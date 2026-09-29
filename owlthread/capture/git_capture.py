"""Explicit, opt-in Git metadata and selected-diff capture. No background watcher."""
from __future__ import annotations
import fnmatch
import hashlib
import json
import subprocess
from pathlib import Path,PurePosixPath
from owlthread.db.database import Database
from owlthread.extraction.extractor import SECRET

DEFAULT_EXCLUDES=[".env*",".ssh",".aws",".git",".npmrc",".pypirc","*.pem","*.key","*credentials*","*secret*","*.p12","*.pfx","id_rsa*","id_ed25519*","*.db","*.sqlite*"]


def capture_git(db: Database,repo: str,files: list[str] | None = None,enable: bool = False,
                exclude: list[str] | None = None, disable: bool = False) -> dict:
    root=Path(repo).expanduser().resolve()
    def git(*args: str,check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git","-C",str(root),*args],capture_output=True,check=check,timeout=10)
    actual=Path(git("rev-parse","--show-toplevel").stdout.decode().strip()).resolve()
    if actual!=root: raise ValueError("Choose the Git repository root")
    pid=db.get_or_create_project(root.name,str(root))
    key=f"git_capture_enabled:{pid}"
    if enable and disable: raise ValueError("Choose enable or disable")
    if disable:
        db.set_setting(key,"false")
        return {"project_id":pid,"stage":"disabled","capture_id":None}
    if enable: db.set_setting(key,"true")
    if exclude is not None: db.set_setting(f"git_capture_excludes:{pid}",json.dumps(exclude))
    if db.get_setting(key,"false")!="true": raise ValueError("Git capture is off for this project; use --enable after reviewing the capture policy")
    exclusions=DEFAULT_EXCLUDES+json.loads(db.get_setting(f"git_capture_excludes:{pid}","[]"))
    paths=files or []
    if len(paths)>20: raise ValueError("Select at most 20 files")
    pieces=[];skipped=[]
    commit=git("log","-1","--format=%H%n%s").stdout.decode("utf-8",errors="replace")[:8000]
    branch=git("branch","--show-current").stdout.decode("utf-8",errors="replace").strip()
    if SECRET.search(commit): raise ValueError("Possible credentials in commit metadata; capture rejected")
    pieces.append(f"Git snapshot on branch {branch}:\n{commit}")
    for value in paths:
        name=value.replace("\\","/")
        path=PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or ":" in name or name.startswith("-"):
            raise ValueError("Diff paths must be relative paths inside the repository")
        if any(fnmatch.fnmatch(part.casefold(),pattern.casefold()) or fnmatch.fnmatch(name.casefold(),pattern.casefold()) for pattern in exclusions for part in path.parts):
            skipped.append(name);continue
        if git("check-ignore","--no-index","-q","--",name,check=False).returncode==0:
            skipped.append(name);continue
        tracked=git("ls-files","-z","--error-unmatch","--",name,check=False)
        if tracked.returncode or tracked.stdout.decode("utf-8",errors="replace") != name+"\0": skipped.append(name);continue
        file=root.joinpath(*path.parts)
        if file.is_symlink() or not file.resolve().is_relative_to(root) or (file.exists() and (not file.is_file() or file.stat().st_size>65536)):
            skipped.append(name);continue
        old_size=git("cat-file","-s","HEAD:"+name,check=False)
        if not old_size.returncode and int(old_size.stdout)>65536: skipped.append(name);continue
        diff=git("diff","--no-ext-diff","--no-textconv","HEAD","--",name).stdout
        if len(diff)>65536 or b"\x00" in diff or b"Binary files" in diff:
            skipped.append(name);continue
        text=diff.decode("utf-8",errors="replace")
        if SECRET.search(text): skipped.append(name);continue
        if text: pieces.append(text)
    text="\n".join(pieces)
    if len(text)>200000: raise ValueError("Selected snapshot exceeds 200,000 characters")
    cid=db.insert_capture(text,"git_manual",pid,{"branch":branch,"selected_files":paths,"skipped_files":skipped},
                          dedup_key=hashlib.sha256(text.encode()).hexdigest())
    return {"capture_id":cid,"project_id":pid,"skipped_files":skipped,"stage":"buffered" if cid else "duplicate"}
