import json
import os
import random
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kadi import Binary, Choice, FunctionOracle, Kadi, OracleError  # noqa: E402
from kadi.cli import main as cli_main, replay  # noqa: E402
from kadi.config import EXAMPLE, build_engine, load  # noqa: E402
from kadi.server import serve  # noqa: E402

BANK = {"pos": ["love it", "great product", "works perfectly", "amazing support", "five stars"],
        "neg": ["hate it", "broken again", "terrible support", "waste of money", "one star"]}


def stream(n, seed=1):
    rng = random.Random(seed)
    for _ in range(n):
        y = rng.choice(["pos", "neg"])
        yield f"{rng.choice(BANK[y])} {rng.choice(BANK[y])} ref {rng.randint(0, 10**6)}", y


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "k.db")
        self.truth = {}
        self.calls = 0
        self.flip = False
        self.down = False

        def fn(q, text, ctx):
            if self.down:
                raise OracleError("down")
            self.calls += 1
            y = self.truth[text]
            if self.flip:
                y = "neg" if y == "pos" else "pos"
            return y
        self.oracle = FunctionOracle(fn, cost_per_call=0.01)

    def warm(self, k, q, n=1500, seed=1):
        for text, y in stream(n, seed):
            self.truth[text] = y
            k.decide(q, text)


class TestModes(Base):
    def test_shadow_never_answers_locally_but_projects(self):
        q = Choice("s", ["pos", "neg"], mode="shadow")
        k = Kadi(self.oracle, db=self.db, audit_rate=0, seed=0)
        self.warm(k, q, 1500)
        self.assertEqual(self.calls, 1500 - k.stats()[0]["counts"]["memory"])
        st = k.stats()[0]
        self.assertEqual(st["counts"]["reflex"], 0)
        self.assertGreater(st["shadow"]["would_be_local"], 0.5)
        self.assertGreater(st["shadow"]["agreement"], 0.95)
        k.close()

    def test_mondrian_goes_local(self):
        q = Choice("m", ["pos", "neg"], conditional=True, target_error=0.05)
        k = Kadi(self.oracle, db=self.db, audit_rate=0, seed=0)
        self.warm(k, q, 2000)
        self.assertGreater(k.stats()[0]["local_rate_recent"], 0.5)
        k.close()
        k2 = Kadi(self.oracle, db=self.db, audit_rate=0)  # reload Mondrian state
        k2.register(q)
        self.assertTrue(k2.stats()[0]["conditional"])
        self.assertGreater(k2.stats()[0]["calibration_size"], 40)
        k2.close()

    def test_novel_input_escalates(self):
        q = Choice("n", ["pos", "neg"])
        k = Kadi(self.oracle, db=self.db, audit_rate=0, seed=0)
        self.warm(k, q, 1500)
        weird = "ζζζ ψψψ ωωω ЖЖЖ ЩЩЩ"
        self.truth[weird] = "pos"
        self.assertGreater(k._brains["n"].model.novelty(k.featurize(weird)), 0.8)
        d = k.decide(q, weird)
        self.assertEqual(d.tier, "oracle")
        self.assertIn(d.reason, ("novel", "ambiguous", "empty_set"))
        k.close()


class TestGuarantee(unittest.TestCase):
    """Regression: calibrating on escalated (non-random) examples made the
    threshold ratchet loose; with an imbalanced binary question and per-label
    calibration, local answers disagreed with the oracle 58% of the time."""

    def run_stream(self, conditional, n=3000, target=0.05):
        rng = random.Random(5)
        words = {"yes": ["asap", "production down", "urgent", "right now", "all users affected"],
                 "no": ["when you can", "minor thing", "no rush", "small question", "just curious"]}
        filler = ["hi", "thanks", "team", "please", "today", "again", "app", "login", "invoice", "export"]
        truth = {}
        k = Kadi(FunctionOracle(lambda q, t, c: truth[t]), db=":memory:", seed=3)
        q = Binary("urgent", "?", target_error=target, conditional=conditional)
        disagree = 0
        for i in range(n):
            y = "yes" if rng.random() < 0.15 else "no"   # rare positive class
            t = " ".join(rng.sample(filler, 3) + [rng.choice(words[y])]) + f" #{i}"
            if rng.random() < 0.04:                      # ambiguous inputs: hint of the other class
                t += " " + rng.choice(words["no" if y == "yes" else "yes"])
            truth[t] = y
            disagree += k.decide(q, t).label != y
        st = k.stats()[0]
        k.close()
        return disagree / n, st

    def test_marginal_bound(self):
        err, st = self.run_stream(False)
        self.assertLessEqual(err, 0.05 * 1.3)
        self.assertGreater(st["local_rate_recent"], 0.5)

    def test_mondrian_bound(self):
        err, st = self.run_stream(True)
        self.assertLessEqual(err, 0.05 * 1.3)
        self.assertLessEqual(st["realized_miscoverage"], 0.08)


class TestResilience(Base):
    def test_fallback_when_oracle_down(self):
        q = Choice("f", ["pos", "neg"])
        k = Kadi(self.oracle, db=self.db, audit_rate=0, on_oracle_error="best_guess")
        self.down = True
        d = k.decide(q, "brand new text")
        self.assertEqual(d.tier, "fallback")
        self.assertTrue(d.flagged)
        self.assertIn(d.label, q.options)
        k.close()
        k2 = Kadi(self.oracle, db=self.db + "2", audit_rate=0)
        with self.assertRaises(OracleError):
            k2.decide(q, "brand new text")
        k2.close()

    def test_self_heals_when_the_world_flips(self):
        q = Choice("h", ["pos", "neg"], target_error=0.05)
        k = Kadi(self.oracle, db=self.db, audit_rate=0, seed=0)
        self.warm(k, q, 1500)
        k.audit_rate = 1.0
        self.flip = True
        late = []
        for i, (text, y) in enumerate(stream(300, seed=99)):
            self.truth[text] = y
            d = k.decide(q, text)
            if i >= 150:
                late.append(d.label != y)  # flipped oracle: correct answer is the opposite of y
        self.assertGreater(sum(late) / len(late), 0.95)
        k.close()

    def test_drift_breaker_trips_and_alerts(self):
        q = Choice("d", ["pos", "neg"], target_error=0.05)
        alerts = []
        k = Kadi(self.oracle, db=self.db, audit_rate=0, seed=0, alert_hook=alerts.append, probation_length=100)
        self.warm(k, q, 1500)
        b = k._brains["d"]
        with b.lock:  # a model that keeps being confidently wrong on audits
            b.checks.extend([False] * 20 + [True] * 40)
            k._check_drift(b)
            k._check_drift(b)  # second trip within the hour: no duplicate alert
        self.assertEqual(b.probation, 100)
        d = None
        for text, y in stream(5, seed=7):
            self.truth[text] = y
            d = k.decide(q, text)
        self.assertEqual((d.tier, d.reason), ("oracle", "probation"))
        self.assertEqual(b.probation, 95)
        time.sleep(0.1)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], "drift")
        self.assertEqual(len(k.store.query("SELECT * FROM alerts")), 1)
        k.close()

    def test_input_validation(self):
        k = Kadi(self.oracle, db=self.db)
        q = Binary("b", "?")
        for bad in ("", "   ", None, "x" * 100_001):
            with self.assertRaises(ValueError):
                k.decide(q, bad)
        with self.assertRaises(KeyError):
            k.decide("nope", "hello")
        k.close()


class TestPrivacy(Base):
    def test_pii_redacted_in_ledger_and_hash_is_keyed(self):
        q = Choice("p", ["pos", "neg"])
        seen = {}
        k = Kadi(FunctionOracle(lambda q_, t, c: seen.setdefault("t", t) and "pos"), db=self.db,
                 redact_oracle=True, secret=b"k1")
        k.decide(q, "contact ayse@example.com or +90 532 123 45 67 about it")
        row = k.store.query("SELECT preview, input_hash FROM decisions")[0]
        self.assertNotIn("ayse@example.com", row["preview"])
        self.assertIn("<EMAIL>", row["preview"])
        self.assertIn("<PHONE>", seen["t"])
        k.close()
        k2 = Kadi(FunctionOracle(lambda *_: "pos"), db=self.db + "2", secret=b"k2")
        k2.decide(q, "contact ayse@example.com or +90 532 123 45 67 about it")
        self.assertNotEqual(row["input_hash"], k2.store.query("SELECT input_hash FROM decisions")[0]["input_hash"])
        k2.close()

    def test_store_inputs_off(self):
        k = Kadi(FunctionOracle(lambda *_: "pos"), db=self.db, store_inputs=False)
        k.decide(Choice("p", ["pos", "neg"]), "secret text")
        self.assertIsNone(k.store.query("SELECT preview FROM decisions")[0]["preview"])
        k.close()


class TestMigration(unittest.TestCase):
    def test_v01_database_upgrades(self):
        db = os.path.join(tempfile.mkdtemp(), "old.db")
        c = sqlite3.connect(db)
        c.executescript("""CREATE TABLE decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
            question TEXT NOT NULL, input_hash TEXT NOT NULL, preview TEXT, label TEXT NOT NULL, tier TEXT NOT NULL,
            confidence REAL, set_size INTEGER, oracle_label TEXT, audited INTEGER NOT NULL DEFAULT 0, agreed INTEGER,
            cost REAL NOT NULL DEFAULT 0, latency_ms REAL NOT NULL DEFAULT 0);""")
        c.close()
        k = Kadi(FunctionOracle(lambda *_: "a"), db=db)
        d = k.decide(Choice("c", ["a", "b"]), "x")
        self.assertEqual(d.reason, "uncalibrated")
        k.close()


class TestServer(Base):
    TOKEN = "t0p-secret-token"

    def setUp(self):
        super().setUp()
        self.k = Kadi(self.oracle, db=self.db, audit_rate=0)
        self.q = Choice("s", ["pos", "neg"])
        self.k.register(self.q)
        self.httpd = serve(self.k.store, "127.0.0.1", 0, engine=self.k, token=self.TOKEN,
                           rate_limit_per_minute=600, background=True)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.k.close()

    def req(self, path, body=None, token=TOKEN, raw=None, ctype="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET")
        if data is not None:
            r.add_header("content-type", ctype)
        if token:
            r.add_header("authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read(), e.headers

    def test_auth_and_health(self):
        self.assertEqual(self.req("/healthz", token=None)[0], 200)
        self.assertEqual(self.req("/api/summary", token=None)[0], 401)
        self.assertEqual(self.req("/api/summary", token="wrong")[0], 401)
        self.assertEqual(self.req("/metrics", token=None)[0], 401)
        code, _, headers = self.req("/api/summary")
        self.assertEqual(code, 200)
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertIn("default-src 'none'", headers.get("Content-Security-Policy"))

    def test_decide_teach_batch(self):
        self.truth["hello there"] = "pos"
        code, body, _ = self.req("/api/decide", {"question": "s", "text": "hello there"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["label"], "pos")
        self.assertEqual(self.req("/api/teach", {"question": "s", "text": "meh", "label": "neg"})[0], 200)
        self.assertEqual(self.req("/api/teach", {"question": "s", "text": "meh", "label": "zzz"})[0], 400)
        self.truth["a"] = "pos"
        code, body, _ = self.req("/api/decide/batch", {"items": [{"question": "s", "text": "a"},
                                                                 {"question": "nope", "text": "b"}, 5]})
        res = json.loads(body)["results"]
        self.assertEqual(res[0]["label"], "pos")
        self.assertIn("error", res[1])
        self.assertIn("error", res[2])
        qs = json.loads(self.req("/api/questions")[1])
        self.assertEqual(qs[0]["name"], "s")
        self.k.checkpoint()
        self.assertIn(b'kadi_decisions_total{question="s",tier="oracle"}', self.req("/metrics")[1])

    def test_bad_inputs(self):
        self.assertEqual(self.req("/api/decide", {"question": "nope", "text": "x"})[0], 404)
        self.assertEqual(self.req("/api/decide", {"question": "s", "text": 5})[0], 400)
        self.assertEqual(self.req("/api/decide", raw=b"{not json")[0], 400)
        self.assertEqual(self.req("/api/decide", raw=b"[]")[0], 400)
        self.assertEqual(self.req("/api/decide", {"question": "s", "text": "x"}, ctype="text/plain")[0], 415)
        self.assertEqual(self.req("/api/decide", raw=b" " * (300 * 1024))[0], 413)
        self.assertEqual(self.req("/api/feed?after=abc")[0], 400)
        self.down = True
        self.assertEqual(self.req("/api/decide", {"question": "s", "text": "unseen text"})[0], 502)

    def test_rate_limit(self):
        codes = [self.req("/api/summary")[0] for _ in range(150)]
        self.assertIn(429, codes)

    def test_refuses_public_bind_without_token(self):
        with self.assertRaises(SystemExit):
            serve(self.k.store, "0.0.0.0", 0, engine=self.k, token=None, background=True)


class TestConfigAndReplay(unittest.TestCase):
    def test_example_config_loads(self):
        p = os.path.join(tempfile.mkdtemp(), "kadi.toml")
        with open(p, "w") as f:
            f.write(EXAMPLE.replace('db = "kadi.db"', f'db = "{os.path.dirname(p)}/k.db"'))
        cfg = load(p)
        self.assertEqual(cfg.questions[0].mode, "shadow")
        k = build_engine(cfg, oracle=FunctionOracle(lambda *_: "bug"))
        self.assertEqual(k.decide("route_ticket", "it crashes").label, "bug")
        k.close()

    def test_init_refuses_overwrite(self):
        p = os.path.join(tempfile.mkdtemp(), "kadi.toml")
        self.assertEqual(cli_main(["init", p]), 0)
        self.assertEqual(cli_main(["init", p]), 1)

    def test_replay_tradeoff(self):
        rows = [{"text": t, "label": y} for t, y in stream(1500)]
        tight = replay(rows, ("pos", "neg"), 0.01, 0.01)
        loose = replay(rows, ("pos", "neg"), 0.10, 0.01)
        self.assertGreaterEqual(loose["local_rate"], tight["local_rate"])
        self.assertLess(tight["steady_error_rate"], 0.03)
        self.assertGreater(loose["savings"], 0.5)


if __name__ == "__main__":
    unittest.main()


class TestSecurityRegressions(Base):
    """One test per finding of the adversarial review."""

    def _server(self, token=None):
        self.k = Kadi(self.oracle, db=self.db, audit_rate=0)
        self.k.register(Choice("s", ["pos", "neg"]))
        self.httpd = serve(self.k.store, "127.0.0.1", 0, engine=self.k, token=token, background=True)
        self.addCleanup(self.k.close)
        self.addCleanup(self.httpd.shutdown)
        return self.httpd.server_address[1]

    def _raw(self, port, method, path, headers, body=b""):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in headers.items():
            c.putheader(k, v)
        c.endheaders()
        if body:
            c.send(body)
        r = c.getresponse()
        out = r.status, r.read()
        c.close()
        return out

    def test_csrf_simple_request_refused(self):
        port = self._server()
        body = json.dumps({"question": "s", "text": "x", "label": "pos"}).encode()
        code, _ = self._raw(port, "POST", "/api/teach", {
            "Host": f"127.0.0.1:{port}", "Content-Type": "text/plain;charset=json",
            "Content-Length": str(len(body))}, body)
        self.assertEqual(code, 415)
        code, _ = self._raw(port, "POST", "/api/teach", {
            "Host": f"127.0.0.1:{port}", "Origin": "https://evil.example", "Content-Type": "application/json",
            "Content-Length": str(len(body))}, body)
        self.assertEqual(code, 403)

    def test_dns_rebinding_host_refused_without_token(self):
        port = self._server()
        self.assertEqual(self._raw(port, "GET", "/api/feed", {"Host": "evil.example"})[0], 403)
        self.assertEqual(self._raw(port, "GET", "/api/feed", {"Host": f"localhost:{port}"})[0], 200)

    def test_negative_content_length(self):
        port = self._server()
        code, _ = self._raw(port, "POST", "/api/decide", {
            "Host": f"127.0.0.1:{port}", "Content-Type": "application/json", "Content-Length": "-1"}, b"{}")
        self.assertEqual(code, 400)

    def test_redaction_does_not_merge_memory_keys(self):
        q = Choice("trust", ["a", "b"])
        k = Kadi(FunctionOracle(lambda q_, t, c: "b" if "evil" in t else "a"), db=self.db, audit_rate=0)
        self.assertEqual(k.decide(q, "is sender trusted? eve@evil.com").label, "b")
        d = k.decide(q, "is sender trusted? ali@good.com")
        self.assertNotEqual(d.tier, "memory")
        self.assertEqual(d.label, "a")
        k.close()

    def test_context_redacted_for_oracle(self):
        seen = {}
        k = Kadi(FunctionOracle(lambda q, t, c: seen.setdefault("c", c) and "a"), db=self.db, redact_oracle=True)
        k.decide(Choice("c", ["a", "b"]), "hello", {"email": "ali@example.com", "card": "4111 1111 1111 1111"})
        self.assertNotIn("ali@example.com", json.dumps(seen["c"]))
        self.assertNotIn("4111", json.dumps(seen["c"]))
        k.close()

    def test_audit_returns_oracle_label(self):
        q = Choice("a", ["pos", "neg"])
        k = Kadi(self.oracle, db=self.db, audit_rate=0, seed=0)
        self.warm(k, q, 1500)
        k.audit_rate = 1.0
        self.flip = True
        text, y = next(stream(1, seed=123))
        self.truth[text] = y
        d = k.decide(q, text)
        self.assertEqual(d.reason, "audited")
        self.assertEqual(d.label, "neg" if y == "pos" else "pos")
        self.assertTrue(d.flagged)
        k.close()

    def test_shadow_probation_can_end(self):
        q = Choice("sh", ["pos", "neg"], mode="shadow")
        k = Kadi(self.oracle, db=self.db, audit_rate=0, seed=0, probation_length=50)
        self.warm(k, q, 1500)
        b = k._brains["sh"]
        with b.lock:
            b.checks.extend([False] * 60)
            k._check_drift(b)
        before = b.shadow_local
        self.warm(k, q, 400, seed=5)
        self.assertGreater(b.shadow_local, before)  # still measuring under probation
        k.close()

    def test_huge_random_input_is_bounded(self):
        rng = random.Random(0)
        junk = "".join(chr(rng.randint(0x4E00, 0x9FFF)) for _ in range(30_000))
        x = Kadi(self.oracle, db=self.db).featurize(junk)
        self.assertLessEqual(len(x), 2048)

    def test_rate_limiter_prune_is_bounded(self):
        from kadi.server import _RateLimiter
        rl = _RateLimiter(600)
        t0 = time.perf_counter()
        for i in range(25_000):
            rl.allow(f"ip{i}")
        self.assertLess(time.perf_counter() - t0, 3.0)
        self.assertLessEqual(len(rl.buckets), 25_000)
