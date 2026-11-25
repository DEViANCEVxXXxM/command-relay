# SPDX-License-Identifier: Apache-2.0
"""Local advisory inspection and best-effort export masking. Never executes commands."""
import json
import re

MASK = '[REDACTED]'
SECRET_NAME = r'(?:[A-Za-z0-9_\-]{0,80}[_\-])?(?:password|passwd|pwd|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|client[_-]?secret|secret[_-]?key|secret|private[_-]?key|aws[_-]?secret[_-]?access[_-]?key|authorization|cookie|set-cookie)'
SECRET_KEY = re.compile(r'^(?:\$env:|\$)?'+SECRET_NAME+r'$', re.I)
# Quoted strings (including JSON escapes), or an unquoted value. Authorization/Cookie
# headers get their own whole-line rule. Empty values need no masking.
ASSIGN = re.compile(r'(?i)(?<![\w-])(?:\$env:|\$)?'+SECRET_NAME+r'[\"\']?[ \t]*[:=][ \t]*(?P<value>"(?:\\.|[^"\\\r\n])*"|\'(?:[^\'\r\n])*\'|[^\s,;\r\n}\]"\']+)')
HEADER = re.compile(r'(?im)^[ \t]*(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*(?P<value>[^\r\n]+)')
TOKEN = re.compile(r'(?i)\b(?:Bearer|Basic)[ \t]+(?P<value>[A-Za-z0-9_.~+/=-]{8,})|\b(?P<known>gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b')
URL = re.compile(r'(?i)\b[a-z][a-z0-9+.-]{1,15}://(?P<value>[^\s/@<>"\']+:[^\s/@<>"\']+)@')
PEM = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)')
# Quoted JSON inside log strings and assignment values are handled before serialization.
PATTERNS = (PEM, HEADER, TOKEN, URL, ASSIGN)
MAX_SOURCE = 8_000_000
MAX_ALIASES = 128


def secret_key(key):
    return isinstance(key,str) and SECRET_KEY.fullmatch(key.strip().split(' / ')[-1]) is not None


def value_span(m):
    for name in ('value','known'):
        if name in m.re.groupindex and m.group(name) is not None:
            a,b=m.span(name);v=m.group(name)
            if v.startswith(('"',"'")) and v[-1:]==v[:1]:return a+1,b-1
            return a,b
    return m.span()


def meaningful(v):
    return bool(v.strip()) and v.strip().lower() not in ('[redacted]','[redacted','<redacted>','***','[masked]')


class Masker:
    def __init__(self,source=''):
        self.aliases=set();self.alias_limit_reached=False;self.replacements=0;self.source_limited=len(source)>MAX_SOURCE
        if source:self.collect(source[:MAX_SOURCE])

    def remember(self,v):
        if 8<=len(v)<=4096 and meaningful(v):
            if v not in self.aliases and len(self.aliases)>=MAX_ALIASES:
                self.alias_limit_reached=True;return
            self.aliases.add(v)
            # JSON-escaped representations can also appear in archived metadata.
            escaped=json.dumps(v,ensure_ascii=False)[1:-1]
            if escaped!=v and len(self.aliases)<MAX_ALIASES:self.aliases.add(escaped)

    def collect(self,text):
        for pattern in PATTERNS:
            for m in pattern.finditer(text):
                a,b=value_span(m);self.remember(text[a:b])

    def collect_object(self,obj,sensitive=False):
        if isinstance(obj,dict):
            metric=secret_key(obj.get('key')) or secret_key(obj.get('field'))
            for k,v in obj.items():
                self.collect_object(v,sensitive or secret_key(k) or (metric and k in ('equals','expected','actual','last','before','after','first','examples')))
        elif isinstance(obj,list):
            for v in obj:self.collect_object(v,sensitive)
        elif isinstance(obj,str):
            if sensitive:self.remember(obj)
            self.collect(obj)

    def ready(self):
        self.alias_re=re.compile('|'.join(re.escape(v) for v in sorted(self.aliases,key=lambda x:(-len(x),x)))) if self.aliases else None

    def text(self,text):
        # Merge overlapping matches so a header or PEM never leaves a partial value.
        spans=[]
        for pattern in PATTERNS:
            for m in pattern.finditer(text):
                a,b=value_span(m)
                if meaningful(text[a:b]):spans.append((a,b))
        if self.alias_re:
            spans.extend(m.span() for m in self.alias_re.finditer(text))
        if not spans:return text
        merged=[]
        for a,b in sorted(spans):
            if merged and a<merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:merged.append((a,b))
        out=[];pos=0
        for a,b in merged:
            out.extend((text[pos:a],MASK));pos=b
        out.append(text[pos:]);self.replacements+=len(merged)
        return ''.join(out)

    def object(self,obj,sensitive=False):
        if isinstance(obj,dict):
            metric=secret_key(obj.get('key')) or secret_key(obj.get('field'))
            return {self.text(k):self.object(v,sensitive or secret_key(k) or (metric and k in ('equals','expected','actual','last','before','after','first','examples'))) for k,v in obj.items()}
        if isinstance(obj,list):return [self.object(v,sensitive) for v in obj]
        if sensitive and obj is not None and obj!='':
            self.replacements+=1;return MASK
        return self.text(obj) if isinstance(obj,str) else obj


def protect_packet(packet,source=''):
    masker=Masker(source);masker.collect_object(packet);masker.ready()
    out=masker.object(packet)
    out['privacy']={'status':'redacted' if masker.replacements else 'no_matches',
                    'replacements':masker.replacements,'source_scan_limited':masker.source_limited,'alias_limit_reached':masker.alias_limit_reached,
                    'note':'Best-effort masking, not a privacy guarantee. Original reports are unchanged; hash fields refer to original data. View and line counts describe the original before masking. Review before sharing.'}
    if masker.replacements and 'output' in out:
        out['interpretation'] = out.get('interpretation','') + ' Export values may be masked; assertions and comparisons were evaluated before masking.'
    return out


def protect_text(text,source=''):
    masker=Masker(source);masker.collect(text);masker.ready()
    return masker.text(text),masker.replacements


# Static, intentionally incomplete hints. Do not claim that unmatched scripts are safe.
RULES = (
    ('high','Destructive file or disk operation',r'\bRemove-Item\b[^\r\n]*(?:-Recurse\b|\*)|\b(?:Clear-Disk|Format-Volume|Initialize-Disk|diskpart(?:\.exe)?|format\.com)\b|\bgit\s+(?:clean\s+[^\r\n]*-[a-z]*f|reset\s+--hard|push\s+[^\r\n]*--force)\b'),
    ('high','System security or privilege change',r'\b(?:Set-MpPreference|Add-MpPreference|Set-ExecutionPolicy|Disable-NetFirewallRule|Set-NetFirewallProfile)\b|\b-Verb\s+RunAs\b|\bbcdedit(?:\.exe)?\b'),
    ('high','Dynamic or encoded command execution',r'\b(?:Invoke-Expression|iex)\b|\b-EncodedCommand\b|\bScriptBlock\s*\]\s*::\s*Create\s*\('),
    ('review','Network or remote Git operation',r'\b(?:Invoke-WebRequest|Invoke-RestMethod|iwr|irm|curl(?:\.exe)?|wget|Start-BitsTransfer)\b|\bgit\s+(?:fetch|pull|push|clone|ls-remote)\b'),
    ('review','File or repository changes',r'\b(?:Remove-Item|Set-Content|Add-Content|Out-File|New-Item|Copy-Item|Move-Item|Rename-Item|Set-ItemProperty|Remove-ItemProperty)\b|\bgit\s+(?:add|commit|checkout|switch|merge|rebase|restore|apply|cherry-pick)\b'),
    ('review','Dependency installation',r'\b(?:pip(?:3)?|npm|pnpm|yarn|winget|choco|cargo)\s+(?:install|add|update|upgrade)\b'),
)
RULES=tuple((level,label,re.compile(pattern,re.I)) for level,label,pattern in RULES)
MAX_SCRIPT=1_000_000


def inspect_script(script):
    matches=[];limited=len(script)>MAX_SCRIPT
    text=script[:MAX_SCRIPT].splitlines()
    for level,label,pattern in RULES:
        lines=[]
        for i,line in enumerate(text,1):
            if line.lstrip().startswith('#'):continue
            if pattern.search(line):
                lines.append(i)
                if len(lines)>=5:break
        if lines:matches.append({'level':level,'label':label,'lines':lines})
    level='high' if any(m['level']=='high' for m in matches) else 'review' if matches or limited else 'none'
    return {'level':level,'matches':matches,'scan_limited':limited,'note':'Heuristic text scan only; not a sandbox or safety guarantee. Aliases, indirect commands and effects can be missed.'}
