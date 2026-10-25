"""A small point-and-click launcher that opens in the browser.

No extra packages, no tkinter: it runs a local web page (only this computer can
reach it) with two choices: the Windows date checks (an NTFS image, or a folder of
parser CSVs) or the first-look report on a FAT or NTFS drive image. Pick one,
press Run, and the plain-language report opens.

    python3 -m ads gui          # opens http://127.0.0.1:8765 in your browser
"""

import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import load_config

JOBS = {}
_LOCK = threading.Lock()
# A fresh random token per run. Only the panel page this server sends knows it, and every request
# must carry it, so a web page from another site open in the same browser cannot start a job or
# read results. Requests must also name this computer as their host (blocks DNS rebinding).
TOKEN = secrets.token_urlsafe(24)


def _new_job():
    jid = "j%d" % int(time.time() * 1000)
    JOBS[jid] = {"status": "running", "steps": [], "out": None, "report": None, "proof": None, "error": None}
    return jid


def _step(jid, msg):
    with _LOCK:
        JOBS[jid]["steps"].append(msg)


def _run_ntfs(jid, path):
    """A folder of parser CSVs, or a raw NTFS image read directly (MFT-only rules)."""
    from . import pipeline
    cfg = load_config(None)
    is_image = os.path.isfile(path)
    out = (os.path.splitext(path)[0] + " Windows report") if is_image else os.path.join(path, "ADS report")
    db = os.path.join(out, "case.sqlite")
    os.makedirs(out, exist_ok=True)
    try:
        if is_image:
            _step(jid, "Reading the file table (MFT) straight from the image")
            summary = pipeline.ingest_image(path, db, cfg)
        else:
            _step(jid, "Reading the records in that folder")
            summary = pipeline.ingest_folder(path, db, cfg)
        _step(jid, "Loaded " + ", ".join("%s (%d rows)" % (s["kind"], s["rows"]) for s in summary))
        _step(jid, "Cross-checking the records")
        r = pipeline.analyze_db(db, out, cfg, self_calibrate=True)
        _step(jid, "Checked %d files; flagged %d" % (r["scored"], r["flagged"]))
        _finish(jid, out, os.path.join(out, "briefing.html"))
    except Exception as e:
        _fail(jid, str(e))


def _run_image(jid, image, key=""):
    """First-look report on a FAT or NTFS drive image: the eight questions; optionally a proof page."""
    from .briefing import write_triage
    from .triage import Triage, UnsupportedImage
    out = os.path.splitext(image)[0] + " report"
    try:
        _step(jid, "Opening the drive image")
        t = Triage(image)
        _step(jid, "Opened the drive (%s). Reading files and asking eight questions of each" % t.vol.summary()["fs_type"])
        t.collect().run()
        data, html = write_triage(t, out)
        _step(jid, "Checked %d files; %d had a clue" % (data["counts"]["examined"], data["counts"]["with_findings"]))
        if key:
            from . import proof
            _, summ = proof.write(out, key)
            _step(jid, "Compared with your answer key: %d of %d evidence files are on the list (%d in the top 10)"
                  % (summ["found"], summ["evidence"], summ["top10"]))
            with _LOCK:
                JOBS[jid]["proof"] = True
        _finish(jid, out, html)
    except UnsupportedImage as e:
        _fail(jid, "%s ADS reads raw images (.img, .dd, .raw) of FAT and NTFS drives." % e)
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

    def _host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _token_ok(self, given):
        return secrets.compare_digest(given or "", TOKEN)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, "forbidden")
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE.replace("@TOKEN@", TOKEN))
        if not self._token_ok(q.get("t", [""])[0]):
            return self._send(403, "forbidden")
        if u.path == "/status":
            jid = q.get("job", [""])[0]
            job = JOBS.get(jid)
            if not job:
                return self._send(404, "{}", "application/json")
            view = {"status": job["status"], "steps": job["steps"], "error": job["error"],
                    "report": ("/report?job=%s&f=briefing.html&t=%s" % (jid, TOKEN)) if job["report"] else None,
                    "proof": ("/report?job=%s&f=proof.html&t=%s" % (jid, TOKEN)) if job["proof"] and job["report"] else None,
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
        if not self._host_ok():
            return self._send(403, "forbidden")
        if self.path != "/run":
            return self._send(404, "not found")
        length = int(self.headers.get("Content-Length", 0))
        data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        if not self._token_ok(data.get("t", [""])[0]):
            return self._send(403, "forbidden")
        kind = data.get("kind", [""])[0]
        path = data.get("path", [""])[0].strip().strip('"').strip("'")
        if kind == "ntfs" and not os.path.exists(path):
            return self._send(200, json.dumps({"error": "That folder or image was not found: %s" % path}), "application/json")
        if kind == "fat" and not os.path.isfile(path):
            return self._send(200, json.dumps({"error": "That image file was not found: %s" % path}), "application/json")
        key = data.get("key", [""])[0].strip().strip('"').strip("'")
        if kind == "fat" and key and not os.path.isfile(key):
            return self._send(200, json.dumps({"error": "That answer key file was not found: %s" % key}), "application/json")
        jid = _new_job()
        if kind == "ntfs":
            threading.Thread(target=_run_ntfs, args=(jid, path), daemon=True).start()
        else:
            threading.Thread(target=_run_image, args=(jid, path, key), daemon=True).start()
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
<p class="hint">Checks the dates Windows keeps for each file. Give either an NTFS drive image (quickest: reads the file table directly), or the folder of record files made by scripts/run_parsers.ps1 (adds the change journal, shortcuts, Prefetch and event logs).</p>
<label for="ntfs">NTFS drive image, or folder with the record files</label>
<input type="text" id="ntfs" placeholder="C:\Cases\Case01\parsed">
<button onclick="run('ntfs','ntfs')">Run on this folder</button>
</div>
<div class="card">
<h2>First look at a drive image</h2>
<p class="hint">Asks eight questions of every file (disguised, hidden, locked, password written down, and so on). Works on FAT and NTFS images (.img, .dd, .raw).</p>
<label for="fat">Drive image file</label>
<input type="text" id="fat" placeholder="C:\Cases\26Fall_Project2.img">
<label for="key">Optional: your own findings, to compare (answer key .csv)</label>
<input type="text" id="key" placeholder="proof\project2_answer_key.csv">
<p class="hint">If you give an answer key, a second page shows where the tool ranked each item you found by hand.</p>
<button onclick="run('fat','fat')">Run on this image</button>
</div>
<div id="log"></div>
</div>
<script>
const TOKEN='@TOKEN@';
let timer=null;
function el(t,c,h){let e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e}
function run(kind,inputId){
  let path=document.getElementById(inputId).value;
  let log=document.getElementById('log');log.innerHTML='';
  if(!path){log.appendChild(el('div','step err','Please enter a path first.'));return}
  log.appendChild(el('div','step','<span class="spin"></span>Starting…'));
  fetch('/run',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:'kind='+encodeURIComponent(kind)+'&path='+encodeURIComponent(path)+'&t='+TOKEN+
      (kind==='fat'?'&key='+encodeURIComponent(document.getElementById('key').value):'')})
   .then(r=>r.json()).then(d=>{
     if(d.error){log.innerHTML='';log.appendChild(el('div','step err',d.error));return}
     poll(d.job);
   });
}
function poll(job){
  if(timer)clearInterval(timer);
  timer=setInterval(()=>{
    fetch('/status?job='+job+'&t='+TOKEN).then(r=>r.json()).then(d=>{
      let log=document.getElementById('log');log.innerHTML='';
      d.steps.forEach(s=>log.appendChild(el('div','step',s)));
      if(d.status==='running')log.appendChild(el('div','step','<span class="spin"></span>Working…'));
      if(d.status==='error'){clearInterval(timer);log.appendChild(el('div','step err',d.error))}
      if(d.status==='done'){clearInterval(timer);
        let done=el('div','step done','Done. The report is saved in: '+d.folder);
        log.appendChild(done);
        let a=el('a','open','Open the report ▸');a.href=d.report;a.target='_blank';
        log.appendChild(a);
        if(d.proof){let b=el('a','open','Open the comparison with your findings ▸');b.href=d.proof;b.target='_blank';
          b.style.marginLeft='18px';log.appendChild(b);}
      }
    });
  },600);
}
</script>
</body></html>"""
