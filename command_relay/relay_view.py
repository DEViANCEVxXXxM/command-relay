# SPDX-License-Identifier: Apache-2.0
"""Bounded display helpers. The original reports are never rewritten."""
import os
from pathlib import Path
from .relay_core import report_metadata

# Shared semantic colors. Explicit preference; unknown values retain the established dark theme.
THEMES = ('dark', 'light')
_THEME_COLORS = {
    'dark': dict(canvas='#181a1e', surface='#212429', raised='#292d33', hover='#353b44',
                 border='#424951', text='#e2e5e9', muted='#aab2bd', disabled='#87909b',
                 accent='#1767b0', accent_hover='#145a98', focus='#82bfff', selection='#284b70',
                 selected_text='#ffffff', on_accent='#ffffff', thumb='#697582',
                 info='#85baff', error='#ff9b90', success='#a9d6a4', warning='#f2cc85', metric='#a7d9fa'),
    'light': dict(canvas='#f3f5f7', surface='#ffffff', raised='#e8edf2', hover='#dce4ed',
                  border='#a0acba', text='#222b36', muted='#455568', disabled='#596879',
                  accent='#1767b0', accent_hover='#145a98', focus='#1767b0', selection='#d0e4fa',
                  selected_text='#17283b', on_accent='#ffffff', thumb='#8593a4',
                  info='#15559a', error='#a12d28', success='#216641', warning='#78520b', metric='#225d86'),
}


def saved_theme(settings):
    value = settings.get('theme')
    return value if isinstance(value, str) and value in THEMES else 'dark'


def theme_colors(theme):
    """Return independent tokens; invalid preferences cannot produce arbitrary QSS."""
    return dict(_THEME_COLORS[saved_theme({'theme': theme})])


MAX_CHARS = 512_000
MAX_BLOCKS = 6000
TRIM_TARGET = 384_000
MAX_TAIL_BYTES = 2_000_000
DISPLAY_NOTICE = '[Relay: visible tail shortened; full report remains on disk.]\n'
HISTORY_MAX_ENTRIES = 50_000
HISTORY_MAX_REPORTS = 3000
HISTORY_PAGE_SIZE = 100


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


def history_snapshot(root, *, include_identity=False):
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
        try:rows.append((path, report_metadata(path, include_identity=include_identity)))
        except (OSError, ValueError):unreadable+=1
    return rows, unreadable, directory_limited or len(names)>HISTORY_MAX_REPORTS


HISTORY_DETAIL_MAX_BYTES = 1_000_000


def history_text(value, limit=300):
    """Bound single-line untrusted report presentation, never interpret markup."""
    return ''.join(c if c.isprintable() else ' ' for c in value[:limit]).strip()


def history_title(path, row):
    return history_text(row[6]) or history_text(row[1]) or path.name


def history_matches(path, row, query, kind):
    date, name, status, duration, workspace, tag, title, task_id = row
    hay=' '.join((path.name,date,name,status,workspace,title,task_id)).casefold()
    return query.strip().casefold() in hay and (
        kind=='All' or (kind=='Exit 0' and status=='Exit 0') or
        (kind=='Failed' and tag=='error') or (kind=='Cancelled' and status=='Cancelled') or
        (kind=='Partial / unknown' and status in ('Partial','Unknown','Exit None')))


def history_page(snapshot, query, kind, limit):
    """Search every loaded header, but materialize only the requested prefix."""
    if type(limit) is not int or limit < 1:
        raise ValueError('Positive history display limit required')
    visible = []
    count = 0
    for path, row in snapshot:
        if history_matches(path, row, query, kind):
            count += 1
            if len(visible) < limit:
                visible.append((path, row))
    return visible, count


def history_assertions(path):
    """Evaluate only the selected report, with a bounded read. Never infer PASS from exit 0."""
    from .relay_core import result_packet
    path=Path(path)
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        raw=stream.read(HISTORY_DETAIL_MAX_BYTES+1)
        after=os.fstat(stream.fileno())
    if len(raw)>HISTORY_DETAIL_MAX_BYTES:return ('LIMITED',0,0)
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):return ('INCONCLUSIVE',0,0)
    result=result_packet(raw.decode('utf-8',errors='replace'),path.name)['assertions']
    checks=result['checks']
    return (result['status'],sum(c['status']=='PASS' for c in checks),len(checks))
