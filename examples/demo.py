"""Live demo: a support desk triaging tickets, with the Divan dashboard open.

    python examples/demo.py              # then open http://127.0.0.1:8765

The oracle is simulated (98% accurate, $0.012 and ~60 ms per call) so the
demo runs offline and free. Two incidents are scripted:
  * 30-33% of the way in, the oracle API goes down -> flagged best-guess fallbacks
  * halfway, customers start writing in a new style -> escalate, relearn, recover
"""
import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kadi import Binary, Choice, FunctionOracle, Kadi, OracleError  # noqa: E402
from kadi.server import serve  # noqa: E402

ROUTE = Choice("route_ticket", ["billing", "bug", "feature_request", "account", "spam"],
               "Which team should handle this support ticket?", target_error=0.05)
URGENT = Binary("is_urgent", "Does this ticket need a human within the hour?", target_error=0.05,
                conditional=True)  # per-label guarantee: "yes" is rare and must not hide behind the average

BANK = {
    "billing": ["I was charged twice", "refund my last invoice", "my card was billed", "wrong amount on the receipt",
                "cancel my subscription and refund", "VAT is missing from the invoice", "payment failed but money left my account"],
    "bug": ["the app crashes when I upload", "error 500 on the dashboard", "export button does nothing",
            "sync is broken since the update", "page freezes on login", "the chart shows wrong numbers", "notifications arrive twice"],
    "feature_request": ["it would be great if you added dark mode", "please support CSV import", "can you add an API for reports",
                        "would love keyboard shortcuts", "add a Slack integration please", "suggestion: bulk edit for tasks"],
    "account": ["I cannot reset my password", "change the email on my account", "two-factor code never arrives",
                "delete my account", "my account is locked", "transfer ownership to a colleague"],
    "spam": ["cheap followers best price click here", "you won a prize claim now", "crypto doubling guaranteed",
             "SEO services for your website", "hot singles in your area", "buy watches discount 90%"],
}
DRIFT = {  # new slang that appears mid-stream
    "billing": ["yo why did u take my money 2x", "where's my cash back fam"],
    "bug": ["app straight up dies lol", "this thing is bugging out fr"],
    "feature_request": ["ngl a dark theme would slap", "pls add csv thing"],
    "account": ["cant get into my acc", "locked out again smh"],
    "spam": ["DM me 4 free crypto", "promo code earn $$$ fast"],
}
URGENT_HINTS = ["asap", "production is down", "we are losing customers", "urgent", "right now", "all users affected"]
FILLER = ["hi team", "hello", "thanks", "regards", "please help", "since yesterday", "on my iphone", "for our company",
          "again", "this week", "kind of annoying", "best", "cheers", "on android", "in chrome"]


def make_ticket(rng: random.Random, drift: bool):
    label = rng.choices(list(BANK), weights=[3, 4, 2, 2, 1])[0]
    pool = BANK[label] + (DRIFT[label] * 3 if drift else [])
    urgent = rng.random() < (0.35 if label in ("bug", "account") else 0.08)
    parts = rng.sample(FILLER, 2) + [rng.choice(pool)]
    if urgent:
        parts.append(rng.choice(URGENT_HINTS))
    rng.shuffle(parts)
    if rng.random() < 0.5:
        parts.append(f"order #{rng.randint(1000, 99999)}")
    return ", ".join(parts), label, urgent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6000)
    ap.add_argument("--db", default="kadi_demo.db")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--pace", type=float, default=0.004, help="seconds between tickets")
    ap.add_argument("--no-serve", action="store_true")
    args = ap.parse_args()

    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(args.db + suffix):
            os.remove(args.db + suffix)

    rng = random.Random(7)
    truth: dict[str, tuple[str, bool]] = {}

    outage = (int(args.n * 0.30), int(args.n * 0.33))  # the frontier API goes down for a while
    progress = {"i": 0}

    def oracle(q, text, ctx):
        if outage[0] <= progress["i"] < outage[1]:
            raise OracleError("simulated 529 overloaded")
        time.sleep(0.06)  # a frontier call is slow
        label, urgent = truth[text]
        ans = label if q is ROUTE else ("yes" if urgent else "no")
        if rng.random() < 0.02:  # even the oracle is not perfect
            ans = rng.choice([o for o in q.options if o != ans])
        return ans

    kadi = Kadi(FunctionOracle(oracle, cost_per_call=0.012, name="simulated-frontier"),
                db=args.db, audit_rate=0.04, on_oracle_error="best_guess", seed=1)
    if not args.no_serve:
        serve(kadi.store, port=args.port, engine=kadi, background=True)
        print(f"Divan dashboard → http://127.0.0.1:{args.port}")

    t0 = time.time()
    for i in range(args.n):
        progress["i"] = i
        text, label, urgent = make_ticket(rng, drift=i > args.n // 2)
        truth[text] = (label, urgent)
        kadi.decide(ROUTE, text)
        kadi.decide(URGENT, text)
        if args.pace:
            time.sleep(args.pace)
        if (i + 1) % 1000 == 0:
            s = {x["question"]: x for x in kadi.stats()}
            print(f"{i + 1:>6} tickets · local {s['route_ticket']['local_rate_recent']:.0%} / "
                  f"{s['is_urgent']['local_rate_recent']:.0%} · {time.time() - t0:.0f}s")
    kadi.checkpoint()
    print("done. dashboard stays up, Ctrl+C to exit." if not args.no_serve else "done.")
    if not args.no_serve:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    kadi.close()


if __name__ == "__main__":
    main()
