import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_hub as hh

# Dummy values only (RFC 5737 / 10.x / a made-up MAC): the repo is public.
CFG = {"HOST_ALLOW_NETS": "10.1.0.0/24, 10.2.0.0/24", "HOST_LAPTOP_MAC": "02-00-00-AA-BB-CC",
       "HOST_LAPTOP_BCAST": "10.1.0.255", "HOST_LAPTOP_SOURCE_IP": "10.1.0.4", "HOST_LAPTOP_IP": "10.1.0.9"}


class Clock:
    t = 100000.0
    def __call__(self): return self.t


class Claude:
    def __init__(self): self.items, self.verified, self.bad = [], [], False
    def enqueue(self, x): self.items.append(x)
    def verify(self, th, msg, sig, ts, tier="H"):
        if self.bad or (tier != "0" and sig != "good"):
            raise PermissionError("bad signature")
        self.verified.append((msg, tier))


def report(**k):
    d = {"v": 1, "next_in_s": 15, "power": {"mains": True, "battery_pct": 100},
         "net": {"type": "ethernet", "speed_mbps": 1000, "name": "Ethernet"},
         "apollo": {"service": True, "web": True, "stream_active": False}, "moonlight_running": True,
         "backup": {"status": "ok", "last_ok": 1763500000, "detail": ""}, "uptime_s": 5000}
    d.update(k)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock, self.claude = Clock(), Claude()
        self.clock.t = 100000.0
        self.sent, self.msgs, self.logs = [], [], []
        self.helper = True
        self.settings = {"muted": False, "kinds": {"host": True}}
        self.probe_result = False
        self.h = self.make()
        self.tok = self.h.add_token("laptop")

    def make(self, cfg=None):
        return hh.HostHub(self.load, self.save, self.msgs.append, self.claude, cfg or CFG, lambda: self.helper,
                          lambda: self.settings, lambda: False, lambda *a: self.logs.append(a), clock=self.clock,
                          sender=lambda *a: self.sent.append(a), probe=lambda ip: self.probe_result)

    def load(self, name, default):
        try:
            return json.loads((self.dir / name).read_text())
        except (OSError, ValueError):
            return default

    def save(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj))

    def tearDown(self):
        self.tmp.cleanup()

    def rep(self, **k):
        self.clock.t += 6
        self.h.on_report("laptop", report(**k))

    def kinds(self):
        return [m["kind"] for m in self.msgs]


class Registry(Base):
    def test_token_hash_only_and_lookup(self):
        raw = (self.dir / "hosts.json").read_text()
        self.assertNotIn(self.tok, raw)
        self.assertEqual(self.h.host_for_token(self.tok), "laptop")
        self.assertIsNone(self.h.host_for_token("nope"))
        self.assertIsNone(self.h.host_for_token(""))

    def test_new_token_replaces_old_and_revoke_applies_at_once(self):
        new = self.h.add_token("laptop")
        self.assertIsNone(self.h.host_for_token(self.tok))
        self.assertEqual(self.h.host_for_token(new), "laptop")
        other = self.make()                      # a second process (the CLI) revokes; no restart needed
        self.assertTrue(other.revoke("laptop"))
        self.assertIsNone(self.h.host_for_token(new))
        self.assertFalse(other.revoke("laptop"))

    def test_token_from_a_cli_add_is_seen_without_restart(self):
        tok2 = self.make().add_token("second")
        self.assertEqual(self.h.host_for_token(tok2), "second")

    def test_network_allow_list(self):
        h = self.h
        self.assertTrue(h.net_ok("10.1.0.29"))
        self.assertTrue(h.net_ok("10.2.0.5"))
        self.assertFalse(h.net_ok("127.0.0.1"))
        self.assertFalse(h.net_ok("::1"))
        self.assertFalse(h.net_ok("::ffff:127.0.0.1"))
        self.assertFalse(h.net_ok("203.0.113.7"))
        self.assertFalse(h.net_ok("10.3.0.1"))
        self.assertFalse(h.net_ok("not an ip"))
        self.assertFalse(h.net_ok(""))
        self.assertTrue(h.net_ok("::ffff:10.1.0.7"))

    def test_empty_allow_list_refuses_everyone(self):
        h = self.make({"HOST_ALLOW_NETS": ""})
        self.assertFalse(h.net_ok("10.1.0.29"))
        self.assertFalse(h.net_ok("127.0.0.1"))
        self.assertFalse(self.make({"HOST_ALLOW_NETS": "garbage,"}).net_ok("10.1.0.29"))
        h2 = self.make({"HOST_ALLOW_NETS": "0.0.0.0/0"})   # even "everything" never lets loopback in
        self.assertFalse(h2.net_ok("127.0.0.1"))
        self.assertTrue(h2.net_ok("203.0.113.7"))

    def test_no_tile_without_a_host_and_list(self):
        h = self.make()
        self.assertEqual([x[0] for x in h.list_hosts()], ["laptop"])
        h.revoke("laptop")
        self.assertIsNone(h.laptop_view())


class Cleaning(Base):
    def test_body_limits(self):
        with self.assertRaises(hh.HostError) as e:
            hh.parse_body(b"x" * 9000)
        self.assertEqual(e.exception.code, 413)
        for bad in (b"{", b"[1]", b"\xff\xfe"):
            with self.assertRaises(hh.HostError) as e:
                hh.parse_body(bad)
            self.assertEqual(e.exception.code, 400)
        self.assertEqual(hh.parse_body(b""), {})

    def test_bad_values_clipped_and_unknown_keys_dropped(self):
        r = hh.clean_report({"next_in_s": 99999, "evil": 1, "power": {"mains": "yes", "battery_pct": 400, "x": 1},
                             "net": {"type": "carrier pigeon", "speed_mbps": -5, "name": "N" * 500 + "\n\x00"},
                             "apollo": "no", "backup": {"status": "weird", "detail": "d" * 500, "last_ok": "now"},
                             "uptime_s": float("nan")})
        self.assertNotIn("evil", r)
        self.assertEqual(r["next_in_s"], 15)
        self.assertIsNone(r["power"]["mains"])
        self.assertIsNone(r["power"]["battery_pct"])
        self.assertEqual(r["net"]["type"], "unknown")
        self.assertIsNone(r["net"]["speed_mbps"])
        self.assertEqual(len(r["net"]["name"]), 40)
        self.assertEqual(r["apollo"], {"service": None, "web": None, "stream_active": None})
        self.assertEqual(r["backup"]["status"], "unknown")
        self.assertEqual(len(r["backup"]["detail"]), 120)
        self.assertIsNone(r["backup"]["last_ok"])
        self.assertIsNone(r["uptime_s"])
        self.assertIsNone(hh.clean_report([1]))
        self.assertEqual(hh.clean_report({"next_in_s": 5})["next_in_s"], 5)

    def test_pc_block_cleaning(self):
        b = hh.clean_pc_laptop({"mode": "Monitor", "mode_since": 1763499000, "manual": 1, "apps": ["A", "A", "", 5, {"x": 1}, "B" * 99],
                                "monitor_stream": True, "junk": 1})
        self.assertEqual(b["mode"], "monitor")
        self.assertFalse(b["manual"])           # only a real true counts
        self.assertEqual(b["apps"], ["A", "5", "B" * 60])
        self.assertEqual(hh.clean_pc_laptop({"mode": "sideways"})["mode"], "unknown")
        self.assertIsNone(hh.clean_pc_laptop("x"))


class States(Base):
    def view(self): return self.h.laptop_view()

    def test_online_after_report_and_stale_after_three_intervals(self):
        self.rep()
        v = self.view()
        self.assertEqual(v["state"], "online")
        self.assertEqual(v["power"]["battery_pct"], 100)
        self.assertEqual(v["net"]["speed_mbps"], 1000)
        self.assertEqual(v["warnings"], [])
        self.clock.t += 44
        self.assertEqual(self.view()["state"], "online")
        self.clock.t += 2                                    # 46 s > 3 x 15
        self.assertEqual(self.view()["state"], "unknown")
        self.assertIsNotNone(self.view()["last_seen"])

    def test_next_in_s_sets_the_stale_limit(self):
        self.rep(next_in_s=60)
        self.clock.t += 170
        self.assertEqual(self.view()["state"], "online")
        self.clock.t += 20
        self.assertNotEqual(self.view()["state"], "online")

    def test_never_reported_is_unknown_then_asleep_when_probe_fails(self):
        self.assertEqual(self.view()["state"], "unknown")
        self.probe_result = False
        self.h.tick()
        self.assertEqual(self.view()["state"], "asleep")
        self.probe_result = True                              # answers but sends no report
        self.h.tick()
        self.assertEqual(self.view()["state"], "unknown")
        self.clock.t += 61                                    # an old probe result is not trusted
        self.probe_result = False
        self.assertEqual(self.view()["state"], "unknown")

    def test_no_probe_without_an_address(self):
        h = self.make({**CFG, "HOST_LAPTOP_IP": ""})
        h.add_token("laptop")
        h.tick()
        self.assertEqual(h.laptop_view()["state"], "unknown")

    def test_slow_link_warning_and_rate_limit(self):
        self.rep(net={"type": "ethernet", "speed_mbps": 100, "name": "E"})
        self.assertEqual(self.view()["warnings"], ["slow_link"])
        with self.assertRaises(hh.HostError) as e:
            self.h.on_report("laptop", report())             # same instant, 0 s later
        self.assertEqual(e.exception.code, 429)
        self.clock.t += 5
        self.h.on_report("laptop", report())

    def test_pc_block_gives_mode_apps_and_goes_stale(self):
        self.h.on_pc_report({"laptop": {"mode": "monitor", "mode_since": 1763499000, "manual": True, "apps": ["Notepad (test)"],
                                        "monitor_stream": True}, "caps": ["laptop"]})
        v = self.view()
        self.assertEqual(v["mode"], {"value": "monitor", "since": 1763499000, "known": True, "manual": True})
        self.assertEqual(v["apps"], ["Notepad (test)"])
        self.assertTrue(v["monitor_stream"])
        self.assertTrue(v["pc_laptop_support"])
        self.clock.t += 91
        v = self.view()
        self.assertEqual(v["mode"]["value"], "unknown")
        self.assertFalse(v["mode"]["known"])
        self.assertEqual(v["apps"], [])

    def test_pending_chain_is_none(self):
        self.assertIsNone(self.view()["pending"]["chain"])
        self.assertEqual(self.view()["tiers"], {"wake": "0", "open": "M", "mode": "M", "clip": "M"})


class Wake(Base):
    def test_packet_bytes_and_arguments(self):
        self.assertEqual(hh.magic_packet("02-00-00-AA-BB-CC"), b"\xff" * 6 + bytes.fromhex("020000AABBCC") * 16)
        self.assertEqual(len(hh.magic_packet("02:00:00:aa:bb:cc")), 102)
        with self.assertRaises(ValueError):
            hh.magic_packet("12:34")

    def test_wake_sends_and_shows_waking(self):
        r = self.h.request_wake()
        self.assertEqual(r["state"], "waking")
        self.assertEqual(self.sent, [("02-00-00-AA-BB-CC", "10.1.0.255", "10.1.0.4")])   # MAC comes from the config value
        v = self.h.laptop_view()
        self.assertEqual(v["state"], "waking")
        self.assertTrue(v["pending"]["wake"])

    def test_cooldown_and_online_409(self):
        self.h.request_wake()
        with self.assertRaises(hh.HostError) as e:
            self.h.request_wake()
        self.assertEqual(e.exception.code, 429)
        self.clock.t += 11
        self.h.request_wake()
        self.assertEqual(len(self.sent), 2)
        self.rep()
        self.clock.t += 20
        self.rep()
        with self.assertRaises(hh.HostError) as e:
            self.h.request_wake()
        self.assertEqual(e.exception.code, 409)

    def test_not_configured(self):
        h = self.make({**CFG, "HOST_LAPTOP_MAC": ""})
        with self.assertRaises(hh.HostError) as e:
            h.request_wake()
        self.assertEqual(e.exception.code, 409)
        self.assertFalse(h.laptop_view()["wake_configured"])

    def test_wake_not_confirmed_after_timeout(self):
        self.h.request_wake()
        self.clock.t += 119
        self.h.tick()
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.h.laptop_view()["state"], "waking")
        self.clock.t += 2
        self.h.tick()
        self.assertEqual(self.kinds(), ["host-wake-failed"])
        v = self.h.laptop_view()
        self.assertNotEqual(v["state"], "waking")
        self.assertEqual(v["pending"]["wake_note"], "Wake sent, laptop did not answer")
        self.assertNotIn("woke", self.msgs[0]["body"].lower().replace("did not wake", ""))
        self.h.tick()
        self.assertEqual(self.kinds(), ["host-wake-failed"])      # once

    def test_wake_answered_by_a_report_does_not_fail(self):
        self.h.request_wake()
        self.clock.t += 30
        self.rep()
        self.assertEqual(self.h.laptop_view()["state"], "online")
        self.clock.t += 100
        self.rep()
        self.h.tick()
        self.assertEqual(self.kinds(), [])

    def test_send_error_is_502(self):
        h = hh.HostHub(self.load, self.save, self.msgs.append, self.claude, CFG, lambda: True, lambda: self.settings,
                       lambda: False, lambda *a: None, clock=self.clock, sender=lambda *a: (_ for _ in ()).throw(OSError("net down")))
        with self.assertRaises(hh.HostError) as e:
            h.request_wake()
        self.assertEqual(e.exception.code, 502)


class Notifications(Base):
    def test_battery_low_once_per_discharge_and_rearms(self):
        self.rep(power={"mains": False, "battery_pct": 25})
        self.assertEqual(self.kinds(), [])
        self.rep(power={"mains": False, "battery_pct": 19})
        self.rep(power={"mains": False, "battery_pct": 15})
        self.assertEqual(self.kinds(), ["host-battery-low"])
        self.assertEqual(self.msgs[0]["cat"], "host")
        self.assertEqual(self.msgs[0]["group"], "host:laptop:host-battery-low")
        self.assertTrue(self.msgs[0]["title"].startswith("Laptop: "))
        self.rep(power={"mains": True, "battery_pct": 30})            # charger back: re-arm
        self.rep(power={"mains": False, "battery_pct": 10})
        self.assertEqual(self.kinds(), ["host-battery-low", "host-battery-low"])

    def test_battery_charging_low_is_silent(self):
        self.rep(power={"mains": True, "battery_pct": 5})
        self.assertEqual(self.kinds(), [])

    def test_battery_flag_survives_restart(self):
        self.rep(power={"mains": False, "battery_pct": 10})
        h2 = self.make()
        h2.on_report("laptop", report(power={"mains": False, "battery_pct": 9}))
        self.assertEqual(self.kinds(), ["host-battery-low"])

    def test_backup_failed_once_per_at(self):
        bad = lambda at: {"status": "failed", "last_ok": 1, "at": at, "detail": "disk full"}
        self.rep(backup=bad(1763500100))
        self.rep(backup=bad(1763500100))
        self.assertEqual(self.kinds(), ["host-backup-failed"])
        self.assertEqual(self.msgs[0]["body"], "disk full")
        self.rep(backup=bad(1763600000))
        self.assertEqual(self.kinds(), ["host-backup-failed"] * 2)
        self.rep(backup={"status": "ok", "last_ok": 1763700000, "at": 1763700000, "detail": ""})
        self.assertEqual(len(self.msgs), 2)

    def stream(self, on):
        self.rep(apollo={"service": True, "web": True, "stream_active": on})

    def run_stream(self, seconds):
        """Reports with the stream on, one every 10 s like a live laptop."""
        for _ in range(seconds // 10):
            self.clock.t += 4
            self.stream(True)

    def pc(self):
        self.h.on_pc_report({"laptop": {"apps": []}, "caps": ["laptop"]})

    def test_stream_died_unexpected(self):
        self.stream(True)
        self.run_stream(70)
        self.stream(False)
        self.assertEqual(self.kinds(), ["host-stream-died"])

    def test_short_stream_is_not_died(self):
        self.stream(True)
        self.run_stream(20)
        self.stream(False)
        self.assertEqual(self.kinds(), [])

    def test_stream_end_after_mc_mode_stop_is_not_died(self):
        self.stream(True)
        self.run_stream(120)
        self.pc()
        self.h.request("mode", "th", {"mode": "own", "ts": 1, "sig": "good"})
        self.run_stream(60)                                   # a slow switch: still running when the stream ends
        self.stream(False)
        self.assertEqual(self.kinds(), [])

    def test_stream_end_within_30s_of_mc_stop_result(self):
        self.stream(True)
        self.run_stream(120)
        self.pc()
        self.h.request("mode", "th", {"mode": "own", "ts": 1, "sig": "good"})
        key = self.claude.items[-1]["key"]
        self.clock.t += 10
        self.h.on_result({"key": key, "ok": True, "detail": "x"})
        self.clock.t += 20
        self.stream(False)
        self.assertEqual(self.kinds(), [])
        self.stream(True)                                      # same again but the stop was long ago
        self.run_stream(70)
        self.stream(False)
        self.assertEqual(self.kinds(), ["host-stream-died"])

    def test_stream_end_with_pc_offline_is_not_died(self):
        self.stream(True)
        self.run_stream(100)
        self.helper = False
        self.stream(False)
        self.assertEqual(self.kinds(), [])

    def test_stream_gap_in_reports_is_not_a_stream_end(self):
        self.stream(True)
        self.clock.t += 600                                    # the laptop was off; the next report starts fresh
        self.stream(False)
        self.assertEqual(self.kinds(), [])

    def test_slow_link_quiet_once_a_day(self):
        slow = {"type": "ethernet", "speed_mbps": 100, "name": "E"}
        self.rep(net=slow, apollo={"service": True, "web": True, "stream_active": True})
        self.rep(net=slow, apollo={"service": True, "web": True, "stream_active": True})
        self.assertEqual(self.kinds(), ["host-slow-link"])
        self.assertTrue(self.msgs[0]["quiet"])
        self.clock.t += 86400
        self.rep(net=slow, apollo={"service": True, "web": True, "stream_active": True})
        self.assertEqual(len(self.msgs), 2)

    def test_mute_and_category_suppress_but_still_log(self):
        self.settings["kinds"]["host"] = False
        self.rep(power={"mains": False, "battery_pct": 10})
        self.assertEqual(self.msgs, [])
        self.assertTrue(any("battery low" in a[1] for a in self.logs))
        self.settings.update(kinds={"host": True}, muted=True)
        self.rep(power={"mains": True, "battery_pct": 10})
        self.rep(power={"mains": False, "battery_pct": 9})
        self.assertEqual(self.msgs, [])

    def test_quiet_hours_flag(self):
        h = hh.HostHub(self.load, self.save, self.msgs.append, self.claude, CFG, lambda: True, lambda: self.settings,
                       lambda: True, lambda *a: None, clock=self.clock)
        h.on_report("laptop", report(power={"mains": False, "battery_pct": 3}))
        self.assertTrue(self.msgs[0]["quiet"])

    def test_laptop_event_limits(self):
        for i in range(3):
            self.h.on_event("laptop", {"kind": "Disk Full!", "key": f"k{i}", "title": "T" * 200, "body": "b" * 900})
        with self.assertRaises(hh.HostError) as e:
            self.h.on_event("laptop", {"kind": "diskfull"})
        self.assertEqual(e.exception.code, 429)
        self.assertEqual(len(self.msgs[0]["title"]), len("Laptop: ") + 80)
        self.assertEqual(len(self.msgs[0]["body"]), 200)
        self.assertEqual(self.msgs[0]["kind"], "host-ev-diskfull")
        self.h.on_event("laptop", {"kind": "other"})              # another kind has its own budget
        self.clock.t += 3601
        self.h.on_event("laptop", {"kind": "diskfull"})
        with self.assertRaises(hh.HostError):
            self.h.on_event("laptop", {"kind": "!!!"})


class Actions(Base):
    def setUp(self):
        super().setUp()
        self.h.on_pc_report({"laptop": {"mode": "monitor", "apps": ["ROBOGUIDE", "Notepad (test)"]}, "caps": ["loop", "chat", "laptop"]})

    def ask(self, action, **d):
        d.setdefault("ts", 1)
        d.setdefault("sig", "good")
        return self.h.request(action, "th", d)

    def code(self, action, **d):
        with self.assertRaises(hh.HostError) as e:
            self.ask(action, **d)
        return e.exception.code

    def test_open_enqueues_with_tier_m_and_signed_message(self):
        self.ask("open", app="Notepad (test)")
        it = self.claude.items[0]
        self.assertEqual((it["kind"], it["app"]), ("laptop-open", "Notepad (test)"))
        self.assertEqual(self.claude.verified, [("host|open|Notepad (test)|1", "M")])
        self.assertEqual(self.h.laptop_view()["pending"]["open"]["state"], "requested")

    def test_open_unknown_app_400(self):
        self.assertEqual(self.code("open", app="Calc"), 400)
        self.assertEqual(self.code("open", app=""), 400)
        self.assertEqual(self.code("open", app={"a": 1}), 400)
        self.assertEqual(self.claude.items, [])

    def test_apps_must_be_fresh(self):
        self.clock.t += 100
        self.assertEqual(self.code("open", app="ROBOGUIDE"), 400)

    def test_mode_list(self):
        for m in ("monitor", "app", "own", "auto"):
            self.job_done()
            self.ask("mode", mode=m)
            self.assertEqual(self.claude.items[-1]["mode"], m)
        self.job_done()
        self.assertEqual(self.code("mode", mode="gaming"), 400)
        self.assertEqual(self.code("mode", mode="monitor; calc"), 400)

    def job_done(self):
        j = self.h.job
        if j:
            self.h.on_result({"key": j["key"], "ok": True, "detail": "d"})

    def test_second_request_while_busy_409(self):
        self.ask("mode", mode="own")
        self.assertEqual(self.code("open", app="ROBOGUIDE"), 409)
        self.job_done()
        self.ask("open", app="ROBOGUIDE")

    def test_job_that_never_answers_expires(self):
        self.ask("mode", mode="own")
        self.clock.t += 121
        self.h.tick()
        self.assertEqual(self.h.laptop_view()["pending"]["mode"]["state"], "failed")
        self.h.on_pc_report({"laptop": {"apps": []}, "caps": ["laptop"]})
        self.ask("mode", mode="app")                        # no longer blocked

    def test_helper_stale_and_old_mc_pc(self):
        self.helper = False
        self.assertEqual(self.code("mode", mode="own"), 409)
        self.helper = True
        h = self.make()                                      # a PC that never advertised "laptop"
        h.on_pc_report({"laptop": {"apps": ["ROBOGUIDE"]}, "caps": ["loop", "chat"]})
        with self.assertRaises(hh.HostError) as e:
            h.request("open", "th", {"app": "ROBOGUIDE", "ts": 1, "sig": "good"})
        self.assertEqual(e.exception.code, 409)
        self.assertFalse(h.laptop_view()["pc_laptop_support"])

    def test_fingerprint_failure_is_403_and_nothing_queued(self):
        self.assertEqual(self.code("mode", mode="own", sig="forged"), 403)
        self.assertEqual(self.claude.items, [])
        self.assertIsNone(self.h.job)
        self.assertEqual(self.code("mode", mode="own", ts="abc"), 400)

    def test_clip_needs_online_laptop_and_has_tier_m(self):
        self.assertEqual(self.code("clip"), 409)
        self.rep()
        self.ask("clip")
        self.assertEqual(self.claude.items[0]["kind"], "laptop-clip")
        self.assertEqual(self.claude.verified[-1], ("host|clip||1", "M"))

    def test_lowering_a_tier_is_one_line(self):
        hh.HOST_TIERS["mode"] = "0"
        try:
            self.h.request("mode", "th", {"mode": "own"})       # no signature at tier 0
        finally:
            hh.HOST_TIERS["mode"] = "M"
        self.assertEqual(self.claude.verified[-1][1], "0")

    def test_unknown_action(self):
        with self.assertRaises(hh.HostError):
            self.h.request("format-c", "th", {})

    def test_result_open_notifies(self):
        self.ask("open", app="ROBOGUIDE")
        key = self.claude.items[0]["key"]
        self.h.on_result({"key": "other-1", "ok": True})       # not ours: ignored
        self.h.on_result({"key": key, "ok": True, "detail": "window is up"})
        self.assertEqual(self.kinds(), ["host-open-done"])
        self.assertTrue(self.msgs[0]["quiet"])                 # quiet on success
        self.h.on_result({"key": key, "ok": False, "detail": "x"})   # a second answer is ignored
        self.assertEqual(len(self.msgs), 1)
        self.ask("open", app="ROBOGUIDE")
        self.h.on_result({"key": self.claude.items[-1]["key"], "ok": False, "detail": "PC is locked"})
        self.assertEqual(self.kinds(), ["host-open-done", "host-open-failed"])
        self.assertFalse(self.msgs[1]["quiet"])
        self.assertEqual(self.msgs[1]["body"], "PC is locked")
        self.assertEqual(self.h.laptop_view()["pending"]["open"]["detail"], "PC is locked")

    def test_mode_result_updates_tile_and_marks_manual(self):
        self.ask("mode", mode="own")
        self.h.on_result({"key": self.claude.items[0]["key"], "ok": True, "detail": "mode=own"})
        m = self.h.laptop_view()["mode"]
        self.assertEqual((m["value"], m["manual"]), ("own", True))
        self.ask("mode", mode="auto")
        self.h.on_result({"key": self.claude.items[1]["key"], "ok": True, "detail": ""})
        self.assertFalse(self.h.laptop_view()["mode"]["manual"])

    def test_finished_job_leaves_the_tile_after_a_minute(self):
        self.ask("mode", mode="own")
        self.job_done()
        self.assertEqual(self.h.laptop_view()["pending"]["mode"]["state"], "done")
        self.clock.t += 61
        self.assertIsNone(self.h.laptop_view()["pending"]["mode"])


if __name__ == "__main__":
    unittest.main()
