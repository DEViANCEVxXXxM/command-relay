# SPDX-License-Identifier: Apache-2.0
"""Build a deterministic, allowlisted portable source release; no local data."""
import argparse
import hashlib
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from command_relay.relay_version import VERSION

RELEASE_FILES = (
    'CHANGELOG.md',
    'CONTRIBUTING.md',
    'DISCLAIMER.md',
    'LICENSE',
    'NOTICE',
    'README.md',
    'SECURITY.md',
    'Start.cmd',
    'Start.pyw',
    'command_relay/__init__.py',
    'command_relay/__main__.py',
    'command_relay/assets/relay-icon.ico',
    'command_relay/assets/relay-icon.png',
    'command_relay/relay_compare.py',
    'command_relay/relay_core.py',
    'command_relay/relay_export.py',
    'command_relay/relay_features.py',
    'command_relay/relay_github.py',
    'command_relay/relay_github_qt.py',
    'command_relay/relay_intelligence.py',
    'command_relay/relay_privacy.py',
    'command_relay/relay_qt.py',
    'command_relay/relay_session.py',
    'command_relay/relay_terms.py',
    'command_relay/relay_version.py',
    'command_relay/relay_view.py',
    'command_relay/relay_windows.py',
    'docs/COMMAND_RELAY_AI_GUIDE.md',
    'docs/architecture.md',
    'docs/disclaimer.md',
    'docs/github-setup.md',
    'docs/manual.txt',
    'examples/example-ai-task.json',
    'examples/example-privacy-task.json',
    'examples/example.txt',
    'requirements.txt',
    'tools/Start-Debug.cmd',
)


def build(output_dir: Path, tag: str | None = None) -> tuple[Path, Path]:
    if not re.fullmatch(r'\d+\.\d+\.\d+', VERSION):
        raise ValueError('VERSION must be a three-part numeric version')
    if tag is not None and tag != f'v{VERSION}':
        raise ValueError(f'Tag {tag!r} does not match v{VERSION}')
    files = list(RELEASE_FILES)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f'command-relay-v{VERSION}-windows'
    archive = output_dir / f'{stem}.zip'
    checksum = output_dir / f'{stem}.sha256'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(files):
            data = (ROOT / name).read_bytes()
            # Git checkout settings must not change bytes of the portable archive.
            if name.endswith('.cmd'):
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            elif not name.endswith(('.ico', '.png')):
                data = data.replace(b'\r\n', b'\n')
            info = zipfile.ZipInfo(f'{stem}/{name}', date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    checksum.write_text(f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n', encoding='ascii', newline='\n')
    return archive, checksum


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist')
    parser.add_argument('--tag', help='Require exact match with application version')
    args = parser.parse_args()
    for path in build(args.out, args.tag):
        print(path)
