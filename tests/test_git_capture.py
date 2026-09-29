"""Temporary real Git repositories: opt-in, exclusion, project and duplicate boundaries."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from owlthread.capture.git_capture import capture_git
from owlthread.db.database import Database

class GitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'project';self.root.mkdir()
        self.db=Database(str(Path(self.tmp.name)/'data.db'))
        self.git('init','-q')
        for name,text in {'app.py':'old = 1\n','.env':'TOKEN=private\n','ignored.txt':'private\n','.gitignore':'ignored.txt\n','custom.txt':'old\n'}.items():
            (self.root/name).write_text(text)
        self.git('add','-f','app.py','.env','ignored.txt','.gitignore','custom.txt')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Create fixture')
    def git(self,*args):
        return subprocess.run(['git','-C',str(self.root),*args],check=True,capture_output=True)
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def test_explicit_opt_in_and_dedup(self):
        with self.assertRaises(ValueError): capture_git(self.db,str(self.root))
        result=capture_git(self.db,str(self.root),enable=True)
        self.assertEqual(result['stage'],'buffered')
        self.assertEqual(capture_git(self.db,str(self.root))['stage'],'duplicate')
        self.assertEqual(self.db.pending_count(),1)
    def test_selected_diff_excludes_ignored_sensitive_and_custom_paths(self):
        for name in ('app.py','.env','ignored.txt','custom.txt'): (self.root/name).write_text('new = 2\n')
        result=capture_git(self.db,str(self.root),['app.py','.env','ignored.txt','custom.txt'],True,['custom.txt'])
        self.assertEqual(result['skipped_files'],['.env','ignored.txt','custom.txt'])
        text=self.db.execute_read('SELECT raw_text FROM capture_buffer')[0]['raw_text']
        self.assertIn('+new = 2',text)
        self.assertNotIn('diff --git a/.env',text)
    def test_paths_cannot_escape_or_expand_to_all_files(self):
        for name in ('../outside','C:/outside','-x'):
            with self.assertRaises(ValueError):capture_git(self.db,str(self.root),[name],True)
        result=capture_git(self.db,str(self.root),['*','.'],True)
        self.assertEqual(result['skipped_files'],['*','.'])
    def test_large_diff_skipped(self):
        (self.root/'app.py').write_text('x'*65537)
        self.assertEqual(capture_git(self.db,str(self.root),['app.py'],True)['skipped_files'],['app.py'])
    def test_disable_prevents_later_capture(self):
        capture_git(self.db,str(self.root),enable=True)
        self.assertEqual(capture_git(self.db,str(self.root),disable=True)['stage'],'disabled')
        with self.assertRaises(ValueError):capture_git(self.db,str(self.root))
        self.assertEqual(self.db.pending_count(),1)
