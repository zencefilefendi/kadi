"""Public intent-classification datasets, downloaded on demand and pinned by SHA-256.

Nothing is redistributed with Kadı: files are fetched from the authors' own
repositories into a local cache (default ~/.cache/kadi-bench, override with
KADI_BENCH_CACHE) and verified before use.

  banking77  Casanueva et al. (2020), "Efficient Intent Detection with Dual
             Sentence Encoders". 77 fine-grained banking intents. CC-BY-4.0.
  clinc150   Larson et al. (2019), "An Evaluation Dataset for Intent
             Classification and Out-of-Scope Prediction". 150 intents across
             10 domains (in-scope part only).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import urllib.request

SOURCES = {
    "banking77": [
        ("train.csv", "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/train.csv",
         "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b"),
        ("test.csv", "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv",
         "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d"),
    ],
    "clinc150": [
        ("data_full.json", "https://raw.githubusercontent.com/clinc/oos-eval/master/data/data_full.json",
         "36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0"),
    ],
}


def cache_dir() -> str:
    d = os.environ.get("KADI_BENCH_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "kadi-bench")
    os.makedirs(d, exist_ok=True)
    return d


def _fetch(name: str, fname: str, url: str, sha256: str | None) -> bytes:
    path = os.path.join(cache_dir(), f"{name}-{fname}")
    if not os.path.exists(path):
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    with open(path, "rb") as f:
        data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    if sha256 and digest != sha256:
        raise RuntimeError(f"{path}: SHA-256 {digest} does not match pinned {sha256}; delete it and retry")
    return data


def load(name: str) -> list[tuple[str, str]]:
    """Return [(text, label), ...] in the dataset's original order."""
    files = {fname: _fetch(name, fname, url, sha) for fname, url, sha in SOURCES[name]}
    rows: list[tuple[str, str]] = []
    if name == "banking77":
        for fname in ("train.csv", "test.csv"):
            for r in csv.DictReader(io.StringIO(files[fname].decode("utf-8"))):
                rows.append((r["text"], r["category"]))
    elif name == "clinc150":
        d = json.loads(files["data_full.json"])
        for split in ("train", "val", "test"):
            rows.extend((t, lab) for t, lab in d[split])
    else:
        raise KeyError(name)
    return rows


def digests() -> dict[str, str]:
    out = {}
    for name, files in SOURCES.items():
        for fname, url, sha in files:
            out[f"{name}/{fname}"] = hashlib.sha256(_fetch(name, fname, url, sha)).hexdigest()
    return out
