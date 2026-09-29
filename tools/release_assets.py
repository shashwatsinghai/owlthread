"""Resolve the shipped extension dependency graph; fail on missing local assets."""
import json
import re
from pathlib import Path

def extension_files(root: Path) -> list[Path]:
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    queue=['manifest.json',manifest['background']['service_worker'],manifest['action']['default_popup'],'help.html']
    queue.extend(manifest['icons'].values())
    for group in manifest['content_scripts']: queue.extend(group['js']);queue.extend(group.get('css',[]))
    for group in manifest['web_accessible_resources']: queue.extend(group['resources'])
    queue.extend(p.relative_to(root).as_posix() for p in (root/'prompts').glob('*') if p.is_file())
    seen=set()
    while queue:
        name=queue.pop()
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file(): raise ValueError('Missing or unsafe extension asset: '+name)
        name=path.relative_to(root.resolve()).as_posix()
        if name in seen: continue
        seen.add(name)
        if path.suffix in {'.html','.css','.js'}:
            text=path.read_text(encoding='utf-8')
            relative=re.findall(r'(?:src|href)=["\']([^"\']+)["\']',text) if path.suffix=='.html' else []
            relative+=re.findall(r'url\(["\']?([^\)"\']+)',text) if path.suffix=='.css' else []
            for value in relative:
                if not re.match(r'^(?:[a-z]+:|#|//)',value): queue.append((Path(name).parent/value.split('?')[0]).as_posix())
            for value in re.findall(r'(?:getURL|importScripts)\(["\']([^"\']+)["\']\)',text): queue.append(value)
    return [root/name for name in sorted(seen)]

if __name__=='__main__':
    root=Path(__file__).resolve().parent.parent/'extension'
    print('\n'.join(path.relative_to(root).as_posix() for path in extension_files(root)))
