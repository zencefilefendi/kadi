import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from kadi.mcp import LEGACY_VERSIONS, MODERN_VERSIONS, TOOLS, build  # noqa: E402

MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
               "io.modelcontextprotocol/clientCapabilities": {},
               "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"}}


class MCPBase(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "mcp.db")
        self.s = build(db=self.db)
        self.n = 0

    def tearDown(self):
        self.s.engine.close()

    def rpc(self, method, params=None, modern=False):
        self.n += 1
        params = dict(params or {})
        if modern:
            params["_meta"] = MODERN_META
        return self.s.handle({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})

    def call(self, name, args=None, modern=False):
        r = self.rpc("tools/call", {"name": name, "arguments": args or {}}, modern)
        return r["result"]


class TestProtocol(MCPBase):
    def test_legacy_initialize_negotiation(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "c", "version": "1"}})["result"]
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["capabilities"])
        self.assertEqual(r["serverInfo"]["name"], "kadi")
        self.assertIn("kadi_resolve", r["instructions"])
        r = self.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(r["protocolVersion"], LEGACY_VERSIONS[0])

    def test_modern_discover_and_per_request_version(self):
        r = self.rpc("server/discover", modern=True)["result"]
        self.assertEqual(r["resultType"], "complete")
        self.assertIn(MODERN_VERSIONS[0], r["supportedVersions"])
        self.assertEqual(r["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "kadi")
        r = self.rpc("tools/list", modern=True)["result"]
        self.assertEqual(r["resultType"], "complete")
        bad = self.s.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/list",
                             "params": {"_meta": {**MODERN_META, "io.modelcontextprotocol/protocolVersion": "1900-01-01"}}})
        self.assertEqual(bad["error"]["code"], -32022)
        self.assertIn("2026-07-28", bad["error"]["data"]["supported"])
        nocaps = self.s.handle({"jsonrpc": "2.0", "id": 10, "method": "tools/list",
                                "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}})
        self.assertEqual(nocaps["error"]["code"], -32602)

    def test_jsonrpc_errors_and_notifications(self):
        self.assertIsNone(self.s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(self.rpc("nope/nope")["error"]["code"], -32601)
        self.assertEqual(self.rpc("tools/call", {"name": "kadi_nope"})["error"]["code"], -32602)
        self.assertEqual(self.s.handle({"jsonrpc": "1.0", "id": 1, "method": "ping"})["error"]["code"], -32600)
        self.assertEqual(self.rpc("ping")["result"], {})
        batch = self.s.handle([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                               {"jsonrpc": "2.0", "method": "notifications/initialized"}])
        self.assertEqual(len(batch), 1)

    def test_tool_listing_is_well_formed(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {t["name"] for t in TOOLS})
        for t in tools:
            self.assertTrue(t["name"].startswith("kadi_"))
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("readOnlyHint", t["annotations"])
            self.assertTrue(t["description"])

    def test_input_validation_is_a_tool_error(self):
        r = self.call("kadi_define_question", {"name": "x", "options": ["a"]})
        self.assertTrue(r["isError"])
        self.assertIn("options", r["content"][0]["text"])
        r = self.call("kadi_decide", {"question": "missing", "text": "hi"})
        self.assertTrue(r["isError"])
        self.assertIn("kadi_define_question", r["content"][0]["text"])
        r = self.call("kadi_decide", {"question": "x", "text": "hi", "bogus": 1})
        self.assertTrue(r["isError"])


class TestAgentAsOracle(MCPBase):
    INTENTS = {"card": ["my card has not arrived", "where is my new card", "card delivery is late"],
               "refund": ["i want my money back", "please refund this charge", "refund for a duplicate payment"],
               "login": ["cannot log in", "password reset is not working", "locked out of my account"]}

    def case(self, rng):
        y = rng.choice(sorted(self.INTENTS))
        return f"{rng.choice(['hi', 'hello', 'hey'])} {rng.choice(self.INTENTS[y])} {rng.randint(0, 10**6)}", y

    def test_learns_from_the_calling_agent(self):
        r = self.call("kadi_define_question", {"name": "intent", "options": sorted(self.INTENTS),
                                               "target_error": 0.05, "policy": "ltt"})
        self.assertFalse(r["isError"])
        rng = random.Random(0)
        tickets = local = wrong = 0
        audit_candidates = set()
        n = 1200
        for i in range(n):
            text, y = self.case(rng)
            out = self.call("kadi_decide", {"question": "intent", "text": text})["structuredContent"]
            if out["status"] == "needs_verdict":
                tickets += 1
                if out["reason"] == "audit":
                    audit_candidates.add(tuple(out["candidates"]))
                done = self.call("kadi_resolve", {"ticket": out["ticket"], "label": y})["structuredContent"]
                self.assertEqual(done["label"], y)
            else:
                local += i >= n // 2
                wrong += out["label"] != y
        self.assertGreater(local / (n - n // 2), 0.6, "the agent should stop being asked for routine cases")
        self.assertLessEqual(wrong / n, 0.05)
        self.assertTrue(all(len(c) == 3 for c in audit_candidates), "audits must not reveal Kadı's own answer")
        st = self.call("kadi_stats")["structuredContent"]
        self.assertEqual(st["decisions"], n)
        self.assertGreater(st["questions"][0]["decided_locally_recent"], 0.6)
        self.assertTrue(self.call("kadi_verify_ledger")["structuredContent"]["ok"])

    def test_resolve_errors_and_retry(self):
        self.call("kadi_define_question", {"name": "yn", "options": ["yes", "no"]})
        out = self.call("kadi_decide", {"question": "yn", "text": "is this spam?"})["structuredContent"]
        self.assertEqual(out["status"], "needs_verdict")
        bad = self.call("kadi_resolve", {"ticket": out["ticket"], "label": "maybe"})
        self.assertTrue(bad["isError"])
        ok = self.call("kadi_resolve", {"ticket": out["ticket"], "label": "no"})
        self.assertFalse(ok["isError"])
        again = self.call("kadi_resolve", {"ticket": out["ticket"], "label": "no"})
        self.assertTrue(again["isError"])
        self.assertIn("expired", again["content"][0]["text"])

    def test_definitions_persist_and_conflicts_are_rejected(self):
        self.call("kadi_define_question", {"name": "route", "options": ["a", "b"], "instructions": "route it"})
        same = self.call("kadi_define_question", {"name": "route", "options": ["a", "b"]})["structuredContent"]
        self.assertTrue(same["already_existed"])
        clash = self.call("kadi_define_question", {"name": "route", "options": ["a", "c"]})
        self.assertTrue(clash["isError"])
        self.s.engine.close()
        self.s = build(db=self.db)
        names = [q["name"] for q in self.call("kadi_list_questions")["structuredContent"]["questions"]]
        self.assertEqual(names, ["route"])

    def test_recent_decisions_pagination(self):
        self.call("kadi_define_question", {"name": "yn", "options": ["yes", "no"]})
        for i in range(5):
            t = self.call("kadi_decide", {"question": "yn", "text": f"case {i}"})["structuredContent"]
            self.call("kadi_resolve", {"ticket": t["ticket"], "label": "yes"})
        page = self.call("kadi_recent_decisions", {"limit": 2})["structuredContent"]
        self.assertEqual(len(page["decisions"]), 2)
        nxt = self.call("kadi_recent_decisions", {"limit": 10, "before_id": page["next_before_id"]})
        self.assertEqual(len(nxt["structuredContent"]["decisions"]), 3)


class TestStdio(unittest.TestCase):
    def test_end_to_end_over_stdio(self):
        db = os.path.join(tempfile.mkdtemp(), "s.db")
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "kadi_define_question", "arguments": {"name": "yn", "options": ["yes", "no"]}}},
        ]
        stdin = "\n".join(json.dumps(m) for m in msgs) + "\nnot json\n"
        p = subprocess.run([sys.executable, "-m", "kadi.cli", "mcp", "--db", db], input=stdin.encode(),
                           capture_output=True, cwd=ROOT, timeout=60)
        lines = [json.loads(x) for x in p.stdout.decode().splitlines()]
        self.assertEqual([m.get("id") for m in lines], [1, 2, 3, None])
        self.assertEqual(lines[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(len(lines[1]["result"]["tools"]), len(TOOLS))
        self.assertFalse(lines[2]["result"]["isError"])
        self.assertEqual(lines[3]["error"]["code"], -32700)
        self.assertIn(b"kadi mcp ready", p.stderr)


if __name__ == "__main__":
    unittest.main()
