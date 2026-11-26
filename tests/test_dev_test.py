# SPDX-License-Identifier: Apache-2.0
import contextlib
import io
import unittest
from unittest.mock import patch

from tools import dev_test


class DevRunnerTests(unittest.TestCase):
    def test_explicit_selection_and_no_overlap(self):
        name = 'tests.test_terms.TermsTests.test_missing_notice_refused'
        self.assertEqual(dev_test.select_tests('fast', [name]).countTestCases(), 1)
        for names in ([], [name, name], ['tests.test_nonexistent'], ['os']):
            with self.subTest(names=names), self.assertRaises(ValueError):
                dev_test.select_tests('fast', names)
        with self.assertRaises(ValueError):
            dev_test.select_tests('standard', [name])

    def test_runner_propagates_failure_and_rejects_all_skipped(self):
        class Cases(unittest.TestCase):
            def test_ok(self):
                pass

            def test_fail(self):
                self.fail('fixture failure')

            @unittest.skip('fixture skip')
            def test_skip(self):
                pass

        for method, code in [('test_ok', 0), ('test_fail', 1), ('test_skip', 1)]:
            with self.subTest(method=method), patch.object(dev_test, 'select_tests', return_value=unittest.TestSuite([Cases(method)])), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(dev_test.main(['fast', 'tests.test_fixture']), code)
                self.assertIn(f'UNIT_TESTS_PASS={code == 0}', output.getvalue())
                self.assertIn('TESTS_RUN=1', output.getvalue())
                self.assertIn('SLOW_TEST=', output.getvalue())

    def test_parallel_partition_covers_all_tests_once(self):
        suite = dev_test.select_tests('standard', [])
        expected = sorted(t.id() for t in dev_test.flatten(suite))
        for jobs in (2, 3, 4):
            lanes = dev_test.partition(suite, jobs)
            self.assertEqual(len(lanes), jobs)
            names = [n for lane in lanes for n, _ in lane]
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(sorted(t for lane in lanes for _, ids in lane for t in ids), expected)

    def test_worker_rejects_invalid_receipts(self):
        import json
        from subprocess import CompletedProcess
        name = 'tests.test_terms.TermsTests.test_missing_notice_refused'
        valid = dict(ids=[name], run=1, skipped=0, passed=True, seconds=0.1, timings=[[name, 0.1]])
        for changes, code, accept in [({}, 0, True), ({'ids': ['other']}, 0, False),
                                      ({'timings': []}, 0, False), ({'skipped': 1}, 0, False),
                                      ({'passed': False}, 0, False), ({}, 1, False)]:
            data = dict(valid, **changes)
            with self.subTest(changes=changes, code=code), patch.object(dev_test.subprocess, 'run', return_value=CompletedProcess([], code, dev_test._RECEIPT + json.dumps(data))):
                if accept:
                    self.assertEqual(dev_test.run_worker([(name, [name])]), valid)
                else:
                    with self.assertRaises(ValueError):
                        dev_test.run_worker([(name, [name])])
        with patch.object(dev_test.subprocess, 'run', return_value=CompletedProcess([], 0, 'no receipt')):
            with self.assertRaises(ValueError):
                dev_test.run_worker([(name, [name])])

    def test_parallel_failure_cannot_pass(self):
        suite = dev_test.select_tests('fast', ['tests.test_terms.TermsTests.test_missing_notice_refused'])
        with patch.object(dev_test, 'run_worker', side_effect=ValueError('fixture failure')), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(dev_test.parallel(suite, 2, 0), 1)
        self.assertIn('PARALLEL_COVERAGE_VERIFIED=False', out.getvalue())
        self.assertIn('UNIT_TESTS_PASS=False', out.getvalue())
