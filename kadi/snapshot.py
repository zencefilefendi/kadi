"""Compact binary container for model state (stdlib only).

A snapshot is a small JSON header plus named typed arrays, zlib-compressed:

    b"KADISNAP" | u8 version | zlib( u32 header_len | header JSON | array bytes ... )

The header lists every array as [name, typecode, item_count]; array bytes
follow in that order, little-endian. Floats are stored as float32: weights do
not need float64, and it halves the size. Measured sizes and timings versus
the v0.5 JSON checkpoint are in docs/ENGINEERING.md.
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from array import array

MAGIC = b"KADISNAP"
VERSION = 1
_TYPES = {"f", "d", "q", "i", "I", "H", "B"}


def dumps(meta: dict, arrays: dict[str, array]) -> bytes:
    spec = []
    chunks = []
    for name, arr in arrays.items():
        if arr.typecode not in _TYPES:
            raise ValueError(f"unsupported array type {arr.typecode!r}")
        a = arr
        if sys.byteorder != "little":  # pragma: no cover
            a = array(arr.typecode, arr)
            a.byteswap()
        spec.append([name, arr.typecode, len(arr)])
        chunks.append(a.tobytes())
    header = json.dumps({"meta": meta, "arrays": spec}, separators=(",", ":")).encode()
    body = struct.pack("<I", len(header)) + header + b"".join(chunks)
    return MAGIC + bytes([VERSION]) + zlib.compress(body, 1)  # floats barely compress; favour speed


def loads(blob: bytes) -> tuple[dict, dict[str, array]]:
    if blob[:8] != MAGIC:
        raise ValueError("not a Kadı snapshot")
    if blob[8] != VERSION:
        raise ValueError(f"unsupported snapshot version {blob[8]}")
    body = zlib.decompress(blob[9:])
    (hlen,) = struct.unpack_from("<I", body, 0)
    header = json.loads(body[4:4 + hlen])
    pos = 4 + hlen
    arrays: dict[str, array] = {}
    for name, code, n in header["arrays"]:
        a = array(code)
        size = a.itemsize * n
        a.frombytes(body[pos:pos + size])
        if sys.byteorder != "little":  # pragma: no cover
            a.byteswap()
        arrays[name] = a
        pos += size
    if pos != len(body):
        raise ValueError("corrupt snapshot: trailing bytes")
    return header["meta"], arrays
