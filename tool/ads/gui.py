"""A small point-and-click launcher that opens in the browser.

No extra packages, no tkinter: it runs a local web page (only this computer can
reach it) with two choices, a Windows drive (a folder of parser CSVs) or a
USB/FAT drive image. Pick one, press Run, and the plain-language report opens.

    python3 -m ads gui          # opens http://127.0.0.1:8765 in your browser
"""

import json
import os
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import load_config

JOBS = {}
_LOCK = threading.Lock()


def _new_job():
    jid = "j%d" % int(time.time() * 1000)
    JOBS[jid] = {"status": "running", "steps": [], "out": None, "report": None, "error": None}
    return jid


def _step(jid, msg):
    with _LOCK:
        JOBS[jid]["steps"].append(msg)


def _run_ntfs(jid, folder):
    from . import pipeline
    cfg = load_config(None)
    out = os.path.join(folder, "ADS report")
    db = os.path.join(out, "case.sqlite")
    os.makedirs(out, exist_ok=True)
    try:
        _step(jid, "Reading the records in that folder")
        summary = pipeline.ingest_folder(folder, db, cfg)
        _step(jid, "Loaded " + ", ".join("%s (%d rows)" % (s["kind"], s["rows"]) for s in summary))
        _step(jid, "Cross-checking the records")
        r = pipeline.analyze_db(db, out, cfg)
        _step(jid, "Checked %d files; flagged %d" % (r["scored"], r["flagged"]))
        _finish(jid, out, os.path.join(out, "briefing.html"))
    except Exception as e:
        _fail(jid, str(e))


def _run_fat(jid, image):
    from .briefing import render
    from .fat import NotFAT
    from .triage import Triage
    out = os.path.splitext(image)[0] + " report"
    try:
        _step(jid, "Opening the drive image")
        t = Triage(image)
        _step(jid, "Reading files and asking eight questions of each")
        t.collect().run()
        data = t.to_json()
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "briefing.html"), "w", encoding="utf-8") as fh:
            fh.write(render(data))
        _step(jid, "Checked %d files; %d had a clue" % (data["counts"]["examined"], data["counts"]["with_findings"]))
        _finish(jid, out, os.path.join(out, "briefing.html"))
    except NotFAT:
        _fail(jid, "That image is not a FAT drive. For a Windows (NTFS) image, use the Windows drive option "
                   "after running the parsers (scripts/run_parsers.ps1).")
    except Exception as e:
        _fail(jid, str(e))


def _finish(jid, out, report):
    with _LOCK:
        JOBS[jid].update(status="done", out=out, report=report)


def _fail(jid, msg):
    with _LOCK:
        JOBS[jid].update(status="error", error=msg)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE)
        if u.path == "/status":
            jid = q.get("job", [""])[0]
            job = JOBS.get(jid)
            if not job:
                return self._send(404, "{}", "application/json")
            view = {"status": job["status"], "steps": job["steps"], "error": job["error"],
                    "report": ("/report?job=%s&f=briefing.html" % jid) if job["report"] else None,
                    "folder": job["out"]}
            return self._send(200, json.dumps(view), "application/json")
        if u.path == "/report":
            jid = q.get("job", [""])[0]
            job = JOBS.get(jid)
            if not job or not job["out"]:
                return self._send(404, "not found")
            name = os.path.basename(q.get("f", ["briefing.html"])[0])
            path = os.path.join(job["out"], name)
            if not os.path.isfile(path):
                return self._send(404, "not found")
            ctype = "text/html; charset=utf-8" if name.endswith(".html") else "application/octet-stream"
            with open(path, "rb") as fh:
                return self._send(200, fh.read(), ctype)
        self._send(404, "not found")

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, "not found")
        length = int(self.headers.get("Content-Length", 0))
        data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        kind = data.get("kind", [""])[0]
        path = data.get("path", [""])[0].strip().strip('"').strip("'")
        if kind == "ntfs" and not os.path.isdir(path):
            return self._send(200, json.dumps({"error": "That folder was not found: %s" % path}), "application/json")
        if kind == "fat" and not os.path.isfile(path):
            return self._send(200, json.dumps({"error": "That image file was not found: %s" % path}), "application/json")
        jid = _new_job()
        target = _run_ntfs if kind == "ntfs" else _run_fat
        threading.Thread(target=target, args=(jid, path), daemon=True).start()
        self._send(200, json.dumps({"job": jid}), "application/json")


def main(argv=None):
    port = 8765
    if argv:
        try:
            port = int(argv[0])
        except ValueError:
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d" % port
    print("ADS control panel is open at %s" % url)
    print("Leave this window open while you use it. Press Ctrl+C here to close.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nClosed.")


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ADS</title>
<style>
:root{--cardinal:#C8102E;--gold:#F1BE48;--ink:#1A1A1A;--muted:#5E5A5A;--line:#DAD6D6;--paper:#fff;--panel:#F7F4F2;--ok:#2E7D4F;
--head:Cambria,Georgia,serif;--body:Calibri,"Segoe UI",Arial,sans-serif;--mono:Consolas,monospace}
@media(prefers-color-scheme:dark){:root{--cardinal:#E2304C;--ink:#EDE8E6;--muted:#ADA5A3;--line:#3A3434;--paper:#151212;--panel:#1F1A1A;--ok:#6CC596;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.55 var(--body)}
.wrap{max-width:760px;margin:0 auto;padding:0 16px}
.band{background:var(--cardinal);color:#fff;border-bottom:8px solid var(--gold)}
.band .wrap{padding:28px 16px}
.band .eyebrow{color:var(--gold);font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:13px}
h1{font-family:var(--head);font-size:clamp(26px,5vw,40px);margin:6px 0 4px}
h2{font-family:var(--head);color:var(--cardinal);font-size:22px;margin:0 0 4px}
.band p{max-width:52ch;margin:0}
.card{border:1px solid var(--line);border-left:6px solid var(--cardinal);border-radius:12px;padding:18px;margin:18px 0;background:var(--paper)}
label{display:block;font-weight:700;margin:10px 0 4px;font-size:15px}
input[type=text]{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font:15px var(--mono);background:var(--panel);color:var(--ink)}
.hint{color:var(--muted);font-size:14px;margin:6px 0 0}
button{font:700 16px var(--body);border:0;border-radius:999px;padding:10px 22px;background:var(--cardinal);color:#fff;cursor:pointer;margin-top:12px}
button:hover{background:#9E0B23}
#log{margin:18px 0}
.step{padding:7px 12px;border-left:3px solid var(--gold);background:var(--panel);border-radius:4px;margin:6px 0;font-size:15px}
.err{border-left-color:var(--cardinal);color:var(--cardinal)}
.done{border-left-color:var(--ok)}
a.open{display:inline-block;margin-top:10px;font-weight:700}
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--gold);border-top-color:transparent;border-radius:50%;animation:s .8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes s{to{transform:rotate(360deg)}}
</style></head><body>
<div class="band"><div class="wrap">
<div class="eyebrow">Artifact Disagreement Scorer</div>
<h1>First-look report</h1>
<p>Point the tool at a drive, and it writes a plain-language report of anything worth a second look. The drive is only read, never changed.</p>
</div></div>
<div class="wrap">
<div class="card">
<h2>Windows drive</h2>
<p class="hint">For a Windows (NTFS) system drive. First run the parsers (scripts/run_parsers.ps1) to make the record files, then give the folder that holds them here.</p>
<label for="ntfs">Folder with the record files (mft.csv, usn.csv, …)</label>
<input type="text" id="ntfs" placeholder="C:\Cases\Case01\parsed">
<button onclick="run('ntfs','ntfs')">Run on this folder</button>
</div>
<div class="card">
<h2>USB or memory-card image</h2>
<p class="hint">For a FAT drive image (.img, .dd, .raw). Give the image file itself.</p>
<label for="fat">Drive image file</label>
<input type="text" id="fat" placeholder="C:\Cases\usb.img">
<button onclick="run('fat','fat')">Run on this image</button>
</div>
<div id="log"></div>
</div>
<script>
let timer=null;
function el(t,c,h){let e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e}
function run(kind,inputId){
  let path=document.getElementById(inputId).value;
  let log=document.getElementById('log');log.innerHTML='';
  if(!path){log.appendChild(el('div','step err','Please enter a path first.'));return}
  log.appendChild(el('div','step','<span class="spin"></span>Starting…'));
  fetch('/run',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:'kind='+encodeURIComponent(kind)+'&path='+encodeURIComponent(path)})
   .then(r=>r.json()).then(d=>{
     if(d.error){log.innerHTML='';log.appendChild(el('div','step err',d.error));return}
     poll(d.job);
   });
}
function poll(job){
  if(timer)clearInterval(timer);
  timer=setInterval(()=>{
    fetch('/status?job='+job).then(r=>r.json()).then(d=>{
      let log=document.getElementById('log');log.innerHTML='';
      d.steps.forEach(s=>log.appendChild(el('div','step',s)));
      if(d.status==='running')log.appendChild(el('div','step','<span class="spin"></span>Working…'));
      if(d.status==='error'){clearInterval(timer);log.appendChild(el('div','step err',d.error))}
      if(d.status==='done'){clearInterval(timer);
        let done=el('div','step done','Done. The report is saved in: '+d.folder);
        log.appendChild(done);
        let a=el('a','open','Open the report ▸');a.href=d.report;a.target='_blank';
        log.appendChild(a);
      }
    });
  },600);
}
</script>
</body></html>"""
