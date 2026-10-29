"""PDF Standard Security Handler, revisions 2 and 3 (40- to 128-bit RC4).

A PDF that only restricts printing or copying is encrypted with a key anyone can
derive: the "user" password is empty. The key turns each stream's random-looking
bytes back into compressed data, which is what lets the reconstruction check each
candidate block by decompressing it. (ISO 32000-1, 7.6.3: Algorithms 2, 4, 5.)
"""

import hashlib

PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 255
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray(len(data))
    for n, c in enumerate(data):
        i = (i + 1) & 255
        j = (j + S[i]) & 255
        S[i], S[j] = S[j], S[i]
        out[n] = c ^ S[(S[i] + S[j]) & 255]
    return bytes(out)


def literal_string(b, i):
    """Read the PDF literal string that starts at b[i] == '(' -> (bytes, index after it)."""
    if b[i:i + 1] != b"(":
        raise ValueError("not a literal string")
    i += 1
    out, depth = bytearray(), 1
    esc = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
    while i < len(b):
        c = b[i]
        if c == 0x5C:
            n = b[i + 1]
            if n in esc:
                out.append(esc[n])
                i += 2
            elif 48 <= n <= 55:
                k, digits = i + 1, b""
                while k < i + 4 and k < len(b) and 48 <= b[k] <= 55:
                    digits += bytes([b[k]])
                    k += 1
                out.append(int(digits, 8) & 255)
                i = k
            elif n in (10, 13):
                i += 2 + (1 if n == 13 and i + 2 < len(b) and b[i + 2] == 10 else 0)
            else:
                out.append(n)
                i += 2
            continue
        if c == 40:
            depth += 1
        elif c == 41:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
        out.append(c)
        i += 1
    raise ValueError("unterminated string")


class Security:
    """The file key for an /Encrypt dictionary with /Filter /Standard, from the empty user password."""

    def __init__(self, O, U, P, ID0, R=3, length=128, password=b""):
        self.R, self.n = R, (5 if R == 2 else length // 8)
        h = hashlib.md5((password + PAD)[:32] + O + (P & 0xFFFFFFFF).to_bytes(4, "little") + ID0).digest()
        if R >= 3:
            for _ in range(50):
                h = hashlib.md5(h[:self.n]).digest()
        self.key = h[:self.n]
        self.ok = self._check(U, ID0)

    def _check(self, U, ID0):
        if self.R == 2:
            return rc4(self.key, PAD) == U
        x = rc4(self.key, hashlib.md5(PAD + ID0).digest())
        for i in range(1, 20):
            x = rc4(bytes(k ^ i for k in self.key), x)
        return x == U[:16]

    def object_key(self, num, gen):
        h = hashlib.md5(self.key + num.to_bytes(3, "little") + gen.to_bytes(2, "little")).digest()
        return h[:min(16, self.n + 5)]

    def keystream(self, num, gen, length):
        """The RC4 bytes that encrypt this object's stream; byte k of the stream is XORed with byte k."""
        return rc4(self.object_key(num, gen), bytes(length))
