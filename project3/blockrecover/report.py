"""The recovery report: one offline HTML page, in the term project's theme.

The page draws itself from one embedded JSON object (the same object the
browser edition builds), so the command line and the browser show the same page.
"""

import base64
import json
import os

from . import recover
from .theme import THEME_CSS, THEME_JS

CREDIT = "Created by Captain Scott Russell for CPRE 5360"


def data(R, summary, out=None):
    placed = R.placed()
    files = []
    for f in R.files:
        L = f["layout"]
        info = next(x for x in summary["files"] if x["name"] == f["name"])
        item = dict(info, how=L.how, at=[b.name if b else None for b in L.at])
        if f["kind"] == "JPEG":
            item["preview"] = "data:image/jpeg;base64," + base64.b64encode(recover.file_bytes(f)).decode()
        files.append(item)
    blocks = []
    for b in R.blocks:
        f, p = placed.get(b.name, (None, None))
        g, why = R.guesses[b.name]
        blocks.append([b.name, f["kind"] if f else "", p, g, why])
    return {"credit": CREDIT, "files": files, "blocks": blocks, "unplaced": summary["unplaced"],
            "log": summary["log"], "total": len(R.blocks)}


def render(d):
    return (TEMPLATE.replace("/*CSS*/", THEME_CSS + PAGE_CSS).replace("/*JS*/", THEME_JS)
            .replace("/*DATA*/", json.dumps(d).replace("</", "<\\/")))


def write(R, summary, out):
    with open(os.path.join(out, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(render(data(R, summary, out)))


PAGE_CSS = r"""
.f-PDF{--fc:var(--f5)} .f-Word{--fc:var(--f6)} .f-JPEG{--fc:var(--f3)} .f-{--fc:var(--minor)}
.fcard{border-top:3px solid var(--fc)}
.fcard h3{display:flex;gap:8px;align-items:center}
.fcard .sw{width:12px;height:12px;border-radius:3px;background:var(--fc)}
.prev{width:100%;border-radius:8px;border:1px solid var(--line);margin-top:10px;display:block}
.map{display:grid;grid-template-columns:repeat(auto-fill,minmax(14px,1fr));gap:3px;margin-top:12px}
.map i{display:block;aspect-ratio:1;border-radius:3px;background:var(--fc);opacity:.88;cursor:pointer;transition:transform .12s}
.map i:hover{transform:scale(1.6);opacity:1;z-index:2;position:relative}
.map i.sel{outline:2px solid var(--text)}
.strip{display:flex;flex-wrap:wrap;gap:2px;margin:8px 0 16px}
.strip i{width:10px;height:22px;border-radius:2px;background:var(--hc);cursor:pointer}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px;color:var(--muted);font-size:13px}
.legend span{display:flex;gap:6px;align-items:center}
.legend i{width:12px;height:12px;border-radius:3px;background:var(--fc,var(--hc));display:inline-block}
#tip{position:fixed;z-index:50;pointer-events:none;background:var(--panel2);border:1px solid var(--line2);border-radius:8px;
  padding:8px 10px;font-size:13px;box-shadow:var(--shadow);display:none;max-width:340px}
table.t td,table.t th{padding:6px 8px;text-align:left;border-bottom:1px solid var(--line)}
table.t{border-collapse:collapse;width:100%;font-size:14px}
.qa{margin-top:10px}
.qa details{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:8px}
.qa summary{cursor:pointer;font-weight:600}
.qa p{margin-top:8px;color:var(--muted)}
.logl{font:12px/1.6 var(--mono);color:var(--muted);max-height:420px;overflow:auto;white-space:pre-wrap}
"""

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Block Recovery Report</title><style>/*CSS*/</style></head><body>
<header class="top"><div class="wrap">
  <div class="brand" title="Created by Captain Scott Russell for CPRE 5360"><span class="dot"></span><span class="nm">BLOCK RECOVERY TOOLKIT<small>FILE RECOVERY REPORT</small></span></div>
  <div class="spacer"></div>
  <button class="iconbtn" data-act="theme" title="Light or dark"><svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>
  <button class="iconbtn" data-act="print" title="Print"><svg class="ico" viewBox="0 0 24 24"><path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="7"/></svg></button>
</div></header>
<nav class="tabs" aria-label="Report sections"><div class="wrap">
  <a class="tab" href="#overview" data-tab="overview">Overview</a>
  <a class="tab" href="#map" data-tab="map">Block map</a>
  <a class="tab" href="#files" data-tab="files">Files</a>
  <a class="tab" href="#how" data-tab="how">How it works</a>
</div></nav>
<main class="wrap">
  <section class="panel" id="p-overview"></section>
  <section class="panel" id="p-map"></section>
  <section class="panel" id="p-files"></section>
  <section class="panel" id="p-how"></section>
  <div id="foot"></div>
</main>
<div id="tip"></div>
<script>const D=/*DATA*/;</script>
<script>
const $=s=>document.querySelector(s), esc=s=>String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const KIND={PDF:"PDF document",Word:"Word document",JPEG:"JPEG picture","":"not placed"};
const placed=D.blocks.filter(b=>b[1]).length;
// how each block was placed, in a few plain groups
function group(how){how=how||"";
  if(/stream|picture rows|inside/.test(how))return "Checked by decoding its content";
  if(/paragraph/.test(how))return "Matched by where its line breaks fall";
  if(/zeros|identical/.test(how))return "Empty or repeated (any copy fits)";
  if(/neighbours/.test(how))return "Fits its neighbours best";
  if(/ascending|records/.test(how))return "Continues a numbered table";
  return "Placed by the file's own map";}
const GC={"Placed by the file's own map":"var(--f1)","Checked by decoding its content":"var(--f2)","Matched by where its line breaks fall":"var(--f4)",
  "Continues a numbered table":"var(--f6)","Empty or repeated (any copy fits)":"var(--minor)","Fits its neighbours best":"var(--f7)"};
function kpi(v,l,c){return '<div class="card kpi '+(c||'')+'"><div class="v">'+v+'</div><div class="l">'+l+'</div></div>';}
// overview
$("#p-overview").innerHTML=
 '<div class="grid g4">'+kpi(D.total,"blocks in the set","acc")+kpi(placed,"placed in a file",placed==D.total?"ok":"warn")+
 kpi(D.files.filter(f=>f.ok).length+" / "+D.files.length,"files rebuilt and checked","ok")+kpi(D.unplaced.length,"blocks left over",D.unplaced.length?"warn":"ok")+'</div>'+
 '<div class="grid g3" style="margin-top:14px">'+D.files.map(f=>'<div class="card fcard f-'+f.kind+'"><h3><span class="sw"></span>'+KIND[f.kind]+'</h3>'+
   '<p class="muted" style="margin-top:6px">'+f.blocks+' blocks, '+f.bytes.toLocaleString()+' bytes &middot; <span class="mono">'+esc(f.name)+'</span></p>'+
   '<p style="margin-top:8px">'+(f.ok?'<span class="pill ok">checked</span> ':'<span class="pill hot">incomplete</span> ')+esc(f.note)+'</p>'+
   (f.preview?'<img class="prev" alt="the rebuilt picture" src="'+f.preview+'">':'')+
   '<p class="mono muted" style="margin-top:8px;font-size:11px;word-break:break-all">MD5 '+f.md5+'<br>SHA-256 '+f.sha256+'</p></div>').join("")+'</div>'+
 '<div class="card" style="margin-top:14px"><h3>First guess and final answer</h3><p class="muted" style="margin-top:6px">Before rebuilding, each block is guessed from its own bytes alone. The final answer is the file it has a place in.</p>'+confusion()+'</div>';
function confusion(){const ks=["PDF","Word","JPEG"],gs=["PDF","Word","JPEG","unsure"];const c={};
  D.blocks.forEach(b=>{const k=(b[1]||"")+"|"+b[3];c[k]=(c[k]||0)+1;});
  return '<table class="t" style="margin-top:10px"><tr><th>Final file</th>'+gs.map(g=>'<th>guessed '+g+'</th>').join("")+'</tr>'+
   ks.map(k=>'<tr><td>'+KIND[k]+'</td>'+gs.map(g=>'<td class="mono">'+(c[k+"|"+g]||0)+'</td>').join("")+'</tr>').join("")+'</table>';}
// block map
const pos={}; D.files.forEach(f=>f.at.forEach((n,p)=>{if(n)pos[n]={f:f,p:p};}));
$("#p-map").innerHTML='<div class="card"><h3>Every block, in the order it was given</h3><p class="muted" style="margin-top:6px">Colour shows the file each block was placed in. Point at a block to see where it went and why.</p>'+
 '<div class="legend">'+["PDF","Word","JPEG"].map(k=>'<span class="f-'+k+'"><i></i>'+KIND[k]+'</span>').join("")+'</div>'+
 '<div class="map">'+D.blocks.map((b,i)=>'<i class="f-'+b[1]+'" data-i="'+i+'"></i>').join("")+'</div></div>'+
 '<div class="card" style="margin-top:14px"><h3>Each file, block by block</h3><p class="muted" style="margin-top:6px">Colour shows how each position was decided.</p>'+
 '<div class="legend">'+Object.keys(GC).map(g=>'<span style="--hc:'+GC[g]+'"><i></i>'+g+'</span>').join("")+'</div>'+
 D.files.map(f=>'<h3 style="margin-top:14px">'+KIND[f.kind]+'</h3><div class="strip">'+f.at.map((n,p)=>'<i style="--hc:'+GC[group(f.how[p])]+'" data-f="'+f.name+'" data-p="'+p+'"></i>').join("")+'</div>').join("")+'</div>';
const tip=$("#tip");
document.addEventListener("mousemove",e=>{const t=e.target.closest(".map i,.strip i");if(!t){tip.style.display="none";return;}
  let html;
  if(t.dataset.i){const b=D.blocks[+t.dataset.i],w=pos[b[0]];html='<b class="mono">'+b[0]+'</b><br>'+(w?KIND[w.f.kind]+', position '+w.p+' (byte '+(w.p*512).toLocaleString()+')<br><span class="muted">'+esc(w.f.how[w.p])+'</span>':'not placed')+
    '<br><span class="muted">first guess: '+b[3]+' ('+esc(b[4])+')</span>';}
  else{const f=D.files.find(x=>x.name==t.dataset.f),p=+t.dataset.p;html=KIND[f.kind]+', position '+p+'<br><b class="mono">'+esc(f.at[p]||"empty")+'</b><br><span class="muted">'+esc(f.how[p])+'</span>';}
  tip.innerHTML=html;tip.style.display="block";tip.style.left=Math.min(e.clientX+14,innerWidth-350)+"px";tip.style.top=(e.clientY+14)+"px";});
// files: runs of positions with the same reason
$("#p-files").innerHTML=D.files.map(f=>{const runs=[];f.how.forEach((h,p)=>{const r=runs[runs.length-1];if(r&&r.h==h&&r.b==p-1)r.b=p;else runs.push({a:p,b:p,h:h});});
  return '<div class="card fcard f-'+f.kind+'" style="margin-bottom:14px"><h3><span class="sw"></span>'+KIND[f.kind]+' <span class="mono muted" style="font-size:13px">'+esc(f.name)+'</span></h3>'+
  '<table class="t" style="margin-top:10px"><tr><th>Positions</th><th>Blocks</th><th>How they were placed</th></tr>'+
  runs.map(r=>'<tr><td class="mono">'+(r.a==r.b?r.a:r.a+"&ndash;"+r.b)+'</td><td class="mono">'+(r.a==r.b?esc(f.at[r.a]):esc(f.at[r.a])+" &hellip; "+esc(f.at[r.b]))+'</td><td>'+esc(r.h)+'</td></tr>').join("")+'</table></div>';}).join("")+
  '<div class="card"><h3>Run log</h3><div class="logl" style="margin-top:8px">'+D.log.map(l=>esc(l[0].toFixed(1)+"s  "+l[1]+"  "+l[2])).join("\n")+'</div></div>';
// how it works
const QA=[
 ["What was the problem?","A disk's worth of 512-byte blocks from three files (a PDF, a Word document and a JPEG picture) was shuffled and renamed. Nothing records which file a block came from or where it went. The toolkit sorts the blocks into the three files and puts each file back in order."],
 ["How does it know which file a block belongs to?","It first makes a quick guess from each block alone (readable text, PDF keywords, the JPEG rule that every FF byte is followed by 00, how random the bytes look). That guess is only a starting point. The final answer is the rebuild itself: a block belongs to a file when it has a checked place in that file. The table on the Overview compares the two."],
 ["How is the PDF put back together?","A PDF carries its own map. The first block gives the file's length, the cross-reference tables give the byte offset of every object, and each object starts with the words “N 0 obj”. So most blocks are placed by reading that map: an object at byte X must sit in block X ÷ 512. The insides of streams (page drawings, fonts, pictures) are not on the map. For those, every remaining block is tried as the next one, and the stream is decoded to see if it still makes sense. This file's streams were encrypted with an empty password (allowed to open, not to copy), so each candidate is first decrypted with the key for its exact position."],
 ["How can it tell a right block from a wrong one inside a stream?","A wrong block usually still decompresses, so that alone is not enough. Instead each kind of stream has its own test. Page drawings must read as PDF drawing commands, each with the right number of numbers before it. Fonts and colour profiles carry their own tables and checksums. Other compressed data is judged by the compressor's habits: a real compressor never spells out a run it could have copied, but random data does it constantly. Pictures must decode, and their rows must join up with no seams. At the end of each stream, zlib's built-in checksum (or the picture's end marker) must come out exactly right, which confirms the whole order."],
 ["How is the Word document put back together?","A .doc file is a small file system of its own. Its first block names the blocks that hold its allocation table, and that table lists, for every block, which block comes next. Word's own header then gives the offset of each table it keeps, and one of those tables records where every paragraph ends. So each block of text has a fingerprint: the exact positions of its line breaks. All 135 text blocks were placed that way. Table blocks are placed by their numbers continuing from the block before, and empty areas take the all-zero blocks."],
 ["How is the picture put back together?","The block with the JPEG signature comes first and the block with the end marker comes last. Each block in between is decoded as the continuation of the picture, and the new 8×8 squares of pixels are compared with the squares already above and to the left of them. The right block continues the picture smoothly; a wrong one arrives with a visible seam of brightness or colour. Several partial orderings are kept at once, so one bad step can be undone. The picture must also end exactly at its last row, in the block just before the end marker."],
 ["How sure is each answer?","The PDF and the Word document are confirmed by their own checks: every PDF stream's checksum matches, and the Word file's tables, text and paragraph marks all agree. Both files open normally. The picture has no checksum, so its order rests on how well the rows join. Where it looks wrong, the report says so instead of claiming success."],
 ["What was never changed?","The blocks themselves. The toolkit only reads them. Its output is a new copy of each file, the block map (block_map.csv), and this report. Every block's MD5 is listed in the block map so the inputs can be checked again later."]];
$("#p-how").innerHTML='<div class="qa">'+QA.map(q=>'<details><summary>'+q[0]+'</summary><p>'+q[1]+'</p></details>').join("")+'</div>';
$("#foot").innerHTML='<div class="credit"><b>Block Recovery Toolkit</b><span>&middot; '+esc(D.credit)+'</span></div>';
</script>
<script>/*JS*/</script>
</body></html>
"""
