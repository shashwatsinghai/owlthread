"""Assemble versioned releases from current build provenance and complete assets."""
from __future__ import annotations
import hashlib
import json
import shutil
import sys
import tomllib
import zipfile
from importlib import metadata
from pathlib import Path
from release_assets import extension_files

root=Path(__file__).resolve().parent.parent
version=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
release=root/'artifacts'/'release'/version
release.mkdir(parents=True,exist_ok=True)
dist=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'artifacts'/'dist'/version/'OwlThread'
assert (dist/'OwlThread.exe').is_file(), 'Build OwlThread.spec first'
provenance=root/'artifacts'/'build-provenance.json'
assert provenance.is_file(), 'Record provenance before building'
built=json.loads(provenance.read_text())
assert built['version']==version
for name,digest in built['sources'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest, 'Source changed after build: '+name
for name in ('README.md','LICENSE','SECURITY.md','CHANGELOG.md','CONTRIBUTING.md','requirements-windows.lock'):
    shutil.copy2(root/name,dist/name)
(dist/'docs').mkdir(exist_ok=True)
for path in (root/'docs').glob('*.md'): shutil.copy2(path,dist/'docs'/path.name)
notices=[]
for line in (root/'requirements-windows.lock').read_text().splitlines():
    if not line or line.startswith('#'): continue
    name,locked=line.split('==')
    package=metadata.distribution(name)
    assert package.version==locked, 'Build environment differs from lock: '+name
    notices.append(f'{package.metadata["Name"]} {package.version}: '+str(package.metadata.get('License-Expression') or package.metadata.get('License') or 'See distribution license files'))
    for file in package.files or []:
        if file.name.upper().startswith(('LICENSE','COPYING','NOTICE')) and '.dist-info' in str(file):
            target=dist/'licenses'/name/file.name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(package.locate_file(file),target)
(dist/'THIRD_PARTY_NOTICES.txt').write_text('\n\n'.join(notices)+'\n',encoding='utf-8')
shutil.copy2(provenance,dist/'build-provenance.json')
for name,command in (('Open OwlThread.bat','app'),('Start tray.bat','start')):
    (dist/name).write_bytes(('@echo off\r\nstart "" "%~dp0OwlThread.exe" '+command+'\r\n').encode())
files=extension_files(root/'extension')
with zipfile.ZipFile(release/f'OwlThread-Chrome-Brave-{version}.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        relative=path.relative_to(root/'extension')
        archive.write(path,'OwlThread-extension/'+relative.as_posix())
        target=dist/'extension'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
with zipfile.ZipFile(release/f'OwlThread-Windows-{version}.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(dist.rglob('*')):
        if path.is_file():archive.write(path,'OwlThread/'+path.relative_to(dist).as_posix())
checksums=[]
for path in sorted(release.iterdir()):
    if path.is_file() and path.name!='SHA256SUMS.txt':
        checksums.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}')
(release/'SHA256SUMS.txt').write_text('\n'.join(checksums)+'\n')
print('\n'.join(checksums))
