"""HTTP-level checks of the host endpoints (needs fastapi + httpx, which only the Pi's venv has: skipped otherwise)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from fastapi.testclient import TestClient
    import mcpi
except ImportError:                       # pragma: no cover
    TestClient = None

LAN = ("10.1.0.29", 50000)                # dummy addresses (RFC 1918 style); the real ones live in mc-pi.env


@unittest.skipIf(TestClient is None, "fastapi / httpx not installed")
class HostHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state = mcpi.STATE
        mcpi.STATE = Path(self.tmp.name)
        cfg = dict(mcpi.DEFAULTS, PC_TOKEN="pc-secret-token", HOST_ALLOW_NETS="10.1.0.0/24,10.2.0.0/24",
                   HOST_LAPTOP_MAC="02-00-00-AA-BB-CC", HOST_LAPTOP_BCAST="10.1.0.255")
        self.state = mcpi.AppState(cfg)
        self.state.pcw_status = lambda fresh=False: {}
        self.state.hosts.sender = lambda *a: None
        self.app = mcpi.make_app(self.state)
        self.host_tok = self.state.hosts.add_token("laptop")
        self.app_tok = self.state.add_token("test phone")

    def tearDown(self):
        mcpi.STATE = self.old_state
        self.tmp.cleanup()

    def client(self, addr=LAN):
        return TestClient(self.app, client=addr)

    def hdr(self, tok):
        return {"Authorization": "Bearer " + tok}

    def post_report(self, tok=None, addr=LAN, body=None):
        return self.client(addr).post("/api/host/report", content=json.dumps(body or {"next_in_s": 15, "power": {"mains": True, "battery_pct": 80}}),
                                      headers=self.hdr(tok or self.host_tok))

    def test_report_shows_up_in_home(self):
        r = self.post_report()
        self.assertEqual(r.status_code, 200, r.text)
        home = self.client().get("/api/home", headers=self.hdr(self.app_tok)).json()
        self.assertEqual(home["hosts"]["laptop"]["state"], "online")
        self.assertEqual(home["hosts"]["laptop"]["power"]["battery_pct"], 80)
        self.assertIn("pc", home)                            # the old key is unchanged

    def test_home_without_a_host_token_has_no_tile(self):
        self.state.hosts.revoke("laptop")
        home = self.client().get("/api/home", headers=self.hdr(self.app_tok)).json()
        self.assertEqual(home["hosts"], {})

    def test_loopback_and_outside_refused_in_range_accepted(self):
        self.assertEqual(self.post_report(addr=("127.0.0.1", 1)).status_code, 403)
        self.assertEqual(self.post_report(addr=("203.0.113.9", 1)).status_code, 403)
        self.assertEqual(self.post_report(addr=("10.2.0.77", 1)).status_code, 200)

    def test_tokens_are_not_interchangeable(self):
        self.assertEqual(self.post_report(tok="pc-secret-token").status_code, 401)           # PC_TOKEN on /api/host/report
        self.assertEqual(self.post_report(tok=self.app_tok).status_code, 401)                # an app token too
        c = self.client()
        self.assertEqual(c.get("/api/pc/command", headers=self.hdr(self.host_tok)).status_code, 401)   # laptop token on /api/pc/*
        self.assertEqual(c.post("/api/pc/report", json={}, headers=self.hdr(self.host_tok)).status_code, 401)
        self.assertEqual(c.get("/api/home", headers=self.hdr(self.host_tok)).status_code, 401)
        self.assertEqual(c.post("/api/host/report", content="{}").status_code, 401)

    def test_oversize_bad_json_and_rate_limit(self):
        c, h = self.client(), self.hdr(self.host_tok)
        self.assertEqual(c.post("/api/host/report", content=b"x" * 9000, headers=h).status_code, 413)
        self.assertEqual(c.post("/api/host/report", content=b"{", headers=h).status_code, 400)
        self.assertEqual(c.post("/api/host/report", content=b"{}", headers=h).status_code, 200)
        self.assertEqual(c.post("/api/host/report", content=b"{}", headers=h).status_code, 429)

    def test_revoke_gives_401_at_once(self):
        self.assertEqual(self.post_report().status_code, 200)
        self.state.hosts.revoke("laptop")
        self.assertEqual(self.post_report().status_code, 401)

    def test_event_endpoint(self):
        r = self.client().post("/api/host/event", content=json.dumps({"kind": "disk", "title": "Disk"}), headers=self.hdr(self.host_tok))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client(("127.0.0.1", 1)).post("/api/host/event", content="{}", headers=self.hdr(self.host_tok)).status_code, 403)

    def test_app_endpoints_need_the_app_token(self):
        c = self.client()
        self.assertEqual(c.post("/api/hosts/laptop/wake", headers=self.hdr(self.host_tok)).status_code, 401)
        self.assertEqual(c.post("/api/hosts/laptop/wake").status_code, 401)
        self.assertEqual(c.post("/api/hosts/laptop/mode", json={"mode": "own"}, headers=self.hdr(self.host_tok)).status_code, 401)

    def test_wake_and_action_status_codes(self):
        c, h = self.client(), self.hdr(self.app_tok)
        self.assertEqual(c.post("/api/hosts/laptop/wake", headers=h).status_code, 200)
        self.assertEqual(c.post("/api/hosts/laptop/wake", headers=h).status_code, 429)       # cooldown
        self.assertEqual(c.post("/api/hosts/laptop/mode", json={"mode": "gaming"}, headers=h).status_code, 400)
        self.assertEqual(c.post("/api/hosts/laptop/open", json={"app": "x"}, headers=h).status_code, 400)
        self.assertEqual(c.post("/api/hosts/laptop/format", json={}, headers=h).status_code, 400)
        self.assertEqual(c.post("/api/hosts/laptop/mode", json={"mode": "own"}, headers=h).status_code, 409)   # PC does not advertise it


if __name__ == "__main__":
    unittest.main()
