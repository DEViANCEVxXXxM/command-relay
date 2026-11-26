# SPDX-License-Identifier: Apache-2.0
"""Local test runner: explicit focused tests or full regression with timings."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import subprocess
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timings = []
        self.started = None

    def startTest(self, test):
        super().startTest(test)
        self.started = time.perf_counter()

    def stopTest(self, test):
        self.timings.append((test.id(), time.perf_counter() - self.started))
        super().stopTest(test)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def select_tests(mode, names):
    loader = unittest.TestLoader()
    if mode == 'fast':
        if not names or any(not name.startswith('tests.test_') for name in names):
            raise ValueError('FAST requires explicit tests.test_* module, class or method names')
        suite = loader.loadTestsFromNames(names)
    else:
        if names:
            raise ValueError('STANDARD runs full discovery; do not supply names')
        suite = loader.discover(str(ROOT / 'tests'), top_level_dir=str(ROOT))
    if loader.errors:
        raise ValueError('\n'.join(loader.errors))
    ids = [test.id() for test in flatten(suite)]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Empty selection or overlapping test names; fix selection')
    return suite


_RECEIPT = 'DEV_WORKER_RECEIPT='
_SPLIT = 'tests.test_updates'
_HEAVY = {'UpdateLifecycleIntegrationTests': 9, 'CrossProcessRecoveryTests': 8,
          'HandoffLaunchTests': 6, 'StandaloneTransactionTests': 5,
          'HandoffPreparationTests': 4, 'PendingTransactionTests': 3,
          'RecoveryRehearsalTests': 3, 'GuiHandoffPreparationTests': 3}


def partition(suite, jobs):
    """Keep module fixtures together; split only the audited updater module."""
    groups = defaultdict(list)
    module = importlib.import_module(_SPLIT)
    split = not any(hasattr(module, n) for n in ('setUpModule', 'tearDownModule', 'load_tests'))
    for test in flatten(suite):
        cls = type(test)
        name = cls.__module__
        if name == _SPLIT and split:
            name += '.' + cls.__qualname__
        groups[name].append(test.id())
    def weight(item):
        name, ids = item
        return len(ids) * _HEAVY.get(name.rsplit('.', 1)[-1], 1)
    lanes = [[] for _ in range(min(jobs, len(groups)))]
    costs = [0] * len(lanes)
    for item in sorted(groups.items(), key=lambda item: (-weight(item), item[0])):
        i = min(range(len(lanes)), key=lambda i: (costs[i], i))
        lanes[i].append(item)
        costs[i] += weight(item)
    return lanes


def run_worker(lane):
    expected = sorted(t for _, ids in lane for t in ids)
    cmd = [sys.executable, '-B', str(Path(__file__).resolve()), 'fast',
           *(name for name, _ in lane), '--top', '0', '--worker-receipt']
    result = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding='utf-8', errors='replace', timeout=240)
    receipts = [line[len(_RECEIPT):] for line in result.stdout.splitlines() if line.startswith(_RECEIPT)]
    if len(receipts) != 1:
        raise ValueError('Missing or duplicate worker receipt: '+result.stdout[-8000:])
    data = json.loads(receipts[0])
    if (result.returncode != 0 or not data['passed'] or data['skipped'] != 0
            or data['run'] != len(expected) or sorted(data['ids']) != expected
            or sorted(n for n, _ in data['timings']) != expected):
        raise ValueError('Worker failure, skip or coverage mismatch: '+result.stdout[-8000:])
    return data


def parallel(suite, jobs, top):
    lanes = partition(suite, jobs)
    expected = sorted(t.id() for t in flatten(suite))
    print(f'TEST_WORKERS={len(lanes)}', flush=True)
    start = time.perf_counter()
    receipts = []
    with ThreadPoolExecutor(max_workers=len(lanes)) as pool:
        futures = [pool.submit(run_worker, lane) for lane in lanes]
        for i, future in enumerate(futures, 1):
            try:
                data = future.result()
            except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as exc:
                print(f'TEST_WORKER_FAILED={i} | {exc}', flush=True)
            else:
                receipts.append(data)
                print(f'TEST_WORKER={i} | TESTS={data["run"]} | SECONDS={data["seconds"]:.3f}', flush=True)
    elapsed = time.perf_counter() - start
    timings = [pair for data in receipts for pair in data['timings']]
    passed = len(receipts) == len(lanes) and sorted(n for n, _ in timings) == expected
    print_profile(timings, top)
    print(f'TESTS_RUN={len(timings)}\nTESTS_SKIPPED={sum(d["skipped"] for d in receipts)}\nTEST_SECONDS={elapsed:.3f}')
    print(f'TEST_AGGREGATE_WORKER_SECONDS={sum(d["seconds"] for d in receipts):.3f}')
    print(f'PARALLEL_COVERAGE_VERIFIED={passed}\nUNIT_TESTS_PASS={passed}', flush=True)
    return 0 if passed else 1


def print_profile(timings, top):
    totals = defaultdict(float)
    for name, seconds in timings:
        totals[name.rsplit('.', 2)[0]] += seconds
    for name, seconds in sorted(totals.items(), key=lambda item: (-item[1], item[0])):
        print(f'TEST_MODULE={name} | SECONDS={seconds:.3f}')
    for name, seconds in sorted(timings, key=lambda item: (-item[1], item[0]))[:top]:
        print(f'SLOW_TEST={name} | SECONDS={seconds:.3f}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fast', 'standard'))
    parser.add_argument('names', nargs='*')
    parser.add_argument('--top', type=int, default=12, help='Number of slowest tests to report (0–50)')
    parser.add_argument('--jobs', type=int, default=1, help='STANDARD: 1–4 isolated processes (default sequential)')
    parser.add_argument('--worker-receipt', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.jobs <= 4 or (args.jobs > 1 and args.mode != 'standard') or (args.worker_receipt and args.mode != 'fast'):
        parser.error('--jobs must be 1–4; parallel execution is STANDARD only')
    if not 0 <= args.top <= 50:
        parser.error('--top must be 0–50')
    sys.path.insert(0, str(ROOT))
    try:
        suite = select_tests(args.mode, args.names)
    except ValueError as exc:
        parser.error(str(exc))
    selected = suite.countTestCases()
    print(f'TEST_MODE={args.mode.upper()}\nTESTS_SELECTED={selected}', flush=True)
    if args.jobs > 1:
        return parallel(suite, args.jobs, args.top)
    ids = [test.id() for test in flatten(suite)]
    start = time.perf_counter()
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1, resultclass=TimedResult).run(suite)
    elapsed = time.perf_counter() - start
    print_profile(result.timings, args.top)
    print(f'TESTS_RUN={result.testsRun}\nTESTS_SKIPPED={len(result.skipped)}\nTEST_SECONDS={elapsed:.3f}')
    print(f'TEST_FIXTURE_AND_RUNNER_SECONDS={max(0, elapsed - sum(s for _, s in result.timings)):.3f}')
    passed = result.wasSuccessful() and result.testsRun == selected and result.testsRun > len(result.skipped)
    print(f'UNIT_TESTS_PASS={passed}', flush=True)
    if args.worker_receipt:
        print(_RECEIPT + json.dumps(dict(ids=ids, run=result.testsRun, skipped=len(result.skipped), passed=passed, seconds=elapsed, timings=result.timings)), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
