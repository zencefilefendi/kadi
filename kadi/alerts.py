"""Alert delivery. Payloads are Slack/Discord/Teams-compatible ({"text": ...})."""
from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlparse


def webhook(url: str, timeout: float = 5.0):
    p = urlparse(url)
    if p.scheme != "https" and p.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("alert webhook must be https (or http on localhost)")

    def send(alert: dict) -> None:
        text = (f"⚖️ Kadı · {alert['question']}: {alert['kind']} — disagreement "
                f"{alert['disagreement']:.1%} (≥{alert['lower_bound']:.1%} at 95%) vs target "
                f"{alert['target_error']:.1%}. {alert['action']}.")
        body = json.dumps({"text": text, "content": text, "kadi": alert}).encode()
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=timeout).close()

    return send
