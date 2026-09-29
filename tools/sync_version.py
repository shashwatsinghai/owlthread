"""pyproject.toml owns the version; regenerate mirrors before release."""
import json
import re
import tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
init=ROOT/'owlthread/__init__.py'
init.write_text(re.sub(r'__version__ = ".*?"',f'__version__ = "{version}"',init.read_text(encoding='utf-8')),encoding='utf-8')
for name in ('manifest.json','package.json','package-lock.json'):
    file=ROOT/'extension'/name
    data=json.loads(file.read_text(encoding='utf-8'))
    data['version']=version
    if name=='package-lock.json': data['packages']['']['version']=version
    file.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print(version)
