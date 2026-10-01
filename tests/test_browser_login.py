"""Browser handoff, PKCE callback, cancellation and bounded context reads."""
import hashlib
import base64
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlencode
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from owlthread.db.database import Database
from owlthread.integrations.browser_login import BrowserLoginService, LoginSession, CloudflareMcpTransport, LoginHttp, CF_ORIGIN, CREDENTIAL_PREFIX, AUTH_PREFIX, refresh_cloudflare, refresh_browser_credential
from owlthread.integrations.context import ProviderError, ContextConnectorService, SUPPORTED_SCOPES, JsonResponse


class CloudflareFixture:
    def __init__(self): self.calls=[];self.authorization={};self.bad_state_rejected=False
    def request(self,url,**kwargs):
        self.calls.append((url,kwargs))
        body=kwargs.get("data",{})
        if url.endswith("/register"):
            assert body["token_endpoint_auth_method"]=="none"
            return {"client_id":"owlthread-fixture-public-client"},{}
        if url.endswith("/token"):
            if body["grant_type"]=="authorization_code":
                challenge=base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"].encode()).digest()).decode().rstrip("=")
                assert self.authorization["code_challenge"]==[challenge]
                assert body["code"]=="fixture-code"
            return {"access_token":"fixture-access-secret","refresh_token":"fixture-refresh-secret","expires_in":3600},{}
        if body.get("method")=="initialize": return {"result":{"protocolVersion":"2025-06-18"}},{}
        if body.get("method")=="notifications/initialized": return {},{}
        assert body["method"]=="tools/call" and body["params"]["name"]=="execute"
        code=body["params"]["arguments"]["code"]
        assert 'method: "GET"' in code
        if 'path: "/accounts?' in code: rows=[{"id":"a"*32,"name":"Fixture account"}]
        elif 'path: "/zones?' in code: rows=[]
        elif "/workers/scripts" in code: rows=[{"id":"fixture-access-secret worker"}]
        else: rows=[]
        return {"result":{"content":[{"type":"text","text":json.dumps({"success":True,"result":rows})}]}},{}

    def open_browser(self,url):
        self.authorization=parse_qs(urlsplit(url).query)
        redirect=self.authorization["redirect_uri"][0]
        def callback():
            try:
                with urlopen(redirect+"?state=incorrect&code=stolen",timeout=3): pass
            except HTTPError as error:
                self.bad_state_rejected=error.code==400;error.close()
            with urlopen(redirect+"?"+urlencode({"state":self.authorization["state"][0],"code":"fixture-code","iss":CF_ORIGIN}),timeout=3) as response:
                assert "fixture-code" not in response.read().decode()
        threading.Thread(target=callback,daemon=True).start()
        return True


class BrowserLoginTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.db=Database(str(Path(self.directory.name)/"login.db"))
        self.project=self.db.get_or_create_project("Login target")
        self.http=CloudflareFixture()
        self.service=BrowserLoginService(self.db,http=self.http,browser=self.http.open_browser)

    def tearDown(self):
        self.service.close()
        for session in self.service.sessions.values():
            if session.thread: session.thread.join(2)
        self.db.close();self.directory.cleanup()

    def complete(self):
        result=self.service.begin("cloudflare",self.project)
        session=self.service.sessions[result["id"]]
        session.thread.join(5)
        self.assertFalse(session.thread.is_alive())
        self.assertEqual(session.state,"signed_in",session.message)
        return session

    def test_browser_login_pkce_rejects_wrong_state_and_keeps_tokens_private(self):
        session=self.complete()
        self.assertTrue(self.http.bad_state_rejected)
        self.assertEqual(session.project_id,self.project)
        public=json.dumps(self.service.status("cloudflare"))+json.dumps(self.db.get_all_settings())
        self.assertNotIn("fixture-access-secret",public)
        self.assertNotIn("fixture-refresh-secret",public)
        rows=self.db.execute_read("SELECT value FROM settings WHERE key=?",(CREDENTIAL_PREFIX+"cloudflare",))
        self.assertTrue(rows[0]["value"].startswith("dpapi:"))
        self.assertFalse(ContextConnectorService(self.db).status("cloudflare")["connected"])

    def test_discovered_account_imports_to_original_project_and_redacts_oauth_tokens(self):
        self.complete()
        self.db.set_setting("active_project","Somewhere else")
        with patch("owlthread.integrations.browser_login.CloudflareMcpTransport",lambda:CloudflareMcpTransport(self.http)):
            result=self.service.select("cloudflare","a"*32)
        self.assertTrue(result["ok"])
        captures=self.db.execute_read("SELECT raw_text,project_id FROM capture_buffer")
        self.assertEqual(len(captures),1)
        self.assertEqual(captures[0]["project_id"],self.project)
        self.assertNotIn("fixture-access-secret",captures[0]["raw_text"])
        self.assertIn("[credential redacted]",captures[0]["raw_text"])

    def test_cancelled_browser_wait_cannot_store_late_credentials(self):
        opened=threading.Event()
        self.service.browser=lambda url:opened.set() or True
        started=self.service.begin("cloudflare",self.project)
        self.assertTrue(opened.wait(2))
        self.service.cancel("cloudflare")
        self.service.sessions[started["id"]].thread.join(2)
        self.assertEqual(self.service.status("cloudflare")["session"]["state"],"cancelled")
        self.assertFalse(self.db.get_setting(CREDENTIAL_PREFIX+"cloudflare"))

    def test_close_cancels_without_waiting_for_browser_login(self):
        opened=threading.Event();self.service.browser=lambda url:opened.set() or True
        self.service.begin("cloudflare",self.project);self.assertTrue(opened.wait(2))
        start=time.monotonic();self.service.close()
        self.assertLess(time.monotonic()-start,.1)
        self.assertFalse(self.db.get_setting(CREDENTIAL_PREFIX+"cloudflare"))

    def test_unknown_resources_do_not_enable_a_grant(self):
        self.complete()
        with self.assertRaises(ValueError): self.service.select("cloudflare","b"*32)
        self.assertFalse(ContextConnectorService(self.db).status("cloudflare")["enabled"])

    def test_existing_manual_token_path_remains_available(self):
        self.complete()
        ContextConnectorService(self.db).configure("cloudflare",options={"account_id":"b"*32},scopes=["workers.read"],project_id=self.project,token="manual-fixture-token")
        self.assertFalse(self.service.status("cloudflare")["signed_in"])
        self.assertEqual(self.db.get_setting(CREDENTIAL_PREFIX+"cloudflare"),"manual-fixture-token")

    def test_disconnect_forgets_browser_credentials_and_resources(self):
        self.complete();ContextConnectorService(self.db).disconnect("cloudflare")
        self.assertFalse(self.service.status("cloudflare")["signed_in"])
        self.assertEqual(self.service.status("cloudflare")["resources"],[])

    def test_refresh_updates_before_import_and_preserves_cancelled_connection(self):
        self.complete()
        bundle=json.loads(self.db.get_setting(CREDENTIAL_PREFIX+"cloudflare"));bundle["expires_at"]=0
        self.db.set_setting(CREDENTIAL_PREFIX+"cloudflare",json.dumps(bundle))
        refresh_cloudflare(self.db,self.http)
        self.assertGreater(json.loads(self.db.get_setting(CREDENTIAL_PREFIX+"cloudflare"))["expires_at"],time.time())

    def test_cloudflare_only_fixed_read_paths_are_executable(self):
        transport=CloudflareMcpTransport(self.http)
        for provider,path,query in [("github","/accounts",{}),("cloudflare","/accounts/"+"a"*32+"/tokens",{}),("cloudflare","/accounts",{"execute":"delete all"})]:
            with self.assertRaises(ProviderError): transport.get(provider,path,"{}",query)
        self.assertEqual(self.http.calls,[])

    def test_github_missing_client_registration_is_honest(self):
        with patch.dict("os.environ",{"OWLTHREAD_GITHUB_CLIENT_ID":""}), patch("owlthread.integrations.browser_login.GITHUB_CLIENT_ID", ""):
            with self.assertRaisesRegex(ValueError,"registered app"): self.service.begin("github",self.project)
            self.assertFalse(self.service.status("github")["browser_login_available"])

    def test_github_device_flow_uses_own_client_id_and_respects_poll_backoff(self):
        self.db.set_setting("github_oauth_client_id","owlthread-public-client")
        polls=[]; opened=[]; requests=[]
        class Cancel:
            def is_set(self): return False
            def wait(self,seconds): polls.append(seconds);return False
        class GitHubFixture:
            def request(inner,url,**kwargs):
                requests.append((url,kwargs))
                if url.endswith("/device/code"):
                    self.assertEqual(kwargs["data"],{"client_id":"owlthread-public-client","scope":"read:user"})
                    return {"device_code":"private-device-secret","user_code":"ABCD-1234","verification_uri":"https://github.com/login/device","interval":5},{}
                if url.endswith("/access_token"):
                    self.assertNotIn("client_secret",kwargs["data"])
                    if len(polls)==1: return {"error":"authorization_pending"},{}
                    if len(polls)==2: return {"error":"slow_down"},{}
                    return {"access_token":"github-fixture-secret"},{}
                if url.endswith("/user"): return {"login":"fixture-user"},{}
                return [{"full_name":"fixture/public","private":False},{"full_name":"fixture/private","private":True}],{}
        self.service.http=GitHubFixture();self.service.browser=lambda url:opened.append(url) or True
        session=LoginSession("github",self.project,list(SUPPORTED_SCOPES["github"]));session.cancelled=Cancel()
        credential,resources,name=self.service._github(session)
        self.assertEqual(polls,[5,5,10]);self.assertEqual(opened,["https://github.com/login/device"])
        self.assertEqual(json.loads(credential)["access_token"],"github-fixture-secret");self.assertEqual(name,"fixture-user")
        self.assertEqual([r["id"] for r in resources],["fixture/public"])
        self.assertNotIn("private-device-secret",json.dumps(session.public()))

    def test_github_denial_does_not_save_credentials(self):
        self.db.set_setting("github_oauth_client_id","owlthread-public-client")
        class Denied:
            def request(inner,url,**kwargs):
                if url.endswith("/device/code"): return {"device_code":"device-secret","user_code":"ABCD-1234","verification_uri":"https://github.com/login/device"},{}
                return {"error":"access_denied"},{}
        session=LoginSession("github",self.project,[])
        session.cancelled=type("Cancel",(),{"is_set":lambda _:False,"wait":lambda _,seconds:False})()
        self.service.http=Denied();self.service.browser=lambda url:True
        with self.assertRaises(ProviderError): self.service._github(session)
        self.assertFalse(self.db.get_setting(CREDENTIAL_PREFIX+"github"))

    def test_github_rotates_expiring_device_tokens_without_a_client_secret(self):
        original={"kind":"github_oauth","client_id":"own-public-client","access_token":"old-access","refresh_token":"old-refresh","expires_at":time.time()-1}
        self.db.set_setting(CREDENTIAL_PREFIX+"github",json.dumps(original))
        requests=[]
        class Renew:
            def request(inner,url,**kwargs):
                requests.append((url,kwargs))
                return {"access_token":"new-access","refresh_token":"new-refresh","expires_in":28800,"scope":"read:user"},{}
        refresh_browser_credential(self.db,"github",Renew())
        stored=json.loads(self.db.get_setting(CREDENTIAL_PREFIX+"github"))
        self.assertEqual(stored["access_token"],"new-access");self.assertEqual(stored["refresh_token"],"new-refresh")
        self.assertNotIn("client_secret",requests[0][1]["data"])
        refresh_browser_credential(self.db,"github",Renew())
        self.assertEqual(len(requests),1)

    def test_disconnect_during_github_renewal_cannot_restore_credentials(self):
        self.db.set_setting(CREDENTIAL_PREFIX+"github",json.dumps({"kind":"github_oauth","client_id":"own-public-client","access_token":"old","refresh_token":"refresh","expires_at":time.time()-1}))
        class Disconnect:
            def request(inner,url,**kwargs):
                ContextConnectorService(self.db).disconnect("github")
                return {"access_token":"new","expires_in":28800},{}
        with self.assertRaisesRegex(ProviderError,"changed"):
            refresh_browser_credential(self.db,"github",Disconnect())
        self.assertFalse(self.db.get_setting(CREDENTIAL_PREFIX+"github"))

    def test_github_oauth_import_uses_access_token_and_redacts_both_secrets(self):
        self.db.set_setting(CREDENTIAL_PREFIX+"github",json.dumps({"kind":"github_oauth","client_id":"public-client",
            "access_token":"access-fixture-secret","refresh_token":"refresh-fixture-secret","expires_at":time.time()+3600}))
        class Repository:
            def get(inner,provider,path,token,query=None):
                self.assertEqual(token,"access-fixture-secret")
                return JsonResponse({"id":1,"full_name":"fixture/public","private":False,
                                     "description":"access-fixture-secret refresh-fixture-secret"})
        service=ContextConnectorService(self.db,transport=Repository())
        service.configure("github",options={"repository":"fixture/public"},scopes=["repositories.read"],project_id=self.project)
        result=service.sync("github");self.assertTrue(result["ok"])
        raw=self.db.execute_read("SELECT raw_text FROM capture_buffer")[0]["raw_text"]
        self.assertNotIn("access-fixture-secret",raw);self.assertNotIn("refresh-fixture-secret",raw)
        self.assertEqual(raw.count("[credential redacted]"),2)

    def test_new_signin_after_selection_cannot_mix_credentials_and_projects(self):
        self.db.set_setting(CREDENTIAL_PREFIX+"github","old-access-secret")
        self.db.set_setting(AUTH_PREFIX+"github",json.dumps({"method":"browser","project_id":self.project,"scopes":["repositories.read"],
            "resources":[{"id":"old/repo","label":"old/repo","options":{"repository":"old/repo"}}]}))
        new_project=self.db.get_or_create_project("New identity's project")
        requests=[]
        class Repository:
            def get(inner,*args,**kwargs):
                requests.append(args);raise AssertionError("Stale selection must not reach the provider")
        real_service=ContextConnectorService(self.db,transport=Repository())
        def replace_login(db):
            self.service._github=lambda session:("new-access-secret",[{"id":"new/repo","label":"new/repo","options":{"repository":"new/repo"}}],"New identity")
            self.service._run(LoginSession("github",new_project,["repositories.read"]))
            real_service.configure("github",options={"repository":"new/repo"},scopes=["repositories.read"],project_id=new_project)
            return real_service
        with patch("owlthread.integrations.context.ContextConnectorService",replace_login):
            with self.assertRaisesRegex(PermissionError,"changed after selection"):
                self.service.select("github","old/repo")
        self.assertEqual(requests,[])
        self.assertEqual(len(self.db.execute_read("SELECT id FROM capture_buffer")),0)
        self.assertEqual(real_service.status("github")["project_id"],new_project)
        self.assertEqual(real_service.status("github")["options"]["repository"],"new/repo")

    def test_signin_cannot_open_unknown_hosts(self):
        for url in ["http://github.com/login/device","https://github.com.evil.example/login/device","https://github.com@evil.example/"]:
            with self.assertRaises(ProviderError): self.service._open(LoginSession("github",self.project,[]),url)

    def test_disabled_connection_during_renewal_cannot_read_or_import(self):
        requests=[]
        class Repository:
            def get(inner,*args,**kwargs):
                requests.append(args);raise AssertionError("Disabled connection must not reach the provider")
        service=ContextConnectorService(self.db,transport=Repository())
        setup={"options":{"repository":"fixture/public"},"scopes":["repositories.read"],"project_id":self.project}
        service.configure("github",token="fixture-token",**setup)
        def disable(db,provider):
            service.configure(provider,enabled=False,**setup)
        with patch("owlthread.integrations.browser_login.refresh_browser_credential",disable):
            with self.assertRaisesRegex(ValueError,"changed during sign-in renewal"):
                service.sync("github")
        self.assertEqual(requests,[])
        self.assertEqual(len(self.db.execute_read("SELECT id FROM capture_buffer")),0)
        self.assertFalse(service.status("github")["enabled"])

    def test_transport_rejects_credential_redirect_and_non_provider_origins(self):
        for url in ["https://evil.example/token","http://mcp.cloudflare.com/token","https://api.github.com@evil.example/user"]:
            with self.assertRaises(ProviderError): LoginHttp().request(url,token="private")


if __name__=="__main__": unittest.main()
