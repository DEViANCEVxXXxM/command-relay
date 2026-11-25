# SPDX-License-Identifier: Apache-2.0
"""Local, protected export preparation. No clipboard access or network."""
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Optional

from .relay_core import compact_report, result_packet
from .relay_compare import compare_previous
from .relay_intelligence import report_meta
from .relay_privacy import protect_packet, protect_text

WARM_MAX_BYTES = 1_000_000


def stamp(path):
    st = path.stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


@dataclass(frozen=True)
class PreparedExport:
    path: Path
    info: tuple
    text: str
    report_stamp: tuple
    directory_stamp: tuple
    baseline: Optional[Path] = None
    baseline_stamp: Optional[tuple] = None

    def fresh(self):
        try:
            return (stamp(self.path) == self.report_stamp and
                    stamp(self.path.parent) == self.directory_stamp and
                    (self.baseline is None or stamp(self.baseline) == self.baseline_stamp))
        except OSError:
            return False


def build_ai(path, warm=False):
    path = Path(path)
    before = stamp(path)
    directory_before = stamp(path.parent)
    if warm and before[2] > WARM_MAX_BYTES:
        return None
    with path.open('rb') as f:
        data = f.read(WARM_MAX_BYTES + 1) if warm else f.read()
    if warm and len(data) > WARM_MAX_BYTES:
        return None
    text = data.decode('utf-8', errors='replace')
    packet = result_packet(text, path.name)
    verdict = packet['assertions']['status']
    packet['comparison'] = compare_previous(path, text, packet)
    packet['task_inspector'] = report_meta(text).get('inspector')
    baseline = None
    baseline_stamp = None
    name = packet['comparison'].get('baseline_report')
    if name and Path(name).name == name:
        baseline = path.parent / name
        try:
            baseline_stamp = stamp(baseline)
        except OSError:
            baseline_stamp = None
    packet = protect_packet(packet, text)
    out = json.dumps(packet, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if stamp(path) != before:
        raise OSError('Report changed during export')
    # A warm export is only reusable if the archive snapshot still looks current.
    prepared = PreparedExport(path, ('ai', path.name, verdict, packet['privacy']['replacements']),
                              out, before, directory_before, baseline, baseline_stamp)
    if warm and not prepared.fresh():
        return None
    return prepared


def build_copy(path, mode):
    path = Path(path)
    try:
        if mode == 'ai':
            prepared = build_ai(path)
            return prepared.info, prepared.text, None
        before = stamp(path)
        text = path.read_bytes().decode('utf-8', errors='replace')
        if stamp(path) != before:
            raise OSError('Report changed during export')
        if mode == 'full':
            out, masked = text, 0
        elif mode == 'compact':
            out, masked = protect_text(compact_report(text), text)
        else:
            raise ValueError('Unknown copy mode')
        return (mode, path.name, None, masked), out, None
    except Exception:
        return (mode, path.name, None, 0), None, 'Could not prepare requested export'
