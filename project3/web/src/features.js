// features.py and classify.py: what one block looks like on its own.
"use strict";
(function () {
  var B = BR.base;

  function entropy(d) {
    // the same sum, in the same order (first appearance of each byte value), as Python's
    var n = d.length;
    if (!n) return 0.0;
    var cnt = new Array(256).fill(0), order = [];
    for (var i = 0; i < n; i++) { if (!cnt[d[i]]) order.push(d[i]); cnt[d[i]]++; }
    var s = 0;
    var T = n === 512 && BR.tables ? BR.tables.PLOGP512 : null;
    for (var k = 0; k < order.length; k++) {
      var c = cnt[order[k]];
      s += T ? T[c] : c / n * Math.log2(c / n);
    }
    return -s;
  }
  function textShare(d) {
    var c = 0;
    for (var i = 0; i < d.length; i++) { var x = d[i]; if ((x >= 32 && x < 127) || x === 9 || x === 10 || x === 13) c++; }
    return c / Math.max(1, d.length);
  }
  function jpegScanLike(d) {
    var ffs = 0;
    for (var i = 0; i < d.length - 1; i++) {
      if (d[i] === 0xFF) {
        var n = d[i + 1];
        if (n !== 0 && !(n >= 0xD0 && n <= 0xD7)) return "no";
        ffs++;
      }
    }
    if (d.length && d[d.length - 1] === 0xFF) ffs++;
    return ffs >= 2 ? "yes" : "unsure";
  }
  function randomLike(d) { return entropy(d) >= 7.35; }

  var PDF_WORDS = /\d{10} \d{5} [nf]|\d+ \d+ obj|endobj|endstream|\/Type[ \t\n\r\f\v]*\/|\/Filter|\/Length \d|xref|trailer|%%EOF/;
  var CFB = B.unhex("d0cf11e0a1b11ae1");

  function guess(block) {
    var d = block.data;
    if (B.startsWith(d, "%PDF-")) return ["PDF", "starts with the PDF signature"];
    if (B.startsWith(d, CFB)) return ["Word", "starts with the Compound File signature"];
    if (d[0] === 0xFF && d[1] === 0xD8 && d[2] === 0xFF) return ["JPEG", "starts with the JPEG signature"];
    if (PDF_WORDS.test(B.bstr(d))) return ["PDF", "holds PDF keywords"];
    if (!B.anyNonZero(d)) return ["unsure", "all zeros"];
    var ent = entropy(d), scan = jpegScanLike(d);
    if (ent >= 7.35) {
      if (scan === "yes") return ["JPEG", "noise-like, and every FF byte is followed by 00 as in JPEG picture data"];
      if (scan === "no") return ["PDF", "noise-like, but breaks JPEG's FF rule: encrypted or compressed data"];
      return ["unsure", "noise-like, too few FF bytes to tell"];
    }
    if (textShare(d) > 0.9) return ["Word", "readable text"];
    if (scan === "yes" && ent > 6) return ["JPEG", "every FF byte is followed by 00 as in JPEG picture data"];
    return ["Word", "structured binary (tables, numbers, small values)"];
  }

  BR.features = { entropy: entropy, textShare: textShare, jpegScanLike: jpegScanLike, randomLike: randomLike };
  BR.classify = { guess: guess };
})();
