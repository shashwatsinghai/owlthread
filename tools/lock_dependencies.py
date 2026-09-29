"""Pin only the transitive runtime/build dependency closure present in this environment."""
from importlib import metadata
from pathlib import Path
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
root=Path(__file__).resolve().parent.parent
config=tomllib.loads((root/'pyproject.toml').read_text())
queue=[Requirement(value) for value in config['project']['dependencies']+config['project']['optional-dependencies']['build']+config['build-system']['requires']]
seen=set();versions={}
while queue:
    requirement=queue.pop()
    if requirement.marker and not requirement.marker.evaluate(): continue
    key=(canonicalize_name(requirement.name),tuple(sorted(requirement.extras)))
    if key in seen: continue
    seen.add(key)
    dist=metadata.distribution(requirement.name)
    versions[key[0]]=dist.version
    for text in dist.requires or []:
        child=Requirement(text)
        if child.marker is None or any(child.marker.evaluate({'extra':extra}) for extra in requirement.extras or {''}):
            child.marker=None
            queue.append(child)
(root/'requirements-windows.lock').write_text('# Windows Python 3.14 runtime + build closure; see pyproject.toml for supported ranges.\n'+'\n'.join(f'{name}=={version}' for name,version in sorted(versions.items()))+'\n')
print(f'Pinned {len(versions)} packages.')
