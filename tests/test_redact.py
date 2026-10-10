import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kadi.redact import Redactor, DEFAULT_REDACTOR, Finding  # noqa: E402


def make_tckn(first9: str) -> str:
    n = [int(c) for c in first9]
    d10 = ((n[0] + n[2] + n[4] + n[6] + n[8]) * 7 - (n[1] + n[3] + n[5] + n[7])) % 10
    d11 = (sum(n) + d10) % 10
    return first9 + str(d10) + str(d11)


def luhn_complete(prefix: str) -> str:
    """Append a check digit so that prefix+digit is Luhn-valid."""
    for d in "0123456789":
        cand = prefix + d
        total = 0
        for i, c in enumerate(reversed(cand)):
            v = int(c)
            if i % 2:
                v *= 2
                if v > 9:
                    v -= 9
            total += v
        if total % 10 == 0:
            return cand
    raise AssertionError


R = DEFAULT_REDACTOR


def kinds(text, redactor=R):
    return [f.kind for f in redactor.find(text)]


class TestEmail(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(R("mail: ali.veli+test@example.co.uk."), "mail: <EMAIL>.")
        self.assertEqual(R("ayşe@örnek.com.tr yazın"), "<EMAIL> yazın")

    def test_negative(self):
        for t in ["user@localhost", "a@b", "foo@@bar.com", "@handle", "x..y@example.com"]:
            self.assertNotIn("EMAIL", kinds(t), t)


class TestPhone(unittest.TestCase):
    def test_turkish_formats(self):
        for p in [
            "+90 532 123 45 67",
            "+905321234567",
            "+90 (532) 123-45-67",
            "0532 123 45 67",
            "05321234567",
            "0 (532) 123 45 67",
            "0532.123.45.67",
            "0090 532 123 4567",
            "0212 555 12 34",
            "532 123 45 67",
        ]:
            self.assertEqual(R(f"Tel: {p}."), "Tel: <PHONE>.", p)

    def test_international(self):
        for p in ["+44 20 7946 0958", "+1 (415) 555-2671", "+4915112345678"]:
            self.assertEqual(R(f"call {p} now"), "call <PHONE> now", p)

    def test_negative(self):
        for t in [
            "Sipariş #48213 hazır",
            "Yıl 2026 oldu",
            "kod 12345",
            "+12345",
            "3+4=7",
            "5321234567",  # bare, no separators
            "fiyat 1.250.000 TL",
        ]:
            self.assertEqual(R(t), t, t)


class TestTCKN(unittest.TestCase):
    def test_valid(self):
        t = make_tckn("123456789")
        self.assertEqual(R(f"TC kimlik no: {t}"), "TC kimlik no: <TCKN>")
        t2 = make_tckn("987654321")
        self.assertEqual(kinds(f"{t2}"), ["TCKN"])

    def test_invalid(self):
        valid = make_tckn("123456789")
        bad_last = valid[:10] + str((int(valid[10]) + 1) % 10)
        bad_10th = valid[:9] + str((int(valid[9]) + 1) % 10) + valid[10]
        for t in [bad_last, bad_10th, "0" + valid[1:], valid + "1", "1234567890"]:
            self.assertNotIn("TCKN", kinds(t), t)


class TestIBAN(unittest.TestCase):
    VALID = "TR33 0006 1005 1978 6457 8413 26"

    def test_valid_spaced_and_compact(self):
        self.assertEqual(R(f"IBAN: {self.VALID} TL"), "IBAN: <IBAN> TL")
        self.assertEqual(R(self.VALID.replace(" ", "")), "<IBAN>")
        self.assertEqual(R("DE89 3704 0044 0532 0130 00"), "<IBAN>")
        self.assertEqual(R("GB82WEST12345698765432"), "<IBAN>")

    def test_wrong_check_digit(self):
        bad = "TR34 0006 1005 1978 6457 8413 26"
        self.assertNotIn("IBAN", kinds(bad))
        bad2 = self.VALID[:-1] + "7"
        self.assertNotIn("IBAN", kinds(bad2))


class TestCard(unittest.TestCase):
    def test_valid(self):
        for c in [
            "4111 1111 1111 1111",
            "4111-1111-1111-1111",
            "5555555555554444",
            "2223 0031 2200 3222",
            "3782 822463 10005",
            "6011 1111 1111 1117",
            luhn_complete("979200000000000"),  # Troy
        ]:
            self.assertEqual(R(f"kart: {c}."), "kart: <CARD>.", c)

    def test_invalid(self):
        for c in [
            "4111 1111 1111 1112",  # Luhn fail
            luhn_complete("123456789012345"),  # Luhn ok, unknown IIN
            "4111 11 11 1111 1111",  # weird grouping
            "1234 5678",
        ]:
            self.assertNotIn("CARD", kinds(c), c)


class TestIP(unittest.TestCase):
    def test_ipv4(self):
        self.assertEqual(R("sunucu 192.168.1.10'da"), "sunucu <IPV4>'da")
        self.assertEqual(R("ip=8.8.8.8."), "ip=<IPV4>.")
        for t in ["10.0.0.256", "1.2.3", "v1.2.3.4.5", "01.02.03.04"]:
            self.assertNotIn("IPV4", kinds(t), t)

    def test_ipv6(self):
        self.assertEqual(R("addr 2001:db8::8a2e:370:7334 ok"), "addr <IPV6> ok")
        self.assertEqual(R("fe80::1."), "<IPV6>.")
        self.assertEqual(R("::ffff:192.0.2.1"), "<IPV6>")
        for t in ["12:30:45", "std::map", "a:b", "::", "00:1A:2B:3C:4D:5E"]:
            self.assertNotIn("IPV6", kinds(t), t)


class TestSecret(unittest.TestCase):
    def test_positive(self):
        samples = [
            "sk-" + "a1B2" * 6,
            "sk-ant-api03-" + "x" * 30,
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_" + "A1b2" * 9,
            "xoxb-1234567890-abcdefghij",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "AIza" + "S" * 35,
        ]
        for s in samples:
            self.assertEqual(R(f"key={s} end"), "key=<SECRET> end", s)

    def test_bearer_only_token(self):
        self.assertEqual(
            R("Authorization: Bearer abc123DEF456ghi789"),
            "Authorization: Bearer <SECRET>",
        )

    def test_negative(self):
        for t in [
            "sk-short",
            "task-abcdefghijklmnopqrstuvwxyz",
            "AKIA123",
            "ghp_short",
            "Bearer authentication is used",
            "eyJ alone",
        ]:
            self.assertNotIn("SECRET", kinds(t), t)


class TestURLCredentials(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(
            R("db: postgres://admin:s3cr3t@db.example.com:5432/app"),
            "db: postgres://<URL_CREDENTIALS>@db.example.com:5432/app",
        )

    def test_negative(self):
        t = "https://example.com/path?a=b"
        self.assertEqual(R(t), t)


class TestGeneral(unittest.TestCase):
    def test_turkish_sentence_preserved(self):
        text = ("Merhaba, ben Çağrı Öztürk; şikâyetim için 0532 123 45 67 numarasından "
                "veya çağrı.öztürk@örnek.com.tr adresinden ulaşabilirsiniz. Sipariş #48213, 2026 yılı. Teşekkürler ğüşıöç!")
        expected = ("Merhaba, ben Çağrı Öztürk; şikâyetim için <PHONE> numarasından "
                    "veya <EMAIL> adresinden ulaşabilirsiniz. Sipariş #48213, 2026 yılı. Teşekkürler ğüşıöç!")
        self.assertEqual(R(text), expected)

    def test_findings_sorted_non_overlapping(self):
        text = "a@b.com 0532 123 45 67 TR33 0006 1005 1978 6457 8413 26 https://u:p@h.io"
        fs = R.find(text)
        self.assertTrue(all(isinstance(f, Finding) for f in fs))
        self.assertEqual([f.kind for f in fs], ["EMAIL", "PHONE", "IBAN", "URL_CREDENTIALS"])
        for a, b in zip(fs, fs[1:]):
            self.assertLessEqual(a.end, b.start)
        self.assertEqual(text[fs[0].start:fs[0].end], "a@b.com")

    def test_url_credentials_beats_email(self):
        self.assertEqual(R("https://user:pass@host.com"), "https://<URL_CREDENTIALS>@host.com")

    def test_idempotent(self):
        texts = [
            "ali@x.com, +90 532 123 45 67, TR33 0006 1005 1978 6457 8413 26, 4111111111111111",
            "Bearer abc123DEF456ghi789 https://u:p@h.io 10.0.0.1 fe80::1 " + make_tckn("123456789"),
            "<EMAIL> <PHONE> already",
        ]
        for t in texts:
            once = R(t)
            self.assertEqual(R(once), once)
        extra = Redactor(extra_patterns={"WORD": r"[A-Z]{3,}"})
        once = extra("ABC and ali@x.com")
        self.assertEqual(once, "<WORD> and <EMAIL>")
        self.assertEqual(extra(once), once)

    def test_kinds_filter(self):
        r = Redactor(kinds=["EMAIL"])
        self.assertEqual(r("ali@x.com 0532 123 45 67"), "<EMAIL> 0532 123 45 67")
        self.assertEqual(r.redact("ali@x.com"), r("ali@x.com"))
        with self.assertRaises(ValueError):
            Redactor(kinds=["NOPE"])

    def test_extra_patterns(self):
        r = Redactor(extra_patterns={"ORDER": r"#\d{5}", "TOKEN": r"token=(?P<redact>\w+)"})
        self.assertEqual(r("Sipariş #48213 token=abc123"), "Sipariş <ORDER> token=<TOKEN>")
        r2 = Redactor(kinds=["ORDER"], extra_patterns={"ORDER": r"#\d{5}"})
        self.assertEqual(r2("#48213 ali@x.com"), "<ORDER> ali@x.com")

    def test_empty_and_plain(self):
        self.assertEqual(R(""), "")
        self.assertEqual(R.find(""), [])
        self.assertEqual(R("Bugün hava çok güzel."), "Bugün hava çok güzel.")

    def test_performance(self):
        chunk = "Merhaba dünya 2026 #48213 sipariş 12.5 TL ali@x.com 0532 123 45 67 ğüşıöç. "
        text = chunk * 2000  # ~150 KB
        t0 = time.perf_counter()
        out = R(text)
        self.assertLess(time.perf_counter() - t0, 5.0)
        self.assertEqual(out.count("<EMAIL>"), 2000)
        self.assertEqual(out.count("<PHONE>"), 2000)


if __name__ == "__main__":
    unittest.main()
