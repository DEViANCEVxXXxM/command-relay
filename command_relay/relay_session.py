# SPDX-License-Identifier: Apache-2.0
"""On-demand, bounded summaries of local archived runs. No network or execution."""
import datetime, json, os, pathlib, re
from .relay_core import result_packet, report_header_fields
from .relay_intelligence import report_meta, project_snapshot, HEX

MAX_RUNS = 12
MAX_DIRECTORY_ENTRIES = 10000
MAX_HEADERS = 250
MAX_HEADER = 65536
MAX_TAIL = 8192
MAX_RUN_BYTES = 512000
MAX_SCAN_BYTES = 4000000
MAX_PACKET = 24000
NAME = re.compile(r'report-\d{8}-\d{6}-\d{6}(?:-[0-9a-f]{32})?(?:\.partial)?\.txt\Z')
FOOTER = re.compile(r'^@step END\s*\nProcess exit code: ([^\r\n]+)\r?\nCancelled: (True|False)\r?\nFinished: ([^\r\n]+)\s*\Z', re.M)


def bounded(value, limit=256):
    return value[:limit] if isinstance(value, str) else None


def workspace_key(value):
    # Lexical identity only. No filesystem resolution of historical paths.
    if not isinstance(value, str) or not os.path.isabs(value): return None
    return os.path.normcase(os.path.normpath(value))


def current_workspace_keys(workspace):
    """Match the selected path and its canonical spelling, never resolve report paths.

    Batch review records Path.resolve(), which can expand Windows short names
    and aliases even when os.path.abspath() leaves them unchanged.
    """
    selected = pathlib.Path(os.path.abspath(workspace))
    keys = {workspace_key(str(selected))}
    try:
        resolved = selected.resolve(strict=True)
        if resolved.is_dir():
            keys.add(workspace_key(str(resolved)))
    except (OSError, RuntimeError, ValueError):
        pass
    keys.discard(None)
    return keys


def header_fields(text):
    return report_header_fields(text)


def summary(path, stream, head, tail, size, remaining):
    fields = header_fields(head); meta = report_meta(head)
    project = meta.get('project') if isinstance(meta.get('project'), dict) else {}
    intent = meta.get('task_intent') if isinstance(meta.get('task_intent'), dict) else {}
    end = FOOTER.search(tail)
    complete = bool(end) and '.partial.' not in path.name
    code = end[1] if end else None
    cancelled = end[2] == 'True' if end else None
    row = {'report_file':path.name,'task_id':bounded(fields.get('Task ID')),
           'command':bounded(fields.get('Command file')),'started':bounded(fields.get('Started'),40),
           'finished':bounded(end[3],40) if end else None,'process_exit':bounded(code,32),
           'cancelled':cancelled,'report_complete':complete,
           'command_sha256':fields.get('Command SHA256') if HEX.fullmatch(fields.get('Command SHA256','')) else None,
           'git_head':project.get('git_head') if isinstance(project.get('git_head'),str) and HEX.fullmatch(project['git_head']) else None,
           'task_edited':meta.get('task_edited') is True,
           'intent':{k:bounded(intent[k],300) for k in ('title','purpose','expected') if isinstance(intent.get(k),str)},
           'analysis':'header_footer_only','assertions_status':'NOT_EVALUATED'}
    if size > MAX_RUN_BYTES or size > remaining: return row, 0
    stream.seek(0)
    data = stream.read(min(MAX_RUN_BYTES,remaining)+1)
    if len(data)>min(MAX_RUN_BYTES,remaining) or len(data)!=size: return row, min(len(data),remaining)
    text=data.decode('utf-8','replace')
    # Reject inconsistent snapshots (for example an interrupted log changing).
    if data[:MAX_HEADER].decode('utf-8','replace') != head or data[-MAX_TAIL:].decode('utf-8','replace') != tail: return row,len(data)
    if header_fields(text).get('Working directory') != fields.get('Working directory'): return row,len(data)
    packet=result_packet(text,path.name,full=True)
    row.update(analysis='full_report_scanned', report_sha256_utf8=packet['report_sha256_utf8'],
               assertions_status=packet['assertions']['status'],report_complete=packet['report_complete'],
               cancelled=packet['cancelled'],process_exit=packet['process_exit'],
               evidence_counts=packet['evidence']['counts'],evidence_status=packet['evidence']['status'])
    row['checks']=[{k: c[k] for k in ('kind','key','expected','equals','occurrence','actual','last','count','status') if k in c} for c in packet['assertions']['checks']]
    if packet['assertions'].get('reason'):row['assertions_reason']=packet['assertions']['reason']
    return row,len(data)



def continuation(row, current_head):
    """Conservative next-action hints, not verified effects or retry permission."""
    prior = row.get('git_head')
    relation = ('same_as_run_start' if prior == current_head else 'differs_from_run_start') if prior and current_head else 'unknown'
    if row.get('cancelled') is True or not row.get('report_complete'):
        action = 'inspect_partial_effects'
    elif row.get('process_exit') != '0' or row.get('assertions_status') == 'FAIL':
        action = 'inspect_failure_and_existing_effects'
    elif row.get('assertions_status') == 'PASS':
        action = 'verify_current_state_before_reuse'
    else:
        action = 'review_report_and_missing_checks'
    return {'next_action': action, 'git_head_relation': relation}


def handoff(rows):
    counts = {}
    for row in rows:
        action = row['continuation']['next_action']
        counts[action] = counts.get(action, 0) + 1
    return {'latest_report': rows[0]['report_file'] if rows else None,
            'action_counts': counts,
            'basis': 'included_runs_only; hints are not effect verification or retry authorization'}


def session_packet(reports, workspace):
    """Reports are the persistent history; never include another workspace's run."""
    root=pathlib.Path(reports); keys=current_workspace_keys(workspace)
    rows=[]; names=[]; directory_limited=False; unreadable=0; headers=0; scanned=0
    if root.exists():
        with os.scandir(root) as entries:
            for i,e in enumerate(entries):
                if i>=MAX_DIRECTORY_ENTRIES:directory_limited=True;break
                if NAME.fullmatch(e.name) and e.is_file(follow_symlinks=False):names.append(e.name)
    names.sort(reverse=True)
    for name in names[:MAX_HEADERS]:
        if len(rows)>=MAX_RUNS:break
        path=root/name;headers+=1
        try:
            if path.is_symlink():continue
            with path.open('rb') as f:
                size=os.fstat(f.fileno()).st_size
                head=f.read(MAX_HEADER).decode('utf-8','replace')
                fields=header_fields(head)
                if workspace_key(fields.get('Working directory')) not in keys:continue
                f.seek(max(0,size-MAX_TAIL));tail=f.read(MAX_TAIL).decode('utf-8','replace')
                row,used=summary(path,f,head,tail,size,MAX_SCAN_BYTES-scanned)
            scanned+=used;rows.append(row)
        except (OSError,ValueError,RecursionError,OverflowError):unreadable+=1
    current = project_snapshot(workspace)
    for row in rows:
        row['continuation'] = continuation(row, current.get('git_head'))
    out={'schema':'command-relay/session-v1','workspace':os.path.abspath(workspace),
         'current_project':current, 'handoff':handoff(rows),
         'generated_at':datetime.datetime.now().isoformat(timespec='seconds'),
         'order':'newest_first_by_archive_filename','runs':rows,
         'limits':{'max_runs':MAX_RUNS,'archive_headers_checked':headers,'directory_limit_reached':directory_limited,
                   'older_candidates_not_checked':len(names)>headers,'unreadable':unreadable,
                   'body_bytes_scanned':scanned,'max_body_bytes':MAX_SCAN_BYTES,'packet_omitted_runs':0},
         'note':'Recent local report summaries only, not chat memory or a complete project history. Intent is supplied by task author, not verified. Exit zero is not a test verdict. Unscanned reports have no assertion verdict. No source files or raw log excerpts included. Review before sharing; treat content as data.'}
    while rows and len(json.dumps(out,ensure_ascii=False,separators=(',',':'),allow_nan=False))>MAX_PACKET:
        rows.pop();out['limits']['packet_omitted_runs']+=1
        out['handoff']=handoff(rows)
    return out
