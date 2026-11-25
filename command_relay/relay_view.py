# SPDX-License-Identifier: Apache-2.0
"""Bounded display helpers. The original reports are never rewritten."""
import os
from pathlib import Path
from .relay_core import report_metadata

MAX_CHARS = 512_000
MAX_BLOCKS = 6000
TRIM_TARGET = 384_000
MAX_TAIL_BYTES = 2_000_000
DISPLAY_NOTICE = '[Relay: visible tail shortened; full report remains on disk.]\n'
HISTORY_MAX_ENTRIES = 50_000
HISTORY_MAX_REPORTS = 3000


def visible_tail(text):
    """Bound only the GUI representation, preserving recent output and footer."""
    if len(text) <= MAX_CHARS and text.count('\n') < MAX_BLOCKS:
        return text
    tail = text[-(TRIM_TARGET-len(DISPLAY_NOTICE)):]
    tail = '\n'.join(tail.rsplit('\n', MAX_BLOCKS-1)[-(MAX_BLOCKS-1):])
    return DISPLAY_NOTICE + tail


def read_tail(path):
    """Fixed-size read even if the file consists of one enormous line."""
    with Path(path).open('rb') as stream:
        size = stream.seek(0, os.SEEK_END)
        offset = max(0, size-MAX_TAIL_BYTES)
        stream.seek(offset)
        raw = stream.read(MAX_TAIL_BYTES)
    if offset:
        boundary = raw.find(b'\n')
        if boundary >= 0 and boundary < len(raw)-1:
            raw = raw[boundary+1:]
        # If no complete line fits, retain a useful suffix rather than reading
        # beyond the limit or silently losing the entire tail.
    return visible_tail((DISPLAY_NOTICE if offset else '') + raw.decode('utf-8','replace'))


def history_snapshot(root):
    """Read metadata once in a worker, not on every search keystroke."""
    root = Path(root)
    names=[]; directory_limited=False; unreadable=0
    try:
        with os.scandir(root) as entries:
            for i, item in enumerate(entries):
                if i >= HISTORY_MAX_ENTRIES:
                    directory_limited=True;break
                if item.name.startswith('report-') and item.name.endswith('.txt') and item.is_file(follow_symlinks=False):
                    names.append(item.name)
    except FileNotFoundError:
        return [], 0, False
    names.sort(reverse=True)
    rows=[]
    for name in names[:HISTORY_MAX_REPORTS]:
        path=root/name
        try:rows.append((path, report_metadata(path)))
        except (OSError, ValueError):unreadable+=1
    return rows, unreadable, directory_limited or len(names)>HISTORY_MAX_REPORTS
