# SPDX-License-Identifier: Apache-2.0
"""Bounded, read-only comparison against earlier identical task definitions."""
import os, pathlib
from .relay_core import result_packet
from .relay_intelligence import HEX, report_meta, validate_assertions
from .relay_session import NAME, header_fields, workspace_key

MAX_ENTRIES = 10000
MAX_HEADERS = 100
MAX_HEADER_BYTES = 32768
MAX_BASELINE_BYTES = 512000


def identity(text):
    h = header_fields(text)
    m = report_meta(text)
    key = workspace_key(h.get('Working directory'))
    tid = h.get('Task ID')
    hashes = tuple(h.get(k, '') for k in ('Command SHA256', 'Prepared script SHA256'))
    if not key or not tid or len(tid)>4000 or m.get('task_edited') is not False or not all(HEX.fullmatch(v) and len(v)==64 for v in hashes):
        return None
    try:
        spec = validate_assertions(m['assertions']) if m.get('assertions') is not None else None
    except ValueError:
        return None
    return key, tid, hashes, spec


def usable(packet):
    return (packet['report_complete'] and packet['cancelled'] is False and
            packet['process_exit'] not in (None,'None') and packet['evidence']['status']=='complete' and
            packet['assertions']['status']!='INCONCLUSIVE')


def compare_previous(path, text, current):
    """Only matching, earlier archived runs; never compare unrelated workspaces/scripts."""
    path = pathlib.Path(path)
    out = {'status':'not_available','headers_checked':0,
           'note':'Identical task ID, editor/prepared hashes, assertions and lexical workspace only. Environment, source changes and causality are not verified.'}
    ident = identity(text)
    if not ident or not NAME.fullmatch(path.name) or not usable(current):
        out['reason']='Current run lacks a complete, comparable task identity or evidence';return out
    names=[];limited=False
    try:
        with os.scandir(path.parent) as entries:
            for n,e in enumerate(entries):
                if n>=MAX_ENTRIES:limited=True;break
                if NAME.fullmatch(e.name) and e.name.split('.')[0]<path.name.split('.')[0] and e.is_file(follow_symlinks=False):names.append(e.name)
        # If enumeration was truncated, we cannot assert that the nearest predecessor was seen.
        if limited:out['reason']='Archive directory limit reached';return out
        for name in sorted(names,reverse=True)[:MAX_HEADERS]:
            out['headers_checked']+=1
            p=path.parent/name
            if p.is_symlink():continue
            with p.open('rb') as f:
                head_bytes=f.read(MAX_HEADER_BYTES);head=head_bytes.decode('utf-8','replace')
                if identity(head)!=ident:continue
                out['baseline_report']=name
                if '.partial.' in name:out['reason']='Previous matching run is partial';return out
                if os.fstat(f.fileno()).st_size>MAX_BASELINE_BYTES:out['reason']='Previous matching report exceeds scan limit';return out
                f.seek(0);data=f.read(MAX_BASELINE_BYTES+1)
                if len(data)>MAX_BASELINE_BYTES:out['reason']='Previous matching report exceeds scan limit';return out
            baseline_text=data.decode('utf-8','replace')
            if identity(baseline_text)!=ident or not data.startswith(head_bytes):out['reason']='Previous report changed while reading';return out
            previous=result_packet(baseline_text,name,full=True)
            if not usable(previous):out['reason']='Previous matching run is incomplete, cancelled or inconclusive';return out
            def rev(p):
                project=p.get('project_context');v=project.get('git_head') if isinstance(project,dict) else None
                return v if isinstance(v,str) and HEX.fullmatch(v) else None
            a,b=rev(previous),rev(current)
            out.update(status='compared',baseline_sha256_utf8=previous['report_sha256_utf8'],
                       git_head_before=a,git_head_after=b,git_head_changed=(a!=b if a and b else None),
                       assertion_status_before=previous['assertions']['status'],assertion_status_after=current['assertions']['status'],
                       exit_before=previous['process_exit'],exit_after=current['process_exit'])
            rows=[]
            for old,new in zip(previous['assertions']['checks'],current['assertions']['checks']):
                if old['kind']!='metric' or new['kind']!='metric':continue
                before,after=old['last'],new['last']
                row={'key':new['key'],'occurrence':new['occurrence'],'before':before,'after':after,'count_before':old['count'],'count_after':new['count'],'status_before':old['status'],'status_after':new['status']}
                if type(before) in (int,float) and type(after) is type(before):
                    delta=after-before
                    if abs(delta)<=2**53-1:row['delta']=delta
                rows.append(row)
            out['metrics']=rows
            counts={}
            for key in ('error_like','warning_like','test_summary'):
                before=previous['evidence']['counts'].get(key,0);after=current['evidence']['counts'].get(key,0)
                if before or after:counts[key]={'before':before,'after':after,'delta':after-before}
            out['heuristic_counts']=counts
            return out
        out['reason']='No matching prior run within bounded archive search'
        out['older_candidates_not_checked']=len(names)>MAX_HEADERS
    except (OSError,ValueError,RecursionError,OverflowError,KeyError,TypeError):
        out['reason']='Prior report could not be read or interpreted'
    return out


def previous_run(reports, header):
    """Find the newest identical archived task before Run; never authorize execution.

    Search is bounded and uses the same lexical identity as result comparison.
    A missing or unreadable history is not proof that a task has never run.
    """
    ident = identity(header)
    if ident is None:
        return {'status': 'not_applicable'}
    root = pathlib.Path(reports)
    names = []
    try:
        with os.scandir(root) as entries:
            for n, entry in enumerate(entries):
                if n >= MAX_ENTRIES:
                    return {'status': 'limited', 'reason': 'Archive directory limit reached.'}
                if NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False):
                    names.append(entry.name)
        for name in sorted(names, reverse=True)[:MAX_HEADERS]:
            path = root / name
            if path.is_symlink():
                continue
            with path.open('rb') as stream:
                head = stream.read(MAX_HEADER_BYTES)
                if identity(head.decode('utf-8', 'replace')) != ident:
                    continue
                result = {'status': 'matched', 'report_file': name, 'verdict': 'NOT_EVALUATED'}
                if '.partial.' in name:
                    return dict(result, verdict='INCOMPLETE')
                size = os.fstat(stream.fileno()).st_size
                if size > MAX_BASELINE_BYTES:
                    return dict(result, reason='Matching report exceeds the scan limit.')
                stream.seek(0)
                data = stream.read(MAX_BASELINE_BYTES + 1)
            if len(data) != size or len(data) > MAX_BASELINE_BYTES or not data.startswith(head):
                return dict(result, reason='Matching report changed while reading.')
            text = data.decode('utf-8', 'replace')
            if identity(text) != ident:
                return dict(result, reason='Matching report identity changed while reading.')
            packet = result_packet(text, name, full=True)
            if not packet['report_complete']:
                return dict(result, verdict='INCOMPLETE')
            if packet['cancelled']:
                return dict(result, verdict='CANCELLED')
            verdict = packet['assertions']['status']
            return dict(result, verdict=verdict, process_exit=packet['process_exit'])
        if len(names) > MAX_HEADERS:
            return {'status': 'limited', 'reason': 'Older archive headers were not checked.'}
        return {'status': 'no_match', 'reason': 'No matching report in the checked history.'}
    except FileNotFoundError:
        if not root.exists():
            return {'status': 'no_match', 'reason': 'No archive directory exists.'}
        return {'status': 'unavailable', 'reason': 'An archive disappeared during the check.'}
    except (OSError, ValueError, RecursionError, OverflowError, KeyError, TypeError):
        return {'status': 'unavailable', 'reason': 'History could not be read or interpreted.'}
