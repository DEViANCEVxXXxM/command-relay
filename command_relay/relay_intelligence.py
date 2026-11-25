# SPDX-License-Identifier: Apache-2.0
"""Bounded, local result enrichment. No execution or network operations."""
import json, math, pathlib, re

MAX_SCAN = 8_000_000  # Unicode characters; beyond this no inferred result.
MAX_LINE = 16_384
KEY = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}\Z')
KV = re.compile(r'^([A-Z][A-Z0-9_]{2,63})=(.*)$')
HEX = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
MARKERS = ('Cargo.toml','Cargo.lock','package.json','package-lock.json','pnpm-lock.yaml','yarn.lock','pyproject.toml','requirements.txt','requirements-qt.txt','requirements-dev.txt','Pipfile','setup.py','setup.cfg','uv.lock','poetry.lock','CMakeLists.txt','Makefile','go.mod','pom.xml','build.gradle','build.gradle.kts','global.json','Gemfile','composer.json','Dockerfile','tsconfig.json','deno.json','index.html','README.md','README.txt')

TECH_MARKERS = {
    'Rust': {'Cargo.toml','Cargo.lock'},
    'Python': {'pyproject.toml','requirements.txt','requirements-qt.txt','requirements-dev.txt','Pipfile','setup.py','setup.cfg','uv.lock','poetry.lock'},
    'JavaScript / Node.js': {'package.json','package-lock.json','pnpm-lock.yaml','yarn.lock'},
    'TypeScript': {'tsconfig.json'}, 'Deno': {'deno.json'}, 'Web (HTML)': {'index.html'},
    'CMake': {'CMakeLists.txt'}, 'Make': {'Makefile'}, 'Go': {'go.mod'},
    'Maven': {'pom.xml'}, 'Gradle': {'build.gradle','build.gradle.kts'},
    '.NET': {'global.json'}, 'Ruby': {'Gemfile'}, 'PHP': {'composer.json'},
    'Docker': {'Dockerfile'},
}


def scalar(value):
    return (type(value) in (bool,type(None)) or type(value) is int and abs(value)<=2**53-1 or
            type(value) is float and math.isfinite(value) or
            type(value) is str and len(value)<=256)


def validate_assertions(obj):
    if not isinstance(obj,dict) or not obj or set(obj)-{'exit_code','metrics'}:
        raise ValueError('Invalid assertions: use exit_code and/or metrics')
    if 'exit_code' in obj and (type(obj['exit_code']) is not int or not -2147483648<=obj['exit_code']<=2147483647):
        raise ValueError('assertions.exit_code must be an integer (signed 32-bit)')
    checks=obj.get('metrics',[])
    if not isinstance(checks,list) or len(checks)>16 or not checks and 'exit_code' not in obj:
        raise ValueError('assertions.metrics: up to 16 checks; at least one assertion required')
    normalized=[]
    for check in checks:
        if not isinstance(check,dict) or set(check)-{'key','equals','occurrence'} or not isinstance(check.get('key'),str) or not KEY.fullmatch(check['key']) or 'equals' not in check or not scalar(check['equals']) or check.get('occurrence','all') not in ('all','last'):
            raise ValueError('Invalid metric assertion: key, scalar equals, optional occurrence all/last')
        if type(check['equals']) is int and abs(check['equals'])>2**53-1:
            raise ValueError('Metric integer outside exact JSON range')
        normalized.append({'key':check['key'],'equals':check['equals'],'occurrence':check.get('occurrence','all')})
    return {**({'exit_code':obj['exit_code']} if 'exit_code' in obj else {}),'metrics':normalized}


def project_snapshot(workspace):
    """Fixed root marker probes, no enumeration, subprocess, source contents or remote URL."""
    root=pathlib.Path(workspace)
    out={'scope':'workspace_root','markers':[], 'git_head':None,'git_head_status':'unavailable','network':False}
    for name in MARKERS:
        try:
            if (root/name).is_file():out['markers'].append(name)
        except OSError:pass
    present=set(out['markers'])
    out['technology_hints']=[label for label,markers in TECH_MARKERS.items() if present & markers]
    git=root/'.git'
    try:
        if git.is_symlink():return out
        if not git.is_dir():
            out['git_head_status']='worktree_or_gitfile_not_inspected' if git.is_file() else 'no_root_git_directory'
            return out
        def small(path):
            # Never read a ref outside this directory or read a non-file.
            if not path.resolve().is_relative_to(git.resolve()) or not path.is_file():return ''
            with path.open('rb') as f:data=f.read(1025)
            return data.decode('ascii').strip() if len(data)<=1024 else ''
        head=small(git/'HEAD')
        if HEX.fullmatch(head):out.update(git_head=head,git_head_status='detached')
        elif head.startswith('ref: '):
            ref=head[5:]
            if not re.fullmatch(r'refs/[A-Za-z0-9_./-]{1,250}',ref) or any(x in ('','.','..') for x in ref.split('/')):return out
            try: value=small(git/ref)
            except OSError:value=''
            if HEX.fullmatch(value):out.update(git_head=value,git_head_status='loose_ref')
            else:out['git_head_status']='packed_or_unresolved_ref'
    except (OSError,UnicodeError,ValueError,RuntimeError):pass
    return out


def run_metadata(workspace,task,unchanged):
    return {'version':1,'project':project_snapshot(workspace),'task_edited':bool(task and not unchanged),
            'assertions':task.get('assertions') if unchanged else None,
            'task_intent':{k:task[k][:300] for k in ('title','purpose','expected') if unchanged and isinstance(task.get(k),str) and task[k]}}


def report_meta(text):
    # Relay-generated metadata lives only in the header, before its first blank line.
    if not text.startswith('COMMAND RELAY REPORT\n') and not text.startswith('COMMAND RELAY REPORT\r\n'):return {}
    for line in text[:65536].splitlines()[1:]:
        if not line.strip() or line.startswith('@step'):break
        if line.startswith('Relay metadata: '):
            try:
                obj=json.loads(line[16:]);return obj if isinstance(obj,dict) and obj.get('version')==1 else {}
            except (ValueError,RecursionError):return {}
    return {}


def classify(t):
    # Explicit structured data first: a key named Failed is not itself an error.
    m=KV.fullmatch(t)
    values=None
    if m:
        values={m[1]:value_from_text(m[2])}
    elif t.startswith('{') and len(t)<=MAX_LINE:
        try:
            obj=json.loads(t)
            if isinstance(obj,dict):values=obj
        except (ValueError,RecursionError):pass
    if values is not None:
        for key,value in values.items():
            k=key.upper()
            if (k=='PASS' or k.endswith('_PASS')) and value is False:return 'error_like'
            if k in ('FAILED','FAILURES','ERRORS','TESTS_FAILED','TESTS_ERRORS','ERROR_COUNT','FAILED_COUNT') and type(value) in (int,float) and value>0:return 'error_like'
            if k in ('ERROR','EXCEPTION') and isinstance(value,str) and value.strip() and value.lower() not in ('none','null','false','0'):return 'error_like'
        for key,value in values.items():
            k=key.upper()
            if k in ('WARNING','WARNINGS','WARNING_COUNT','WARN_COUNT') and (type(value) in (int,float) and value>0 or isinstance(value,str) and value.strip() and value.lower() not in ('none','null','false','0')):return 'warning_like'
        for key,value in values.items():
            k=key.upper()
            if (k in ('ARTIFACT','OUTPUT_FILE','REPORT_FILE','LOG_FILE','RESULT_DIR','ARTIFACT_PATH') or k.endswith(('_ARTIFACT','_PATH','_FILE','_DIR'))) and isinstance(value,str) and value.strip() and re.match(r'^(?:[A-Za-z]:[\\/]|\\\\|/|\.\.?[\\/])',value):return 'artifact_like'
        return 'structured_like'
    if re.search(r'^test result:|\b(?:tests? passed|tests? failed|tests? skipped|\d+ passed|\d+ failed|\d+ skipped)\b',t,re.I):return 'test_summary'
    if re.search(r'^(?:error(?:\[|:|\s)|fatal:|traceback\b|thread .* panicked|runner error:)|\b(?:FAILED|FAILURE|EXCEPTION)\b',t,re.I):return 'error_like'
    if re.search(r'^(?:warning(?:\[|:|\s)|warn:)|\bWARN(?:ING)?\b',t,re.I):return 'warning_like'
    if re.match(r'^(?:[0-9a-f]{7,64}(?=\s|$)|##\s|ref:\s+refs/)',t,re.I):return 'git_ref'
    if KV.match(t) or t.startswith('{'):return 'structured_like'
    return None


def value_from_text(v):
    if v in ('True','False'):return v=='True'
    if len(v)<=256:
        try:
            value=json.loads(v)
            if scalar(value):return value
            return None
        except (ValueError,RecursionError):pass
    return v if len(v)<=256 else None


def equal(a,b):return type(a) is type(b) and a==b



ARTIFACT_KEYS = frozenset(('ARTIFACT','ARTIFACT_PATH','OUTPUT_FILE','OUTPUT_PATH','REPORT_FILE','LOG_FILE','RESULT_DIR','BUILD_FILE','BUILD_DIR','BINARY_FILE','EVIDENCE_FILE','MANIFEST_FILE'))
MAX_ARTIFACTS = 12

def artifact_hints(t):
    # Explicit output labels only. Never follow, stat, hash or open paths from logs.
    m=KV.fullmatch(t)
    if m and m[1] in ARTIFACT_KEYS:
        v=m[2].strip()
        if v.startswith('"'):
            try:v=json.loads(v)
            except (ValueError,RecursionError):return []
        values={m[1]:v}
    elif t.startswith('{') and any('"'+k+'"' in t for k in ARTIFACT_KEYS):
        try:values=json.loads(t)
        except (ValueError,RecursionError):return []
        if not isinstance(values,dict):return []
    else:return []
    return [(k,v) for k,v in values.items() if k in ARTIFACT_KEYS and isinstance(v,str) and 0<len(v)<=512 and not any(ord(c)<32 for c in v) and re.match(r'^(?:[A-Za-z]:[\\/]|\\\\|/|\.\.?[\\/])',v)]


def enrich(text,packet):
    meta=report_meta(text);raw=meta.get('assertions');edited=meta.get('task_edited') is True
    checks=None
    if raw is not None:
        try:checks=validate_assertions(raw)
        except ValueError:pass
    result={'status':'NOT_REQUESTED','checks':[],'basis':'declared assertions on complete report text; not independent test verification'}
    if edited:result.update(status='INCONCLUSIVE',reason='Imported task was edited; original assertions disabled')
    elif raw is not None and checks is None:result.update(status='INCONCLUSIVE',reason='Invalid stored assertions')
    evidence={'status':'complete','counts':{},'examples':{},'note':'Heuristic text matches, not verified errors or test results; examples bounded.'}
    artifacts={'status':'reported_only','items':[],'limit_reached':False,'note':'Paths reported by task output; existence, contents and creation are not verified. No file access or upload.'}
    out={'project_context':meta.get('project'),'assertions':result,'evidence':evidence,'artifacts':artifacts}
    seen_artifacts=set()
    if len(text)>MAX_SCAN:
        evidence.update(status='not_scanned_size_limit');artifacts['status']='not_scanned_size_limit'
        if checks:result.update(status='INCONCLUSIVE',reason='Report exceeds automatic scan limit')
        return out
    states=[{'count':0,'last':None,'last_line':None,'mismatches':0} for _ in (checks or {}).get('metrics',[])]
    by_key={}
    for i,c in enumerate((checks or {}).get('metrics',[])):by_key.setdefault(c['key'],[]).append(i)
    uncertain=False; stage=False; in_header=text.startswith('COMMAND RELAY REPORT')
    for n,line in enumerate(text.splitlines(),1):
        if re.match(r'^@step\s+\d+\s+—',line):stage=True;in_header=False;continue
        if in_header and not line.strip():stage=True;in_header=False;continue
        if line=='@step END':stage=False;continue
        if not stage:continue
        t=line.strip()
        if len(t)>MAX_LINE:
            evidence['oversized_lines_skipped']=evidence.get('oversized_lines_skipped',0)+1
            if t.startswith('{') or KV.match(t):uncertain=True
            continue
        cat=classify(t)
        if cat and (t.startswith('{') or '=' in t):
            for key,path in artifact_hints(t):
                pair=(key,path)
                if pair in seen_artifacts:continue
                if len(seen_artifacts)>=MAX_ARTIFACTS:artifacts['limit_reached']=True;continue
                seen_artifacts.add(pair);artifacts['items'].append({'key':key,'path':path,'line':n})
        if cat:
            evidence['counts'][cat]=evidence['counts'].get(cat,0)+1
            # Full text already available; no repeated excerpts in small packets.
            if packet['view']!='full':
                examples=evidence['examples'].setdefault(cat,[])
                sample={'line':n,'text':t[:360],'excerpt_truncated':len(t)>360}
                if len(examples)<4:examples.append(sample)
                else:examples[-1]=sample
        if not by_key:continue
        values={};m=KV.fullmatch(t)
        if m and m[1] in by_key:
            v=value_from_text(m[2]);
            if v is None and m[2]!='null':uncertain=True
            else:values[m[1]]=v
        elif t.startswith('{'):
            try:
                obj=json.loads(t)
                if isinstance(obj,dict):
                    for key in by_key.keys() & obj.keys():
                        if scalar(obj[key]):values[key]=obj[key]
                        else:uncertain=True
            except (ValueError,RecursionError):pass
        for key,v in values.items():
            for i in by_key[key]:
                st=states[i];st['count']+=1;st['last']=v;st['last_line']=n
                if not equal(v,checks['metrics'][i]['equals']):st['mismatches']+=1
    if evidence.get('oversized_lines_skipped'):evidence['status']='partial_oversized_lines';artifacts['status']='partial_oversized_lines'
    if not checks:return out
    if edited:return out
    if not packet['report_complete'] or packet['cancelled'] is not False or packet['process_exit'] in (None,'None'):
        result.update(status='INCONCLUSIVE',reason='Incomplete, cancelled or unavailable process exit');return out
    rows=result['checks']
    if 'exit_code' in checks:
        actual=packet['process_exit'];rows.append({'kind':'exit_code','expected':checks['exit_code'],'actual':actual,'status':'PASS' if actual==str(checks['exit_code']) else 'FAIL'})
    else:
        # Unexpected nonzero exit cannot silently become a PASS.
        actual=packet['process_exit'];rows.append({'kind':'exit_code','expected':0,'actual':actual,'implicit':True,'status':'PASS' if actual=='0' else 'FAIL'})
    for c,st in zip(checks['metrics'],states):
        verdict='INCONCLUSIVE' if not st['count'] or uncertain else 'PASS' if (not st['mismatches'] if c['occurrence']=='all' else equal(st['last'],c['equals'])) else 'FAIL'
        rows.append({'kind':'metric',**c,**st,'status':verdict})
    result['status']='FAIL' if any(r['status']=='FAIL' for r in rows) else 'INCONCLUSIVE' if any(r['status']=='INCONCLUSIVE' for r in rows) else 'PASS'
    return out
