"""Extract current ZIPs, verify hashes/assets, and exercise the extracted executable."""
import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path
from release_assets import extension_files
root=Path(__file__).resolve().parent.parent
version=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
release=root/'artifacts/release'/version
checks=0
def check(value,label):
    global checks
    assert value,label
    checks+=1
for line in (release/'SHA256SUMS.txt').read_text().splitlines():
    digest,name=line.split('  ',1)
    check(hashlib.sha256((release/name).read_bytes()).hexdigest()==digest,'Checksum '+name)
with tempfile.TemporaryDirectory(prefix='owlthread-extracted-') as temp:
    for name in (f'OwlThread-Windows-{version}.zip',f'OwlThread-Chrome-Brave-{version}.zip'):
        with zipfile.ZipFile(release/name) as archive:
            check(archive.testzip() is None,'ZIP CRC '+name)
            for item in archive.namelist():
                check((Path(temp)/item).resolve().is_relative_to(Path(temp).resolve()),'ZIP path '+item)
            archive.extractall(temp)
    desktop=Path(temp)/'OwlThread'
    extension=Path(temp)/'OwlThread-extension'
    for file in extension_files(root/'extension'):
        relative=file.relative_to(root/'extension')
        expected=file.read_bytes()
        check((extension/relative).read_bytes()==expected,'Standalone extension '+str(relative))
        check((desktop/'extension'/relative).read_bytes()==expected,'Bundled extension '+str(relative))
    check(json.loads((desktop/'build-provenance.json').read_text())['version']==version,'Provenance version')
    exe=desktop/'owlthread-cli.exe'
    result=subprocess.run([str(exe),'--version'],capture_output=True,text=True,timeout=30,check=True)
    check(result.stdout.strip()=='OwlThread '+version,'Packaged version')
    subprocess.run([sys.executable,str(root/'tools/package_smoke.py'),str(exe)],check=True,cwd=temp,timeout=90)
    check(True,'Extracted CLI/clipboard/MCP integration')
print(json.dumps({'suite':'fresh-archive-verification','checks':checks,'passed':True,'extension_assets':len(extension_files(root/'extension'))}))
