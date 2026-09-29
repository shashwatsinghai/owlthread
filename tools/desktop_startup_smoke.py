"""Source or packaged GUI/tray startup against an isolated database and real API.

This is not a visual interaction or global-shortcut certification.
"""
import json
import os
import ctypes
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from owlthread.db.database import Database
from owlthread.security import local_token
source_mode=len(sys.argv)>1 and sys.argv[1]=='--source'
command=[sys.executable,'-m','owlthread'] if source_mode else [str(Path(sys.argv[1]).resolve())]
def desktop_window_visible() -> bool:
    if os.name!='nt':
        return False
    user32=ctypes.windll.user32
    found=[]
    callback_type=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    def inspect(hwnd,unused):
        if user32.IsWindowVisible(hwnd):
            title=ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd,title,len(title))
            if title.value=='OwlThread — State your task, get context.':
                found.append(hwnd)
        return True
    user32.EnumWindows(callback_type(inspect),0)
    return bool(found)
checks=[]
for mode in (('app','start') if source_mode else ('app','start','default')):
    with tempfile.TemporaryDirectory(prefix='owlthread-desktop-startup-') as temp:
        database=Path(temp)/'memory.db'
        with Database(str(database)) as db:
            db.set_setting('llm_provider','fallback')
            token=local_token(db)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        started=time.monotonic()
        if mode=='default':
            env=os.environ.copy()
            env.update(OWLTHREAD_DB_PATH=str(database),OWLTHREAD_PORT=str(port))
            process=subprocess.Popen(command,env=env)
        else:
            process=subprocess.Popen([*command,'--db-path',str(database),mode,'--port',str(port)])
        try:
            deadline=time.monotonic()+20
            status=None
            while time.monotonic()<deadline:
                assert process.poll() is None,'Desktop exited before API startup'
                try:
                    request=urllib.request.Request(f'http://127.0.0.1:{port}/status',headers={'Authorization':'Bearer '+token})
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=1) as response:status=json.load(response)
                    break
                except OSError:time.sleep(.1)
            assert status and status['engine_running'] and status['http_listener']['running']
            assert not status['clipboard_watcher'] and not status['connectors'],'Fresh startup must not monitor private sources'
            time.sleep(.3)
            assert process.poll() is None
            visible=desktop_window_visible() if os.name=='nt' else None
            if mode in ('app','default') and os.name=='nt':
                assert visible,'Desktop process started but no visible window appeared'
            checks.append({'mode':mode,'passed':True,'startup_seconds':round(time.monotonic()-started,2),
                           'authenticated_api':True,'capture_sources_off':True,'visible_window':visible})
        finally:
            process.terminate();process.wait(timeout=10)
            # Windows may release the SQLite WAL handle just after process exit.
            time.sleep(.3)
print(json.dumps({'suite':'desktop-process-startup','source':source_mode,'checks':checks,
                  'visual_interaction':False,'shortcut_tested':False}))
