// pdflex.py: how much of a piece of decompressed PDF text is well-formed PDF syntax.
// Strings here are "binary strings" (one char per byte); \s is spelled out as Python's
// bytes \s ([ \t\n\r\v\f]) because JavaScript's \s also matches byte A0.
"use strict";
(function () {
  var WS = " \t\r\n\f\x00", HEX = "0123456789abcdefABCDEF \t\r\n\f";
  var S = "[ \\t\\n\\r\\x0b\\x0c]";
  var ARITY = {};
  [["q Q h n f F f* B B* b b* S s W W* BT ET EMC BX EX T*", 0],
   ["w J j M i gs Tc Tw Tz TL Tr Ts g G cs CS sh Do MP BMC ' Tj TJ ri", 1],
   ["m l d Td TD Tf BDC DP d0", 2], ['rg RG "', 3], ["re k K v y", 4], ["c cm Tm d1", 6]].forEach(function (p) {
    p[0].split(" ").forEach(function (op) { ARITY[op] = [p[1]]; });
  });
  ["sc", "SC", "scn", "SCN"].forEach(function (op) { ARITY[op] = [1, 2, 3, 4, 5]; });
  var NUM = /^[+-]?(?:\d+\.?\d*|\.\d+)$/;
  var NAME = new RegExp("/[^ \\t\\n\\r\\x0b\\x0c()<>\\[\\]{}/%\\x00]*", "y");
  var WORD = /^[A-Za-z'"][A-Za-z0-9*'"]*$/;
  var END = new RegExp("[ \\t\\n\\r\\x0b\\x0c()<>\\[\\]{}/%\\x00]", "g");

  function unit(b, i) {
    var c = b.charCodeAt(i), j;
    if (c === 0x28) {
      var depth = 1; j = i + 1;
      while (j < b.length && depth) {
        var x = b.charCodeAt(j);
        if (x === 0x5C) { j += 2; continue; }
        if (x === 0x28) depth++; else if (x === 0x29) depth--;
        j++;
      }
      return ["str", depth === 0 ? j : null];
    }
    if (c === 0x3C) {
      if (b.charAt(i + 1) === "<") return group(b, i + 2, ">>", "dict");
      j = b.indexOf(">", i);
      if (j < 0) return ["str", null];
      for (var k = i + 1; k < j; k++) if (HEX.indexOf(b.charAt(k)) < 0) return ["bad", j + 1];
      return ["str", j + 1];
    }
    if (c === 0x5B) return group(b, i + 1, "]", "arr");
    if (c === 0x2F) { NAME.lastIndex = i; var m = NAME.exec(b); return ["name", i + m[0].length]; }
    END.lastIndex = i;
    var e = END.exec(b);
    j = e ? e.index : b.length;
    if (j === b.length) return ["word", null];
    var tok = j > i ? b.slice(i, j) : b.slice(i, i + 1);
    j = Math.max(j, i + 1);
    if (NUM.test(tok)) return ["num", j];
    if (WORD.test(tok) && (tok.length <= 3 || tok === "true" || tok === "false" || tok === "null")) return ["word", j];
    return ["bad", j];
  }

  function group(b, i, close, kind) {
    var ok = true;
    for (;;) {
      while (i < b.length && WS.indexOf(b.charAt(i)) >= 0) i++;
      if (i >= b.length) return [kind, null];
      if (b.substr(i, close.length) === close) return [ok ? kind : "bad", i + close.length];
      var ch = b.charAt(i);
      if (ch === ">" || ch === "]") return ["bad", i + 1];
      var r = unit(b, i);
      if (r[1] === null) return [kind, null];
      var t = b.slice(i, r[1]);
      if ((r[0] === "bad" || r[0] === "word") && t !== "true" && t !== "false" && t !== "null" && t !== "R") ok = false;
      i = r[1];
    }
  }

  // -> [bad bytes, bytes read, tail (binary string)]
  function check(data, carry) {
    var b = (carry || "") + data;
    var bad = 0, i = 0, n = b.length, runStart = null, ops = 0, done = 0;
    while (i < n) {
      var c = b.charAt(i);
      if (WS.indexOf(c) >= 0) { i++; continue; }
      if (c === "%") {
        var j0 = b.indexOf("\n", i);
        if (j0 < 0) break;
        i = j0 + 1;
        if (runStart === null) done = i;
        continue;
      }
      var r = unit(b, i), kind = r[0], j = r[1];
      if (j === null) break;
      if (runStart === null) runStart = i;
      var tok = b.slice(i, j);
      if (kind === "word" && tok !== "true" && tok !== "false" && tok !== "null") {
        var want = Object.prototype.hasOwnProperty.call(ARITY, tok) ? ARITY[tok] : null;
        if (want === null || want.indexOf(ops) < 0) bad += j - runStart;
        runStart = null; ops = 0; done = j;
      } else if (kind === "bad") { bad += j - i; ops++; }
      else ops++;
      i = j;
    }
    var tail = b.slice(done);
    if (tail.length > 4096) { bad += tail.length - 4096; done += tail.length - 4096; tail = b.slice(done); }
    return [bad, done, tail];
  }

  var TOKEN = new RegExp(S + "*(<<|>>|\\[|\\]|/[^ \\t\\n\\r\\x0b\\x0c()<>\\[\\]{}/%]*|\\((?:\\\\[\\s\\S]|[^\\\\)])*\\)|<[0-9A-Fa-f \\t\\n\\r\\x0b\\x0c]*>|[+-]?\\d*\\.?\\d+|true|false|null|R)", "y");

  function value(toks, k) {
    if (k >= toks.length) return -1;
    var t = toks[k];
    if (t === "<<") {
      k++;
      while (k < toks.length && toks[k] !== ">>") {
        if (toks[k].charAt(0) !== "/") return -1;
        k = value(toks, k + 1);
        if (k < 0) return -1;
      }
      return k < toks.length ? k + 1 : -1;
    }
    if (t === "[") {
      k++;
      while (k < toks.length && toks[k] !== "]") { k = value(toks, k); if (k < 0) return -1; }
      return k < toks.length ? k + 1 : -1;
    }
    if (t === ">>" || t === "]" || t === "R") return -1;
    if (/^\d+$/.test(t) && k + 2 < toks.length && /^\d+$/.test(toks[k + 1]) && toks[k + 2] === "R") return k + 3;
    return k + 1;
  }
  function valueEnd(text) {
    var toks = [], ends = [], i = 0;
    for (;;) {
      TOKEN.lastIndex = i;
      var m = TOKEN.exec(text);
      if (!m) break;
      toks.push(m[1]); ends.push(TOKEN.lastIndex);
      if (TOKEN.lastIndex === i) break;
      i = TOKEN.lastIndex;
    }
    var k = value(toks, 0);
    return k > 0 ? ends[k - 1] : -1;
  }
  var AFTER = new RegExp("^" + S + "*(stream|endobj)");
  function objectOk(text) {
    var e = valueEnd(text);
    if (e < 0) return -1;
    var m = AFTER.exec(text.slice(e));
    return m ? e + m[0].length - m[1].length : -1;
  }

  BR.pdflex = { check: check, valueEnd: valueEnd, objectOk: objectOk };
})();
