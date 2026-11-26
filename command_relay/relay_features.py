# SPDX-License-Identifier: Apache-2.0
"""Local, explicit, bounded utilities. No AI service or automatic execution."""
import datetime, hashlib, json, math, os, pathlib, re, stat, subprocess, tempfile, zipfile
from dataclasses import dataclass
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


# User extensions are inert data, not importable Python modules or grants.
SKILL_LIMIT = 128_000
SKILL_COUNT_LIMIT = 100
SKILL_SCHEMA = 'command-relay/skill-v1'


def user_data_root():
    """Per-account data, independent of the portable installation directory."""
    if os.name == 'nt':
        base = pathlib.Path(os.environ.get('LOCALAPPDATA') or pathlib.Path.home() / 'AppData' / 'Local')
    else:
        base = pathlib.Path(os.environ.get('XDG_DATA_HOME') or pathlib.Path.home() / '.local' / 'share')
    if not base.is_absolute():
        raise ValueError('User data base must be absolute')
    return base / 'CommandRelay' / 'User'


def _skill_unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Duplicate skill JSON key')
        obj[key] = value
    return obj


def _skill_constant(value):
    raise ValueError('Invalid skill JSON constant')


@dataclass(frozen=True)
class UserSkill:
    skill_id: str
    revision: int
    title: str
    description: str
    instructions: str
    task_bytes: bytes | None
    raw: bytes
    digest: str

    @property
    def filename(self):
        return f'skill-{self.skill_id}--v{self.revision}.json'


def load_skill(data):
    """Validate a bounded manifest; never dispatch commands or import modules."""
    from .relay_core import load_input, prepare
    if type(data) is not bytes or not 0 < len(data) <= SKILL_LIMIT:
        raise ValueError('Invalid skill manifest size')
    try:
        obj = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_skill_unique,
                         parse_constant=_skill_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError('Invalid skill JSON') from exc
    required = {'schema', 'id', 'revision', 'title', 'description', 'instructions'}
    if type(obj) is not dict or not required <= set(obj) or set(obj) - required - {'task'} or obj['schema'] != SKILL_SCHEMA:
        raise ValueError('Unsupported skill manifest fields or schema')
    key, revision = obj['id'], obj['revision']
    if type(key) is not str or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', key) or type(revision) is not int or not 1 <= revision <= 999999:
        raise ValueError('Invalid skill ID or revision')
    for field, limit in [('title', 120), ('description', 4000), ('instructions', 24000)]:
        value = obj[field]
        if type(value) is not str or not value.strip() or len(value) > limit or '\x00' in value:
            raise ValueError('Invalid skill field: ' + field)
        try: value.encode('utf-8')
        except UnicodeError as exc: raise ValueError('Invalid skill text encoding') from exc
    task = None
    if 'task' in obj:
        packet = obj['task']
        allowed = {'schema','task_id','title','purpose','expected','workspace_hint','language','script','assertions'}
        if (type(packet) is not dict or packet.get('schema') != 'command-relay/task-v1'
                or set(packet) - allowed or not isinstance(packet.get('task_id'), str)
                or not packet['task_id'].strip() or 'assertions' not in packet):
            raise ValueError('Skill template requires task-v1 with ID and assertions')
        try:
            task = json.dumps(packet, ensure_ascii=False, allow_nan=False).encode('utf-8')
            script, _ = load_input(task)
            prepare(script).encode('utf-8')
        except (UnicodeError, RecursionError) as exc:
            raise ValueError('Invalid skill template encoding') from exc
    return UserSkill(key, revision, obj['title'], obj['description'], obj['instructions'], task,
                     data, hashlib.sha256(data).hexdigest())


def _checked_skill_path(path, *, directory):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError('Skill store refuses links, reparse points and special files')
    return path


class UserSkillStore:
    """Explicit, local store. Same-account edits are not a security boundary.

    No discovery at application startup, no automatic import, no permissions.
    Revisions are retained; installing a different body over an existing revision
    is rejected. Unknown and malformed files never become runnable templates.
    """
    def __init__(self, root=None):
        self.root = pathlib.Path(root) if root is not None else user_data_root()
        if not self.root.is_absolute():
            raise ValueError('User skill root must be absolute')
        self.folder = self.root / 'skills'

    def ensure(self):
        # Check our own directories, not the OS-owned profile parent (which may
        # legitimately be redirected). This is not a defense against concurrent
        # malicious changes by another process running as the same user.
        self.root.parent.mkdir(parents=True, exist_ok=True)
        _checked_skill_path(self.root.parent, directory=True)
        self.root.mkdir(exist_ok=True)
        _checked_skill_path(self.root, directory=True)
        self.folder.mkdir(exist_ok=True)
        return _checked_skill_path(self.folder, directory=True)

    def read(self, filename):
        if type(filename) is not str or not re.fullmatch(r'skill-[a-z0-9][a-z0-9-]{0,63}--v[1-9][0-9]{0,5}\.json', filename):
            raise ValueError('Invalid skill filename')
        path = self.ensure() / filename
        _checked_skill_path(path, directory=False)
        skill = load_skill(read_bounded(path, SKILL_LIMIT))
        if skill.filename != filename:
            raise ValueError('Skill filename does not match manifest identity')
        return skill

    def scan(self):
        from itertools import islice
        folder = self.ensure()
        # Bound directory enumeration as well as manifest parsing. An oversized
        # directory is not silently presented as a complete library.
        with os.scandir(folder) as entries:
            paths = list(islice(entries, SKILL_COUNT_LIMIT + 1))
        if len(paths) > SKILL_COUNT_LIMIT:
            raise ValueError('Skill folder exceeds 100 entries; move unused files elsewhere')
        skills, errors = [], []
        for entry in sorted(paths, key=lambda item: item.name):
            if not entry.name.endswith('.json'):
                continue
            try: skills.append(self.read(entry.name))
            except (OSError, ValueError) as exc: errors.append((entry.name, str(exc)))
        skills.sort(key=lambda item: (item.title.casefold(), item.skill_id, -item.revision))
        return tuple(skills), tuple(errors)

    def install(self, data):
        from .relay_core import publish_attempt_report
        skill = load_skill(data)
        folder = self.ensure()
        target = folder / skill.filename
        try:
            existing = self.read(skill.filename)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing.digest != skill.digest:
                raise ValueError('Revision already exists with different content; use a new revision')
            return existing
        # No overwrite, including simultaneous imports. Only manifest bytes.
        with os.scandir(folder) as entries:
            from itertools import islice
            if len(list(islice(entries, SKILL_COUNT_LIMIT))) >= SKILL_COUNT_LIMIT:
                raise ValueError('Skill folder is full')
        publish_attempt_report(target, data)
        return skill

# Browser Bridge receives only explicit JSON task/batch packets, never arbitrary
# downloads, scripts, report packets, browser cookies or local file paths.
def browser_origin(url):
    from urllib.parse import urlsplit
    if not isinstance(url, str) or not url or len(url) > 8192 or any(c.isspace() or ord(c) < 32 for c in url) or '\\' in url:
        raise ValueError('Invalid provider URL')
    try:
        p = urlsplit(url)
        host = p.hostname
        port = p.port
        if not host or p.username is not None or p.password is not None or '%' in host:
            raise ValueError('Invalid provider URL')
        if p.scheme != 'https' and not (p.scheme == 'http' and host in ('127.0.0.1', '::1', 'localhost')):
            raise ValueError('Use HTTPS or an explicit loopback HTTP URL')
        if port == 0:
            raise ValueError('Invalid provider port')
        host = host.encode('idna').decode('ascii').lower()
        return p.scheme, host, port or (443 if p.scheme == 'https' else 80)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Use a valid HTTPS or loopback provider URL without credentials') from exc


def browser_download_allowed(page_url, download_url, filename, size):
    try:
        origin = browser_origin(page_url)
        target = download_url[5:] if download_url.startswith('blob:') else download_url
        return (browser_origin(target) == origin and isinstance(filename, str)
                and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,119}\.json', filename, re.I))
                and type(size) is int and -1 <= size <= 1_000_000)
    except (ValueError, AttributeError, TypeError):
        return False


def browser_task_packet(data):
    from .relay_core import PACKET_LIMIT, load_input, load_batch, prepare
    if type(data) is not bytes or not 0 < len(data) <= PACKET_LIMIT:
        raise ValueError('Browser task packet exceeds limit or is empty')
    try:
        obj = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_skill_unique,
                         parse_constant=_skill_constant)
        if type(obj) is not dict:
            raise ValueError('Browser input must be a task or batch packet')
        if obj.get('schema') == 'command-relay/task-v1':
            allowed = {'schema', 'language', 'task_id', 'title', 'purpose', 'expected', 'workspace_hint', 'script', 'assertions'}
            if set(obj) - allowed:
                raise ValueError('Unexpected task fields')
            script, _ = load_input(data)
            prepare(script)
        elif obj.get('schema') == 'command-relay/batch-v1':
            load_batch(data)
        else:
            raise ValueError('Browser input must be a task or batch packet')
        return obj['schema']
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise ValueError('Invalid or unsupported browser task packet') from exc



# Fixed isolated-world helpers: user data is serialized as a JSON literal,
# never treated as executable JavaScript. No click, submit or network action.
BROWSER_DRAFT_LIMIT = 120_000

def browser_draft_script(url, nonce, text=None):
    browser_origin(url)
    if not isinstance(nonce,str) or not re.fullmatch(r'[0-9a-f]{32}',nonce):
        raise ValueError('Invalid draft token')
    if text is not None and (not isinstance(text,str) or not 0 < len(text) <= BROWSER_DRAFT_LIMIT):
        raise ValueError('Invalid draft length')
    args=json.dumps([url,nonce,text],ensure_ascii=True)
    return """((url, nonce, text) => {
      const el = document.activeElement;
      const valid = () => location.href === url && el instanceof HTMLTextAreaElement &&
        el.isConnected && !el.disabled && !el.readOnly && el.value === '' &&
        el.getClientRects().length > 0;
      if (text === null) {
        globalThis.__relayDraftTarget = null;
        if (!valid()) return false;
        globalThis.__relayDraftTarget = {nonce, el};
        return true;
      }
      const target = globalThis.__relayDraftTarget;
      globalThis.__relayDraftTarget = null;
      if (!valid() || !target || target.nonce !== nonce || target.el !== el ||
          (el.maxLength >= 0 && text.length > el.maxLength)) return false;
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, text);
      el.dispatchEvent(new Event('input', {bubbles:true}));
      return el.value === text;
    })(..."""+args+")"


def runtime_diagnostics(workspace, reports, *, max_entries=1000):
    """Read-only snapshot. No tool launches, PATH changes or report deletion."""
    import shutil, sys
    from .relay_session import NAME
    if not isinstance(max_entries, int) or not 1 <= max_entries <= 10000:
        raise ValueError('Invalid diagnostic scan limit')
    root = pathlib.Path(reports)
    tools = {}
    for name in ('powershell.exe', 'pwsh', 'git', 'gh', 'python'):
        tools[name] = bool(shutil.which(name))
    selected = pathlib.Path(workspace)
    partial = []; scanned = 0; limited = False; archive_status = 'available'
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if scanned >= max_entries:
                    limited = True; break
                scanned += 1
                if entry.name.endswith('.partial.txt') and NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False):
                    partial.append(entry.name)
    except FileNotFoundError:
        archive_status = 'missing'
    except OSError:
        archive_status = 'unreadable'
    try:
        free = shutil.disk_usage(selected).free if selected.is_dir() else None
    except OSError:
        free = None
    return {'schema':'command-relay/diagnostics-v1', 'platform':sys.platform,
            'python_version':sys.version.split()[0], 'workspace_available':selected.is_dir(),
            'workspace_free_bytes':free, 'tools_on_current_path':tools,
            'archive':{'status':archive_status,'entries_scanned':scanned,'scan_limited':limited,
                       'partial_reports_observed':len(partial),'partial_report_names':sorted(partial)[-20:]},
            'recovery':{'partial_reports':'Inspect existing effects before retry; partial does not prove a process stopped.',
                        'missing_tools':'Install or locate the tool explicitly; restart Relay after changing PATH.',
                        'automatic_retry':False},
            'note':'Local snapshot, not a health or execution guarantee. No commands launched or configuration changed.'}


# Bounded autonomy is a separate protocol, never a PowerShell task or a plugin.
PLAN_SCHEMA = 'command-relay/plan-v1'
PLAN_OPERATIONS = ('workspace_inventory', 'disk_space', 'project_markers')
PLAN_SECONDS = 15
PLAN_ENTRY_LIMIT = 1000


@dataclass(frozen=True)
class LocalPlan:
    operations: tuple
    digest: str


def load_local_plan(data):
    if not isinstance(data, bytes) or not 1 <= len(data) <= 8192:
        raise ValueError('Invalid plan size')
    try:
        obj = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_skill_unique,
                         parse_constant=_skill_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError('Invalid plan JSON') from exc
    if not isinstance(obj, dict) or set(obj) != {'schema', 'operations'} or obj['schema'] != PLAN_SCHEMA:
        raise ValueError('Unsupported plan schema or fields')
    ops = obj['operations']
    if (not isinstance(ops, list) or not 1 <= len(ops) <= len(PLAN_OPERATIONS)
            or any(not isinstance(op, str) or op not in PLAN_OPERATIONS for op in ops)
            or len(set(ops)) != len(ops)):
        raise ValueError('Only distinct built-in plan operations are supported')
    return LocalPlan(tuple(ops), hashlib.sha256(data).hexdigest())


def _plan_scope(workspace):
    path = pathlib.Path(workspace)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Select an absolute local workspace')
    if os.name == 'nt':
        import ctypes
        # No UNC, mapped network, removable, or device paths.
        if not re.fullmatch(r'[A-Za-z]:', path.drive):
            raise ValueError('Select a fixed local drive')
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        drive_type.restype = ctypes.c_uint
        if drive_type(path.anchor) != 3:
            raise ValueError('Select a fixed local drive')
    identity = []
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('Plan scope must not contain links or reparse points')
        identity.append((info.st_dev, info.st_ino))
    return path, tuple(identity)


class _PlanStopped(Exception):
    pass


def _plan_operation(op, root, check):
    # Fixed dispatch, no subprocess, arbitrary path, read of file contents, or write.
    if op == 'disk_space':
        import shutil
        disk = shutil.disk_usage(root)
        return {'total_bytes': disk.total, 'free_bytes': disk.free}
    if op == 'project_markers':
        markers = {}
        for name in ('README.md', 'requirements.txt', 'pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod'):
            check()
            try:
                info = (root / name).lstat()
            except FileNotFoundError:
                markers[name] = False
            else:
                markers[name] = stat.S_ISREG(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400
        return {'ordinary_marker_present': markers}
    if op != 'workspace_inventory':
        raise ValueError('Unsupported operation')
    count = files = directories = other = size = 0
    limited = False
    with os.scandir(root) as entries:
        for entry in entries:
            check()
            if count >= PLAN_ENTRY_LIMIT:
                limited = True; break
            info = entry.stat(follow_symlinks=False)
            count += 1
            if getattr(info, 'st_file_attributes', 0) & 0x400:
                other += 1
            elif stat.S_ISREG(info.st_mode):
                files += 1; size += info.st_size
            elif stat.S_ISDIR(info.st_mode):
                directories += 1
            else:
                other += 1
    return {'entries_observed': count, 'ordinary_files': files, 'directories': directories,
            'other_entries': other, 'ordinary_file_bytes': size, 'scan_limited': limited}


class ReviewedLocalPlan:
    """One-use scope-bound review. Not a sandbox or a grant for arbitrary tasks."""
    def __init__(self, data, workspace):
        import threading
        self.plan = load_local_plan(data)
        self.root, self.identity = _plan_scope(workspace)
        self._lock = threading.Lock()
        self._used = False

    def run(self, cancel):
        import time
        with self._lock:
            if self._used:
                raise ValueError('Plan review already used')
            self._used = True
        deadline = time.monotonic() + PLAN_SECONDS
        rows = []; status = 'complete'
        def check():
            if cancel.is_set(): raise _PlanStopped('cancelled')
            if time.monotonic() >= deadline: raise _PlanStopped('time_limit')
        for op in self.plan.operations:
            try:
                check()
                if _plan_scope(self.root)[1] != self.identity:
                    raise _PlanStopped('scope_changed')
                result = _plan_operation(op, self.root, check)
                check()
                if _plan_scope(self.root)[1] != self.identity:
                    raise _PlanStopped('scope_changed')
                rows.append({'operation': op, 'result': result})
                if result.get('scan_limited'):
                    status = 'entry_limit'; break
            except _PlanStopped as exc:
                status = str(exc); break
            except (OSError, ValueError):
                status = 'unknown_or_unavailable'; break
        return {'schema': 'command-relay/plan-result-v1', 'plan_sha256': self.plan.digest,
                'status': status, 'operations_requested': list(self.plan.operations),
                'operations_completed': len(rows), 'results': rows,
                'automatic_retry': False, 'note': 'Local metadata only. Cooperative time/cancel checks; a blocked OS call may delay stop. No file contents, commands, writes or automatic transfer.'}
