"""Verify generated JavaScript is current, then record exact production input hashes."""
import hashlib
import json
import subprocess
import tempfile
import tomllib
from pathlib import Path
from release_assets import extension_files
root=Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as temp:
    subprocess.run(['node',str(root/'extension/node_modules/typescript/bin/tsc'),'-p',str(root/'extension/tsconfig.json'),'--outDir',temp],check=True)
    for path in Path(temp).rglob('*.js'):
        live=root/'extension'/path.relative_to(temp)
        assert live.read_bytes()==path.read_bytes(), 'Stale generated JavaScript: '+str(live)
paths=list((root/'owlthread').rglob('*.py'))+extension_files(root/'extension')
paths += [root/name for name in ('main.py','OwlThread.spec','pyproject.toml','requirements-windows.lock')]
paths += list((root/'extension').glob('*.ts'))+list((root/'extension/popup').glob('*.ts'))
data={'version':tomllib.loads((root/'pyproject.toml').read_text())['project']['version'],
      'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
      'dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True)),
      'sources':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}}
output=root/'artifacts/audit-2026-09-14/build-provenance.json'
output.write_text(json.dumps(data,indent=2)+'\n')
print(f'Verified generated scripts; recorded {len(data["sources"])} input hashes.')
