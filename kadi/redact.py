"""PII / secret redaction for Kadı (KVKK / GDPR friendly).

Text is redacted

* before previews are stored in the audit DB,
* optionally before it is sent to an external LLM oracle,
* before featurization, so the local model learns ``<EMAIL>`` rather than a
  specific address.

Every detector *validates* its candidates (checksums, octet ranges, IIN
prefixes, ...) instead of trusting a regex alone, to keep false positives low.
All patterns are precompiled; matching is linear-ish in the input length.

Usage::

    from kadi.redact import DEFAULT_REDACTOR
    DEFAULT_REDACTOR("Bana ali@örnek.com veya 0532 123 45 67 üzerinden ulaşın")
    # -> 'Bana <EMAIL> veya <PHONE> üzerinden ulaşın'

Redaction is idempotent: ``redact(redact(x)) == redact(x)``.
"""

from __future__ import annotations

import bisect
import ipaddress
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

__all__ = ["Finding", "Redactor", "DEFAULT_REDACTOR", "BUILTIN_KINDS"]


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int


# Higher-priority kinds come first. When two candidates overlap, the one with
# the higher priority wins; ties are broken by length (longer wins), then by
# position. Extra (user) patterns rank below all built-ins.
BUILTIN_KINDS: tuple[str, ...] = (
    "URL_CREDENTIALS",
    "SECRET",
    "IBAN",
    "CARD",
    "EMAIL",
    "TCKN",
    "IPV6",
    "IPV4",
    "PHONE",
)

_KIND_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
# Already-redacted placeholders such as "<EMAIL>"; never re-redacted.
_PLACEHOLDER_RE = re.compile(r"<[A-Za-z][A-Za-z0-9_]*>")

Span = tuple[int, int]
Detector = Callable[[str], Iterator[Span]]


# --------------------------------------------------------------------------
# validators
# --------------------------------------------------------------------------

def _tckn_valid(d: str) -> bool:
    if len(d) != 11 or not d.isdigit() or d[0] == "0":
        return False
    n = [int(c) for c in d]
    d10 = ((n[0] + n[2] + n[4] + n[6] + n[8]) * 7 - (n[1] + n[3] + n[5] + n[7])) % 10
    if d10 != n[9]:
        return False
    return sum(n[:10]) % 10 == n[10]


def _luhn_valid(d: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(d)):
        v = ord(c) - 48
        if i % 2 == 1:
            v *= 2
            if v > 9:
                v -= 9
        total += v
    return total % 10 == 0


def _card_iin_ok(d: str) -> bool:
    n = len(d)
    if d[0] == "4":  # Visa
        return n in (13, 16, 19)
    p2 = int(d[:2])
    p4 = int(d[:4])
    if 51 <= p2 <= 55 or 2221 <= p4 <= 2720:  # Mastercard
        return n == 16
    if p2 in (34, 37):  # Amex
        return n == 15
    if p4 == 9792:  # Troy
        return n == 16
    if p4 == 6011 or p2 == 65:  # Discover
        return 16 <= n <= 19
    return False


def _iban_valid(compact: str) -> bool:
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    num = "".join(str(int(c, 36)) for c in rearranged)
    return int(num) % 97 == 1


# ISO 13616 registry lengths (SWIFT IBAN registry + common partial adopters).
_IBAN_LENGTHS: dict[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BI": 27, "BR": 29, "BY": 28, "CH": 21, "CR": 22,
    "CY": 28, "CZ": 24, "DE": 22, "DJ": 27, "DK": 18, "DO": 28, "EE": 20,
    "EG": 29, "ES": 24, "FI": 18, "FK": 18, "FO": 18, "FR": 27, "GB": 22,
    "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30,
    "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "LY": 25, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MN": 20, "MR": 27,
    "MT": 31, "MU": 30, "NI": 28, "NL": 18, "NO": 15, "OM": 23, "PK": 24,
    "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "RU": 33,
    "SA": 24, "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24, "SM": 27,
    "SO": 23, "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29,
    "VA": 22, "VG": 24, "XK": 20, "YE": 30,
}


# --------------------------------------------------------------------------
# detectors (each yields (start, end) spans of validated findings)
# --------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"(?<![\w.%+-])"
    r"[\w%+-](?:[\w.%+-]{0,63})"
    r"@"
    r"(?:[^\W_](?:[\w-]{0,61}[^\W_])?\.)+"
    r"[^\W\d_]{2,24}"
    r"(?![\w-])"
)


def _detect_email(text: str) -> Iterator[Span]:
    for m in _EMAIL_RE.finditer(text):
        local = m.group().split("@", 1)[0]
        if ".." in local or local.endswith("."):
            continue
        yield m.span()


_SEP = r"[ .-]"
_PHONE_END = r"(?![\w]|[.-]\d)"
_PHONE_TR_RE = re.compile(
    r"(?<![\w+])(?:"
    # +90 / 0090 prefix, optional (0) trunk, optional parens around area code
    r"(?:\+|00)[ ]?90" + _SEP + r"?(?:\(0?[ ]?[2-58]\d{2}\)|0?[ ]?[2-58]\d{2})"
    r"|"
    # national trunk prefix 0
    r"0[ ]?(?:\([2-58]\d{2}\)|[2-58]\d{2})"
    r")"
    + _SEP + r"?\d{3}" + _SEP + r"?\d{2}" + _SEP + r"?\d{2}"
    + _PHONE_END
)
# Bare mobile number without a prefix: only accepted with consistent separators.
_PHONE_TR_BARE_RE = re.compile(
    r"(?<![\w+])5\d{2}([ .-])\d{3}\1\d{2}\1\d{2}" + _PHONE_END
)
# Generic E.164: "+" country code then 8-15 digits in total, with separators.
_PHONE_INTL_RE = re.compile(
    r"(?<![\w+])\+[ ]?\(?[1-9](?:[ .()-]{0,2}\d){7,14}" + _PHONE_END
)


def _detect_phone(text: str) -> Iterator[Span]:
    for m in _PHONE_TR_RE.finditer(text):
        yield m.span()
    for m in _PHONE_TR_BARE_RE.finditer(text):
        yield m.span()
    for m in _PHONE_INTL_RE.finditer(text):
        s = m.group()
        if s.count("(") != s.count(")"):
            continue
        digits = sum(c.isdigit() for c in s)
        if 8 <= digits <= 15:
            yield m.span()


_TCKN_RE = re.compile(r"(?<![\w])[1-9]\d{10}(?![\w])")


def _detect_tckn(text: str) -> Iterator[Span]:
    for m in _TCKN_RE.finditer(text):
        if _tckn_valid(m.group()):
            yield m.span()


_IBAN_RE = re.compile(r"(?<![\w])[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}")


def _detect_iban(text: str) -> Iterator[Span]:
    for m in _IBAN_RE.finditer(text):
        s = m.group()
        start = m.start()
        country = s[:2]
        expected = _IBAN_LENGTHS.get(country)
        # positions (in s) of each alphanumeric char
        idx = [i for i, c in enumerate(s) if c != " "]
        lengths = [expected] if expected else range(min(len(idx), 34), 14, -1)
        for n in lengths:
            if n is None or n > len(idx):
                continue
            end_in_s = idx[n - 1] + 1
            # must not stop in the middle of an alphanumeric run
            nxt = start + end_in_s
            if nxt < len(text) and text[nxt].isalnum():
                continue
            chunk = s[:end_in_s]
            if " " in chunk:
                # spaces only between groups of four
                if any(c == " " and len(chunk[:i].replace(" ", "")) % 4
                       for i, c in enumerate(chunk)):
                    continue
                if "  " in chunk:
                    continue
            compact = chunk.replace(" ", "")
            if _iban_valid(compact):
                yield (start, start + end_in_s)
                break


_CARD_RE = re.compile(r"(?<![\w.+-])\d(?:[ -]?\d){12,18}(?![\w])")


def _detect_card(text: str) -> Iterator[Span]:
    for m in _CARD_RE.finditer(text):
        s = m.group()
        has_space, has_dash = " " in s, "-" in s
        if has_space and has_dash:
            continue
        if has_space or has_dash:
            groups = s.split(" " if has_space else "-")
            if any(not 3 <= len(g) <= 8 for g in groups):
                continue
        d = s.replace(" ", "").replace("-", "")
        if _card_iin_ok(d) and _luhn_valid(d):
            yield m.span()


_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)")


def _detect_ipv4(text: str) -> Iterator[Span]:
    for m in _IPV4_RE.finditer(text):
        parts = m.group().split(".")
        if all(int(p) <= 255 and (p == "0" or not p.startswith("0")) for p in parts):
            yield m.span()


_IPV6_RE = re.compile(
    r"(?<![\w:.])"
    r"(?:[0-9A-Fa-f]{0,4}:){2,7}"
    r"(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f]{0,4})"
    r"(?![\w:]|\.\w)"
)


def _detect_ipv6(text: str) -> Iterator[Span]:
    for m in _IPV6_RE.finditer(text):
        s = m.group()
        if not any(c not in ":." for c in s):
            continue  # bare "::"
        try:
            ipaddress.IPv6Address(s)
        except ValueError:
            continue
        yield m.span()


_SECRET_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![\w-])sk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![\w-])eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])"),
)
_BEARER_RE = re.compile(r"\b[Bb][Ee][Aa][Rr][Ee][Rr][ \t]+([A-Za-z0-9\-._~+/]{12,}=*)")


def _detect_secret(text: str) -> Iterator[Span]:
    for rx in _SECRET_RES:
        for m in rx.finditer(text):
            yield m.span()
    for m in _BEARER_RE.finditer(text):
        tok = m.group(1)
        # avoid prose like "Bearer authentication": need a non-letter or length
        if len(tok) >= 24 or not tok.isalpha():
            yield m.span(1)


_URL_CRED_RE = re.compile(
    r"(?<![\w+.-])[A-Za-z][A-Za-z0-9+.-]*://([^\s:/?#@<>]+:[^\s/?#@<>]+)@"
)


def _detect_url_credentials(text: str) -> Iterator[Span]:
    for m in _URL_CRED_RE.finditer(text):
        yield m.span(1)


_BUILTIN_DETECTORS: dict[str, Detector] = {
    "URL_CREDENTIALS": _detect_url_credentials,
    "SECRET": _detect_secret,
    "IBAN": _detect_iban,
    "CARD": _detect_card,
    "EMAIL": _detect_email,
    "TCKN": _detect_tckn,
    "IPV6": _detect_ipv6,
    "IPV4": _detect_ipv4,
    "PHONE": _detect_phone,
}


# --------------------------------------------------------------------------
# Redactor
# --------------------------------------------------------------------------

class Redactor:
    """Detects and replaces PII/secrets with ``<KIND>`` placeholders.

    ``kinds`` restricts which built-in detectors run (default: all of
    :data:`BUILTIN_KINDS`). ``extra_patterns`` maps a kind name to a regex;
    the whole match is redacted, or only the named group ``redact`` if the
    pattern defines one. Extra patterns always run and rank below built-ins
    when overlaps are resolved.
    """

    def __init__(
        self,
        kinds: Iterable[str] | None = None,
        extra_patterns: dict[str, str] | None = None,
    ):
        extra_patterns = dict(extra_patterns or {})
        for name in extra_patterns:
            if not _KIND_NAME_RE.match(name):
                raise ValueError(f"invalid kind name for extra pattern: {name!r}")
        if kinds is None:
            selected = list(BUILTIN_KINDS)
        else:
            requested = {k.upper() for k in kinds}
            unknown = requested - set(BUILTIN_KINDS) - set(extra_patterns)
            if unknown:
                raise ValueError(f"unknown redaction kinds: {sorted(unknown)}")
            selected = [k for k in BUILTIN_KINDS if k in requested]

        self.kinds: tuple[str, ...] = tuple(selected) + tuple(
            k for k in extra_patterns if k not in selected
        )
        self._detectors: list[tuple[int, str, Detector]] = [
            (rank, k, _BUILTIN_DETECTORS[k]) for rank, k in enumerate(selected)
        ]
        base = len(BUILTIN_KINDS)
        for i, (name, pattern) in enumerate(extra_patterns.items()):
            self._detectors.append((base + i, name, self._make_extra(re.compile(pattern))))

    @staticmethod
    def _make_extra(rx: re.Pattern[str]) -> Detector:
        group = "redact" if "redact" in rx.groupindex else 0

        def detect(text: str) -> Iterator[Span]:
            for m in rx.finditer(text):
                s, e = m.span(group)
                if s >= 0 and e > s:
                    yield (s, e)

        return detect

    def find(self, text: str) -> list[Finding]:
        if not text:
            return []
        placeholders = [m.span() for m in _PLACEHOLDER_RE.finditer(text)]
        ph_starts = [s for s, _ in placeholders]

        def in_placeholder(s: int, e: int) -> bool:
            i = bisect.bisect_right(ph_starts, e - 1) - 1
            return i >= 0 and placeholders[i][1] > s

        candidates: list[tuple[int, int, int, str]] = []  # rank, start, end, kind
        for rank, kind, detect in self._detectors:
            for s, e in detect(text):
                if e > s and not (placeholders and in_placeholder(s, e)):
                    candidates.append((rank, s, e, kind))

        # priority first, then longer, then earlier
        candidates.sort(key=lambda c: (c[0], -(c[2] - c[1]), c[1]))
        starts: list[int] = []
        chosen: list[tuple[int, int, str]] = []
        for _, s, e, kind in candidates:
            i = bisect.bisect_left(starts, s)
            if i > 0 and chosen[i - 1][1] > s:
                continue
            if i < len(chosen) and chosen[i][0] < e:
                continue
            starts.insert(i, s)
            chosen.insert(i, (s, e, kind))
        return [Finding(kind, s, e) for s, e, kind in chosen]

    def redact(self, text: str) -> str:
        findings = self.find(text)
        if not findings:
            return text
        out: list[str] = []
        pos = 0
        for f in findings:
            out.append(text[pos:f.start])
            out.append(f"<{f.kind}>")
            pos = f.end
        out.append(text[pos:])
        return "".join(out)

    __call__ = redact

    def __repr__(self) -> str:
        return f"Redactor(kinds={list(self.kinds)!r})"


DEFAULT_REDACTOR = Redactor()
