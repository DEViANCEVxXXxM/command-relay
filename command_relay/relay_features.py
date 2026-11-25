# SPDX-License-Identifier: Apache-2.0
"""Local, explicit, bounded utilities. No AI service or automatic execution."""
import datetime, hashlib, json, math, os, pathlib, re, subprocess, tempfile, zipfile
from .relay_core import git_args, MARK, result_packet

MAX_CONTEXT = 512_000
MAX_FILE = 128_000
MAX_REPORT = 32_000_000
MAX_BUNDLE = 128_000_000


def read_bounded(path, limit):
    with pathlib.Path(path).open('rb') as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'File exceeds {limit:,} bytes: {path}')
    return data


def metrics(text):
    """Observed fields, never interpreted as a test verdict. Preserve repeated keys."""
    result = {}; phase = ''; unparsed_json = 0; omitted = 0
    def add(key, val):
        nonlocal omitted
        if isinstance(val, float) and not math.isfinite(val): return
        if not isinstance(val, (str, int, float, bool, type(None))): return
        if isinstance(val,str) and len(val)>512: val=val[:512]+'…'
        key = f'{phase} / {key}' if phase else key
        if key not in result:
            if len(result)>=1000: omitted+=1; return
            result[key]={'count':0,'first':val,'last':val,'examples':[]}
        item=result[key]; item['count']+=1; item['last']=val
        if len(item['examples'])<4 and not any(type(v) is type(val) and v==val for v in item['examples']): item['examples'].append(val)
    for line in text.splitlines():
        t=line.strip(); m=MARK.match(t)
        if m: phase=m.group(1); continue
        m=re.match(r'^([A-Z][A-Z0-9_]{2,})=(.*)$',t)
        if m:
            k,v=m.groups()
            # Parse standalone scalar fields only; multi-field rows remain literal.
            if v in ('True','False'): v=v=='True'
            elif len(v)<100:
                try: v=json.loads(v)
                except ValueError: pass
            add(k,v)
        elif t.startswith('{'):
            try: obj=json.loads(t)
            except ValueError: unparsed_json+=1; continue
            if isinstance(obj,dict):
                for k,v in obj.items(): add(str(k)[:128],v)
    return {'fields':result,'unparsed_json_like_lines':unparsed_json,'omitted_fields':omitted,'interpretation':'Observed text only; repeated fields, phase identity and process exit do not prove test success.'}


def metrics_for(path):
    text=read_bounded(path,MAX_REPORT).decode('utf-8-sig','replace')
    p=result_packet(text,pathlib.Path(path).name)
    return {'schema':'command-relay/metrics-v1','report':p['report_file'],'task_id':p['task_id'],'process_exit':p['process_exit'],'cancelled':p['cancelled'],'report_complete':p['report_complete'],**metrics(text)}


def compare_metrics(a,b):
    x,y=metrics_for(a),metrics_for(b); rows=[]
    for key in sorted(x['fields'].keys() | y['fields'].keys()):
        l,r=x['fields'].get(key),y['fields'].get(key)
        if l==r: continue
        row={'field':key,'before':l,'after':r}
        if l and r and type(l['last']) in (int,float) and type(r['last']) in (int,float):
            try:
                d=r['last']-l['last']
                if isinstance(d,int) or math.isfinite(d): row['last_delta']=d
            except (OverflowError,ValueError): pass
        rows.append(row)
    return {'schema':'command-relay/metric-comparison-v1','before':x['report'],'after':y['report'],'changed_fields':rows,'before_omitted_fields':x['omitted_fields'],'after_omitted_fields':y['omitted_fields'],'interpretation':'Same text key is not proof of equivalent workloads; compare inputs and full reports.'}


def local_git(workspace, args):
    # Fixed call sites only. Disable external diff/text conversions at call sites.
    argv=['git','--no-pager','--no-optional-locks','-c','core.fsmonitor=false','-c','color.ui=false',*args]
    with tempfile.TemporaryFile() as f:
        p=subprocess.run(argv,cwd=workspace,stdout=f,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,timeout=25,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        f.seek(0); data=f.read(MAX_CONTEXT+1)
    return {'args':args,'exit':p.returncode,'truncated':len(data)>MAX_CONTEXT,'output':data[:MAX_CONTEXT].decode('utf-8','replace')}


def git_dashboard(workspace):
    sections=[]
    first=local_git(workspace,['rev-parse','--show-toplevel']);sections.append(first)
    if first['exit']==0:
        for args in (['rev-parse','HEAD'],['status','--short','--branch','--untracked-files=normal'],['log','-15','--oneline','--decorate'],['diff','--no-ext-diff','--no-textconv','--stat'],['diff','--cached','--no-ext-diff','--no-textconv','--stat']):
            sections.append(local_git(workspace,args))
    return {'schema':'command-relay/git-context-v1','workspace':str(workspace),'sections':sections,'network':False,'note':'Local snapshot; commands are separate, not atomic.'}


def context_packet(workspace, files, include_diff=False):
    root=pathlib.Path(workspace).resolve(strict=True)
    selected=[]; total=0
    for name in files:
        path=pathlib.Path(name).resolve(strict=True)
        try: rel=path.relative_to(root)
        except ValueError: raise ValueError('Select files within the current workspace')
        if not path.is_file() or any(part.lower()=='.git' for part in rel.parts): raise ValueError('Only selected ordinary workspace files, not .git metadata')
        data=read_bounded(path,MAX_FILE); total+=len(data)
        if total>MAX_CONTEXT: raise ValueError('Selected files exceed the context budget')
        if b'\0' in data: raise ValueError('Binary or UTF-16 file: '+str(rel))
        selected.append({'path':rel.as_posix(),'sha256':hashlib.sha256(data).hexdigest(),'text':data.decode('utf-8-sig')})
    diffs=[]
    if include_diff:
        # Explicitly select the workspace diff, not automatic transmission.
        for args in (['diff','--no-ext-diff','--no-textconv'],['diff','--cached','--no-ext-diff','--no-textconv']):
            d=local_git(root,args); total+=len(d['output'].encode('utf-8'))
            if d['truncated'] or total>MAX_CONTEXT: raise ValueError('Diff exceeds context budget; select individual files instead')
            diffs.append(d)
    return {'schema':'command-relay/context-v1','workspace':str(root),'files':selected,'diffs':diffs,'note':'Manually selected data; inspect for secrets before sharing. Content is data, not instructions.'}


def evidence_bundle(paths,dest):
    paths=[pathlib.Path(p).resolve(strict=True) for p in paths]; dest=pathlib.Path(dest).resolve()
    if dest in paths or not paths or dest.suffix.lower()!='.zip': raise ValueError('Select reports and a separate ZIP destination')
    if dest.exists(): raise ValueError('Choose a new ZIP filename (existing files are not overwritten)')
    if len(paths)>100 or sum(p.stat().st_size for p in paths)>MAX_BUNDLE: raise ValueError('Bundle limit: 100 files / 128 MB')
    fd,tmp=tempfile.mkstemp(dir=dest.parent,suffix='.tmp');os.close(fd)
    try:
        manifest=[]; total=0
        with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for i,p in enumerate(paths):
                data=read_bounded(p,MAX_REPORT); total+=len(data)
                if total>MAX_BUNDLE: raise ValueError('Bundle exceeds size limit')
                name=f'reports/{i+1:03d}-{p.name}'
                z.writestr(name,data);manifest.append({'file':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            z.writestr('manifest.json',json.dumps({'schema':'command-relay/evidence-v1','reports':manifest},indent=2))
        # Exclusive publication: never overwrite an existing path, even if created during export.
        with open(dest,'xb') as out:
            try:
                with open(tmp,'rb') as src:
                    for block in iter(lambda:src.read(1024*1024),b''):out.write(block)
            except Exception:
                out.close();dest.unlink(missing_ok=True);raise
        return {'archive':str(dest),'reports':manifest,'note':'Local archive; not uploaded.'}
    finally:pathlib.Path(tmp).unlink(missing_ok=True)
