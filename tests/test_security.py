"""Real loopback adversarial requests; no live user data or provider calls."""
import http.client
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from owlthread.capture.server import LocalHttpListener, CaptureHTTPServer
from owlthread.db.database import Database
from owlthread.security import local_token

ORIGIN = "chrome-extension://" + "a" * 32


class LocalAPISecurity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name)/"security.db"))
        self.db.set_setting("llm_provider", "fallback")
        self.listener = LocalHttpListener(self.db,port=0)
        self.listener.start()
        self.token = local_token(self.db)

    def tearDown(self):
        self.listener.stop()
        self.db.close()
        self.tmp.cleanup()

    def call(self,path="/entries",method="GET",payload=None,token=True,origin=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.listener.port,timeout=3)
        opts={"Content-Type":"application/json"}
        if token: opts["Authorization"]="Bearer "+self.token
        if origin is not None: opts["Origin"]=origin
        opts.update(headers or {})
        conn.request(method,path,body=json.dumps(payload) if payload is not None else None,headers=opts)
        response=conn.getresponse()
        result=(response.status,dict(response.getheaders()),json.loads(response.read()))
        conn.close()
        return result

    def test_health_is_minimal(self):
        status,_,data=self.call("/health",token=False)
        self.assertEqual(status,200)
        self.assertEqual(data,{"app":"OwlThread","status":"healthy"})

    def test_all_sensitive_routes_require_credentials(self):
        for path,method in [(p,"GET") for p in ("/entries","/projects","/status","/primer")]+[(p,"POST") for p in ("/capture","/capture-smart","/context","/flush","/primer","/pair")]:
            with self.subTest(path=path,method=method):
                self.assertEqual(self.call(path,method,{},token=False)[0],401)

    def test_invalid_token(self):
        self.assertEqual(self.call(headers={"Authorization":"Bearer wrong"})[0],401)

    def test_websites_rejected_even_with_token(self):
        for origin in ("https://evil.example","null","http://localhost","chrome-extension://bad",ORIGIN+".evil"):
            with self.subTest(origin=origin):
                status,headers,_=self.call(origin=origin)
                self.assertEqual(status,403)
                self.assertNotIn("Access-Control-Allow-Origin",headers)

    def test_extension_must_pair_then_can_capture(self):
        self.assertEqual(self.call(origin=ORIGIN)[0],403)
        self.assertEqual(self.call("/pair","POST",{},origin=ORIGIN)[0],200)
        status,headers,_=self.call("/capture","POST",{"text":"Decision: use SQLite WAL","project":"Browser"},origin=ORIGIN)
        self.assertEqual(status,200)
        self.assertEqual(headers["Access-Control-Allow-Origin"],ORIGIN)
        self.assertNotIn("Access-Control-Allow-Private-Network",headers)
        self.assertEqual(self.db.pending_count(),1)

    def test_preflight_does_not_authorize_reads(self):
        self.assertEqual(self.call("/pair","OPTIONS",token=False,origin=ORIGIN,headers={"Access-Control-Request-Method":"POST","Access-Control-Request-Headers":"authorization, content-type"})[0],200)
        self.assertEqual(self.call("/entries",origin=ORIGIN,token=False)[0],403)

    def test_revoke_invalidates_token_and_origin(self):
        self.call("/pair","POST",{},origin=ORIGIN)
        new=local_token(self.db,rotate=True)
        self.assertNotEqual(new,self.token)
        self.assertEqual(self.call()[0],401)
        self.assertEqual(self.call(origin=ORIGIN)[0],403)

    def test_host_header_attacks(self):
        for host in ("evil.com","127.0.0.1.evil:41789","localhost:wrong","127.0.0.1:1","localhost@evil.com"):
            with self.subTest(host=host): self.assertEqual(self.call(headers={"Host":host})[0],403)

    def test_loopback_only(self):
        with self.assertRaises(ValueError): CaptureHTTPServer(("0.0.0.0",0),self.db)

    def test_invalid_payload_boundaries(self):
        for payload in ([],{"text":True},{"text":"a","project":{}},{"text":"a","project_id":True},
                        {"text":"a","project":"x"*101},{"text":"a","project_id":999},
                        {"text":"a","url":"https://name:SECRET@example.com"},{"text":"a","title":[]},
                        {"text":"a","dedup_key":"bad key"},{"text":"a"*200001}):
            with self.subTest(payload_type=type(payload).__name__):
                status,_,body=self.call("/capture","POST",payload)
                self.assertEqual(status,400)
                self.assertNotIn("SECRET",json.dumps(body))
        self.assertEqual(self.db.pending_count(),0)

    def test_content_type_and_length(self):
        self.assertEqual(self.call("/capture","POST",{"text":"note"},headers={"Content-Type":"text/plain"})[0],400)
        self.assertEqual(self.call("/capture","POST",{"text":"note"},headers={"Content-Length":"1048577"})[0],400)

    def test_project_scoped_dedup_and_conflicts(self):
        payload={"text":"Decision: use local SQLite","dedup_key":"one","project":"A"}
        for _ in range(2): self.assertEqual(self.call("/capture","POST",payload)[0],200)
        self.assertEqual(self.call("/capture","POST",{**payload,"project":"B"})[0],200)
        self.assertEqual(self.db.pending_count(),2)
        self.assertEqual(self.call("/capture","POST",{**payload,"text":"Different"})[0],400)
        for project in self.db.list_projects():
            if project["name"] in {"A","B"}:
                self.assertEqual(self.call("/capture","POST",{**payload,"project_id":project["id"],"project":"other"})[0],400)

    def test_entries_project_filter(self):
        for name in ("A","B"):
            pid=self.db.get_or_create_project(name)
            self.db.insert_entry(name+" private fact",project_id=pid)
        rows=self.call("/entries?project=A")[2]["entries"]
        self.assertEqual([r["raw_text"] for r in rows],["A private fact"])

    def test_rate_limit(self):
        self.listener._server.rate_limit=2
        self.assertEqual(self.call()[0],200)
        self.assertEqual(self.call()[0],200)
        self.assertEqual(self.call()[0],429)

    def test_windows_secrets_protected_at_rest(self):
        import sys
        self.db.set_setting("llm_api_key","test-secret")
        raw=self.db.execute_read("SELECT value FROM settings WHERE key='llm_api_key'")[0]["value"]
        if sys.platform=="win32":
            self.assertTrue(raw.startswith("dpapi:"))
            self.assertNotIn("test-secret",raw)
        self.assertEqual(self.db.get_setting("llm_api_key"),"test-secret")
        self.assertNotIn(self.token,json.dumps(self.call("/status")[2]))

    def test_existing_settings_timestamp_constraint_allows_startup_and_pairing(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"existing.db"
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
                conn.execute("INSERT INTO settings VALUES ('llm_provider','fallback','2025-01-01T00:00:00+00:00')")
                conn.execute("INSERT INTO settings VALUES ('llm_api_key','dpapi:invalid','2025-01-01T00:00:00+00:00')")
                conn.execute("INSERT INTO settings VALUES ('local_api_token','dpapi:invalid','2025-01-01T00:00:00+00:00')")
                conn.execute("INSERT INTO settings VALUES ('authorized_origins',?,'2025-01-01T00:00:00+00:00')",
                             (json.dumps([ORIGIN]),))
                conn.commit()
            with Database(str(path)) as db:
                token=local_token(db)
                self.assertTrue(db.execute_read("SELECT updated_at FROM settings WHERE key='local_api_token'")[0]["updated_at"])
                self.assertEqual(db.execute_read("SELECT COUNT(*) AS n FROM settings WHERE key='authorized_origins'")[0]["n"],0)
                self.assertEqual(db.get_all_settings()["llm_api_key"],"")
                self.assertIn("llm_api_key",db.unavailable_secret_settings)
                self.assertEqual(db.execute_read("SELECT value FROM settings WHERE key='llm_api_key'")[0]["value"],"dpapi:invalid")
                listener=LocalHttpListener(db,port=0)
                listener.start()
                try:
                    for _ in range(2):
                        connection=http.client.HTTPConnection("127.0.0.1",listener.port,timeout=3)
                        connection.request("POST","/pair",body="{}",headers={
                            "Content-Type":"application/json","Authorization":"Bearer "+token,"Origin":ORIGIN})
                        response=connection.getresponse()
                        body=response.read()
                        self.assertEqual(response.status,200,body)
                        connection.close()
                    self.assertTrue(db.execute_read("SELECT updated_at FROM settings WHERE key='authorized_origins'")[0]["updated_at"])
                    self.assertNotEqual(local_token(db,rotate=True),token)
                    self.assertEqual(db.get_setting("llm_provider"),"fallback")
                    db.set_setting("llm_api_key","replacement")
                    self.assertEqual(db.get_setting("llm_api_key"),"replacement")
                    self.assertNotIn("llm_api_key",db.unavailable_secret_settings)
                finally:
                    listener.stop()
