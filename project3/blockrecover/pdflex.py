"""How much of a piece of decompressed PDF text is well-formed PDF syntax.

A wrong block, decrypted and decompressed as if it continued a stream, often
decodes without an error, because the decoder draws characters from the stream's
own code table. What it cannot do is produce valid syntax for long: numbers come out
with two decimal points, operators are glued to digits, hex strings hold non-hex
characters. The score is the share of bytes that sit in valid tokens.
"""

import re

WS = b" \t\r\n\f\x00"
DELIM = b"()<>[]{}/%"
NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)\Z")
KEYWORD = re.compile(rb"[A-Za-z'\"][A-Za-z0-9*'\"]{0,11}\Z")
HEX = set(b"0123456789abcdefABCDEF \t\r\n\f")


ARITY = {}
for _ops, _n in ((b"q Q h n f F f* B B* b b* S s W W* BT ET EMC BX EX T*", 0),
                 (b"w J j M i gs Tc Tw Tz TL Tr Ts g G cs CS sh Do MP BMC ' Tj TJ ri", 1),
                 (b"m l d Td TD Tf BDC DP d0", 2),
                 (b"rg RG \"", 3),
                 (b"re k K v y", 4),
                 (b"c cm Tm d1", 6)):
    for _op in _ops.split():
        ARITY[_op] = (_n,)
for _op in (b"sc", b"SC", b"scn", b"SCN"):
    ARITY[_op] = (1, 2, 3, 4, 5)
NUM = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
NAME = re.compile(rb"/[^\s()<>\[\]{}/%\x00]*")
WORD = re.compile(rb"[A-Za-z'\"][A-Za-z0-9*'\"]*")
END = re.compile(rb"[\s()<>\[\]{}/%\x00]")


def _unit(b, i):
    """One operand or keyword at b[i] (no leading space). -> (kind, end) ; kind is
    'num', 'name', 'str', 'arr', 'dict', 'word', 'bad'; end None if it runs off the end."""
    c = b[i]
    if c == 0x28:
        depth, j = 1, i + 1
        while j < len(b) and depth:
            if b[j] == 0x5C:
                j += 2
                continue
            depth += {0x28: 1, 0x29: -1}.get(b[j], 0)
            j += 1
        return "str", (j if depth == 0 else None)
    if c == 0x3C:
        if b[i + 1:i + 2] == b"<":
            return _group(b, i + 2, b">>", "dict")
        j = b.find(b">", i)
        if j < 0:
            return "str", None
        return ("str" if all(x in HEX for x in b[i + 1:j]) else "bad"), j + 1
    if c == 0x5B:
        return _group(b, i + 1, b"]", "arr")
    if c == 0x2F:
        m = NAME.match(b, i)
        return "name", m.end()
    m = END.search(b, i)
    j = m.start() if m else len(b)
    if j == len(b):
        return "word", None
    tok = b[i:j] if j > i else b[i:i + 1]
    j = max(j, i + 1)
    if NUM.fullmatch(tok):
        return "num", j
    if WORD.fullmatch(tok) and (len(tok) <= 3 or tok in (b"true", b"false", b"null")):
        return "word", j
    return "bad", j


def _group(b, i, close, kind):
    """The inside of [ ... ] or << ... >>: operands only."""
    ok = True
    while True:
        while i < len(b) and b[i] in WS:
            i += 1
        if i >= len(b):
            return kind, None
        if b.startswith(close, i):
            return (kind if ok else "bad"), i + len(close)
        if b[i] in b">]":
            return "bad", i + 1
        k, i2 = _unit(b, i)
        if i2 is None:
            return kind, None
        if k in ("bad", "word") and b[i:i2] not in (b"true", b"false", b"null", b"R"):
            ok = False
        i = i2


def check(data, carry=b""):
    """Read content-stream text: operands, then an operator that takes that many.
    -> (bad bytes, bytes read, unread tail to carry into the next piece)."""
    b = carry + data
    bad, i, n = 0, 0, len(b)
    run_start, ops = None, 0
    done = 0                                        # end of the last finished operator
    while i < n:
        c = b[i]
        if c in WS:
            i += 1
            continue
        if c == 0x25:
            j = b.find(b"\n", i)
            if j < 0:
                break
            i = j + 1
            if run_start is None:
                done = i
            continue
        kind, j = _unit(b, i)
        if j is None:
            break
        if run_start is None:
            run_start = i
        if kind == "word" and b[i:j] not in (b"true", b"false", b"null"):
            want = ARITY.get(b[i:j])
            if want is None or ops not in want:
                bad += j - run_start
            run_start, ops, done = None, 0, j
        elif kind == "bad":
            bad += j - i
            ops += 1
        else:
            ops += 1
        i = j
    tail = b[done:]
    if len(tail) > 4096:                            # operands that never end in an operator
        bad += len(tail) - 4096
        done += len(tail) - 4096
        tail = b[done:]
    return bad, done, tail


def printable(data):
    return sum(32 <= x < 127 or x in (9, 10, 13) for x in data) / max(1, len(data))


TOKEN = re.compile(rb"\s*(<<|>>|\[|\]|/[^\s()<>\[\]{}/%]*|\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>|[+-]?\d*\.?\d+|true|false|null|R)", re.S)


def value_end(text):
    """Where the PDF value at the start of `text` ends, or -1 if it is not well formed there.

    Used where an object is cut by a block boundary: the block that completes it must
    give names where names go and values where values go."""
    toks, ends, i = [], [], 0
    while True:
        m = TOKEN.match(text, i)
        if not m:
            break
        toks.append(m.group(1))
        ends.append(m.end())
        i = m.end()
    k = _value(toks, 0)
    return ends[k - 1] if k > 0 else -1


def object_ok(text):
    """`text` is an object body after "N G obj": one value, then "stream" or "endobj".
    -> index of that keyword, or -1."""
    e = value_end(text)
    if e < 0:
        return -1
    m = re.match(rb"\s*(stream|endobj)", text[e:])
    return e + m.start(1) if m else -1


def _value(toks, k):
    """Parse one value from toks[k]; -> index after it, or -1."""
    if k >= len(toks):
        return -1
    t = toks[k]
    if t == b"<<":
        k += 1
        while k < len(toks) and toks[k] != b">>":
            if not toks[k].startswith(b"/"):
                return -1
            k = _value(toks, k + 1)
            if k < 0:
                return -1
        return k + 1 if k < len(toks) else -1
    if t == b"[":
        k += 1
        while k < len(toks) and toks[k] != b"]":
            k = _value(toks, k)
            if k < 0:
                return -1
        return k + 1 if k < len(toks) else -1
    if t in (b">>", b"]", b"R"):
        return -1
    if re.fullmatch(rb"\d+", t) and k + 2 < len(toks) and re.fullmatch(rb"\d+", toks[k + 1]) and toks[k + 2] == b"R":
        return k + 3
    return k + 1
