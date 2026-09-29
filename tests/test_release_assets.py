import json
import sys
import tomllib
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tools'))
from release_assets import extension_files
from owlthread import __version__

class ReleaseAssetsTests(unittest.TestCase):
    def test_all_declared_and_nested_assets_exist(self):
        paths={p.relative_to(ROOT/'extension').as_posix() for p in extension_files(ROOT/'extension')}
        self.assertTrue({'policy.js','content.js','companion.js','background.js','popup/popup.js','assets/owl-cozy-developer.png'} <= paths)
        self.assertTrue(any(p.startswith('prompts/') for p in paths))
    def test_version_mirrors_match(self):
        version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
        self.assertEqual(version,__version__)
        for name in ('manifest.json','package.json','package-lock.json'):
            self.assertEqual(version,json.loads((ROOT/'extension'/name).read_text())['version'])
