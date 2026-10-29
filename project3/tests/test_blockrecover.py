"""Tests for the block recovery toolkit.

    py -3 -m unittest discover -s tests        (from the project3 folder)

The tests that need Pillow (to make JPEGs) are skipped without it. The course
block set is not part of the repository; if it is placed at
tests/data/CP3-3-blockset.zip the end-to-end check on it runs too.
"""

import io
import os
import random
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from blockrecover import binfmt, blocks, classify, inflate, pdfcrypt, pdflex, streams  # noqa: E402
from blockrecover.blocks import Block  # noqa: E402
from blockrecover import jpeg  # noqa: E402

try:
    from PIL import Image
except ImportError:          # pragma: no cover
    Image = None

HERE = os.path.dirname(os.path.abspath(__file__))
COURSE_SET = os.path.join(HERE, "data", "CP3-3-blockset.zip")


class TestRC4AndKeys(unittest.TestCase):
    def test_rc4_vectors(self):
        # the classic test vectors
        self.assertEqual(pdfcrypt.rc4(b"Key", b"Plaintext").hex(), "bbf316e8d940af0ad3")
        self.assertEqual(pdfcrypt.rc4(b"Wiki", b"pedia").hex(), "1021bf0420")

    def test_literal_string(self):
        s, end = pdfcrypt.literal_string(b"(a\\(b\\)c\\101)rest", 0)
        self.assertEqual(s, b"a(b)cA")
        self.assertEqual(end, 13)

    def test_user_password_check(self):
        # build O and U for the empty password the way a writer would (R3, 128-bit)
        O = bytes(range(32))
        ID0 = bytes(16)
        sec = pdfcrypt.Security(O, b"\0" * 32, -4, ID0)
        import hashlib
        x = pdfcrypt.rc4(sec.key, hashlib.md5(pdfcrypt.PAD + ID0).digest())
        for i in range(1, 20):
            x = pdfcrypt.rc4(bytes(k ^ i for k in sec.key), x)
        self.assertTrue(pdfcrypt.Security(O, x + bytes(16), -4, ID0).ok)
        self.assertFalse(sec.ok)


class TestInflate(unittest.TestCase):
    def test_matches_zlib(self):
        rnd = random.Random(1)
        for level in (1, 6, 9):
            data = bytes(rnd.randrange(256) for _ in range(3000)) + b"the quick brown fox " * 400
            z = zlib.compress(data, level)
            inf = inflate.Inflater()
            for i in range(0, len(z), 512):                  # piece by piece, like blocks
                inf.feed(z[i:i + 512])
            self.assertTrue(inf.eof)
            self.assertEqual(bytes(inf.out), data[-len(inf.out):])

    def test_checksum_checked(self):
        z = bytearray(zlib.compress(b"hello world " * 100))
        z[-1] ^= 1
        with self.assertRaises(inflate.InflateError):
            inflate.Inflater().feed(bytes(z))

    def test_wrong_block_slips(self):
        # a wrong continuation breaks the compressor's habits far more often than the right one
        rnd = random.Random(2)
        text = b"".join(b"%d.%02d %d.%02d %s\n" % (rnd.randrange(600), rnd.randrange(100), rnd.randrange(800),
                                                    rnd.randrange(100), rnd.choice([b"m", b"l"])) for _ in range(3000))
        z = zlib.compress(text)
        self.assertGreater(len(z), 2000)
        cut = 600
        base = inflate.Inflater().feed(z[:cut])
        right = base.copy().feed(z[cut:cut + 512])
        wrongs = []
        for _ in range(20):
            try:
                w = base.copy().feed(bytes(rnd.randrange(256) for _ in range(512)))
                wrongs.append(w.slips - base.slips)
            except inflate.InflateError:
                wrongs.append(99)
        self.assertLessEqual(right.slips - base.slips, 2)
        self.assertGreater(sum(wrongs) / len(wrongs), 4)


class TestPDFGrammar(unittest.TestCase):
    def test_good_content_stream(self):
        bad, total, _tail = pdflex.check(b"q 1 0 0 1 72 720 cm BT /F1 12 Tf (Hi) Tj ET Q\n0.5 g 0 0 10 10 re f\n")
        self.assertEqual(bad, 0)
        self.assertGreater(total, 40)

    def test_wrong_operand_count(self):
        bad, _total, _tail = pdflex.check(b"1 2 3 m 4 5 l\n")
        self.assertGreater(bad, 0)

    def test_carry_across_blocks(self):
        b1, t1, tail = pdflex.check(b"BT /F1 12 Tf (Hel")
        b2, t2, _ = pdflex.check(b"lo) Tj ET\n", tail)
        self.assertEqual(b1 + b2, 0)

    def test_object_ok(self):
        self.assertGreater(pdflex.object_ok(b"<</Length 10/Filter/FlateDecode>>stream\r\n"), 0)
        self.assertEqual(pdflex.object_ok(b"<</Length 10/Filter/Fla"), -1)
        self.assertEqual(pdflex.object_ok(b"<</Length/Filter 3>>stream"), -1)


class TestFormats(unittest.TestCase):
    def test_der(self):
        cert = bytes.fromhex("3009020101" "0c0441424344")   # SEQUENCE { INTEGER 1, UTF8String "ABCD" }
        self.assertEqual(binfmt.der(cert, 0, len(cert)), (0, len(cert)))
        broken = bytes.fromhex("3009020101" "0cff41424344")
        self.assertGreater(binfmt.der(broken, 0, len(broken))[0], 0)

    def test_classify_basics(self):
        self.assertEqual(classify.guess(Block("a", b"%PDF-1.4" + bytes(504), 0))[0], "PDF")
        self.assertEqual(classify.guess(Block("b", bytes.fromhex("D0CF11E0A1B11AE1") + bytes(504), 0))[0], "Word")
        self.assertEqual(classify.guess(Block("c", b"Hello there, this is plain text. " * 16, 0))[0], "Word")


@unittest.skipIf(Image is None, "Pillow is needed to make test JPEGs")
class TestJPEG(unittest.TestCase):
    def picture(self, **kw):
        im = Image.radial_gradient("L").resize((160, 96)).convert("RGB")
        b = io.BytesIO()
        im.save(b, "JPEG", quality=85, **kw)
        return b.getvalue()

    def decode_all(self, data):
        h = jpeg.Header(data)
        dec = jpeg.Decoder(h)
        st = jpeg.State(len(h.scan))
        body = data[h.scan_start:]
        for i in range(0, len(body), 512):
            _d, info = dec.run(st, body[i:i + 512], final=i + 512 >= len(body))
            self.assertIsNone(info["error"])
        return st

    def test_decodes_to_the_end(self):
        for kw in ({}, {"subsampling": 0}, {"restart_marker_blocks": 3}):
            self.assertTrue(self.decode_all(self.picture(**kw)).done, kw)

    def test_reorders_a_small_picture(self):
        from blockrecover import jpegfile
        data = self.picture()
        data += b"\0" * (-len(data) % 512)
        bl = [Block("B%02d" % i, data[512 * i:512 * i + 512], i) for i in range(len(data) // 512)]
        shuffled = bl[:]
        random.Random(3).shuffle(shuffled)
        L = jpegfile.rebuild(shuffled)
        self.assertEqual([b.name for b in L.at], [b.name for b in bl])


@unittest.skipUnless(os.path.exists(COURSE_SET), "course block set not present")
class TestCourseSet(unittest.TestCase):
    def test_pdf_and_word(self):
        from blockrecover import recover
        R = recover.run(COURSE_SET, stages=("PDF", "Word"))
        kinds = {f["kind"]: f for f in R.files}
        self.assertTrue(kinds["PDF"]["ok"])
        self.assertTrue(kinds["Word"]["ok"])
        self.assertEqual(sum(1 for b in kinds["PDF"]["layout"].at if b), 271)
        self.assertEqual(sum(1 for b in kinds["Word"]["layout"].at if b), 284)


if __name__ == "__main__":
    unittest.main()
