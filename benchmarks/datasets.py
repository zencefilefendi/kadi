"""Public intent-classification datasets, downloaded on demand and pinned by SHA-256.

Nothing is redistributed with Kadı: files are fetched from the authors' own
repositories into a local cache (default ~/.cache/kadi-bench, override with
KADI_BENCH_CACHE) and verified before use.

  banking77  Casanueva et al. (2020), "Efficient Intent Detection with Dual
             Sentence Encoders". 77 fine-grained banking intents. CC-BY-4.0.
  clinc150   Larson et al. (2019), "An Evaluation Dataset for Intent
             Classification and Out-of-Scope Prediction". 150 intents across
             10 domains (in-scope part only).
  massive_tr FitzGerald et al. (2022), "MASSIVE: A 1M-Example Multilingual
             Natural Language Understanding Dataset". Turkish (tr-TR) part,
             60 intents, all partitions. CC BY 4.0.
  offenseval_tr  Coltekin (2020), "A Corpus of Turkish Offensive Language on
             Social Media" (OffensEval 2020, subtask A: OFF / NOT). CC BY.
  hatespeech_en  Kennedy et al. (2020), "Constructing interval variables via
             faceted Rasch measurement and multitask deep learning: a hate
             speech application" (UC Berkeley D-Lab Measuring Hate Speech).
             One label per comment: "hateful" if the mean faceted-Rasch
             hate_speech_score is > 0.5 (the dataset's suggested cut-off),
             else "not_hateful". CC BY 4.0. Needs pyarrow to read.
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
    "massive_tr": [
        ("amazon-massive-dataset-1.1.tar.gz",
         "https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.1.tar.gz",
         "4cba5faa11c71437928e17cb1b9b3d8b8e727e7ea363a3a9a8045e19c0491577"),
    ],
    "offenseval_tr": [
        ("offenseval2020-turkish.zip", "https://coltekin.github.io/offensive-turkish/offenseval2020-turkish.zip",
         "7977e96255dbc9b8d14893f1b14cbe3dec53c70358503c062c5a59720ec9c2f2"),
    ],
    "hatespeech_en": [
        ("measuring-hate-speech.parquet",
         "https://huggingface.co/datasets/ucberkeley-dlab/measuring-hate-speech/resolve/main/measuring-hate-speech.parquet",
         "6819525ce61bc24344df9fc3f7bf48270b31038273cc27c67fc225b51433b0e1"),
    ],
}
LANGUAGE = {"banking77": "en", "clinc150": "en", "massive_tr": "tr", "offenseval_tr": "tr", "hatespeech_en": "en"}


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
    elif name == "massive_tr":
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(files["amazon-massive-dataset-1.1.tar.gz"])) as t:
            for line in t.extractfile("1.1/data/tr-TR.jsonl").read().decode("utf-8").splitlines():
                r = json.loads(line)
                rows.append((r["utt"], r["intent"]))
    elif name == "offenseval_tr":
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(files["offenseval2020-turkish.zip"]))
        base = "offenseval2020-turkish/"
        train = z.read(base + "offenseval-tr-training-v1/offenseval-tr-training-v1.tsv").decode("utf-8")
        for r in csv.DictReader(io.StringIO(train), delimiter="\t", quoting=csv.QUOTE_NONE):
            rows.append((r["tweet"], r["subtask_a"]))
        test = z.read(base + "offenseval-tr-testset-v1/offenseval-tr-testset-v1.tsv").decode("utf-8")
        gold = dict(line.split(",", 1) for line in
                    z.read(base + "offenseval-tr-testset-v1/offenseval-tr-labela-v1.tsv").decode("utf-8").split())
        for r in csv.DictReader(io.StringIO(test), delimiter="\t", quoting=csv.QUOTE_NONE):
            rows.append((r["tweet"], gold[r["id"]]))
        rows = [(t, y) for t, y in rows if t and t.strip()]
    elif name == "hatespeech_en":
        try:
            import pyarrow.parquet as pq
        except ImportError as e:  # pragma: no cover
            raise ImportError("hatespeech_en needs pyarrow (pip install pyarrow)") from e
        t = pq.read_table(io.BytesIO(files["measuring-hate-speech.parquet"]),
                          columns=["comment_id", "text", "hate_speech_score"]).to_pydict()
        acc: dict = {}
        for cid, text, score in zip(t["comment_id"], t["text"], t["hate_speech_score"]):
            a = acc.setdefault(cid, [text, 0.0, 0])
            a[1] += score
            a[2] += 1
        for cid in sorted(acc):
            text, total, n = acc[cid]
            if text and text.strip():
                rows.append((text, "hateful" if total / n > 0.5 else "not_hateful"))
    else:
        raise KeyError(name)
    return rows


def digests(names=None) -> dict[str, str]:
    """SHA-256 of the raw files of the given datasets (all if None). Downloads
    only what is asked for."""
    out = {}
    for name, files in SOURCES.items():
        if names is not None and name not in names:
            continue
        for fname, url, sha in files:
            out[f"{name}/{fname}"] = hashlib.sha256(_fetch(name, fname, url, sha)).hexdigest()
    return out
