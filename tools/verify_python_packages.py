"""Fresh wheel install outside the checkout and wheel rebuild from extracted sdist."""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
from pathlib import Path
root=Path(__file__).resolve().parent.parent
version=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
release=root/'artifacts/release'/version
with tempfile.TemporaryDirectory(prefix='owlthread-python-install-') as temp:
    target=Path(temp)
    environment=target/'venv'
    venv.EnvBuilder(with_pip=True).create(environment)
    python=environment/'Scripts/python.exe'
    env=os.environ.copy();env.pop('PYTHONPATH',None);env['OWLTHREAD_LLM_PROVIDER']='fallback'
    def run(*args):
        result=subprocess.run([str(python),*args],cwd=temp,env=env,text=True,capture_output=True,timeout=180)
        if result.returncode:
            raise RuntimeError(f"Fresh Python check failed: {args}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
        return result
    run('-m','pip','install','-r',str(root/'requirements-windows.lock'),str(release/f'owlthread-{version}-py3-none-any.whl'))
    result=run('-c',"import owlthread; from pathlib import Path; import sys; assert Path(owlthread.__file__).is_relative_to(Path(sys.prefix)); print(owlthread.__version__)")
    assert result.stdout.strip()==version
    assert run('-m','owlthread','--version').stdout.strip()=='OwlThread '+version
    run('-m','pip','check')
    run('-m','owlthread','--db-path',str(target/'fresh.db'),'test-capture','Decision: Keep installation independent of the source checkout.')
    result=run('-m','owlthread','--db-path',str(target/'fresh.db'),'done')
    assert json.loads(result.stdout)['total_extracted']==1
    with tarfile.open(release/f'owlthread-{version}.tar.gz') as archive:
        archive.extractall(target/'source',filter='data')
    source=target/'source'/f'owlthread-{version}'
    for name in ('extension/policy.js','extension/companion.js','extension/assets/owl-cozy-developer.png','extension/prompts/memory-filter.txt','tools/record_build.py'):
        assert (source/name).is_file(),name
    run('-m','build','--wheel','--no-isolation','--outdir',str(target/'rebuilt'),str(source))
    assert (target/'rebuilt'/f'owlthread-{version}-py3-none-any.whl').is_file()
print(json.dumps({'suite':'fresh-python-packages','checks':11,'passed':True,'isolated_import':True,'sdist_rebuild':True}))
