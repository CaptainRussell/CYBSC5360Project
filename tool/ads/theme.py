"""One look for every page ADS writes: a dark, console-style forensic theme.

All report pages (first-look report, Windows date report, proof page, evaluation
page, control panel) embed THEME_CSS and, where they have tabs or expanding rows,
THEME_JS. Everything is inline: a report opened on an offline forensic workstation
must not fetch fonts or scripts from the internet.

Colors: near-black navy surfaces; cyan for data and interaction, violet for
structure; rose, amber and green for "look first", "worth a look" and "clean".
"""

THEME_CSS = r"""
:root{
  --bg:#0A0F1C; --bg2:#0D1424; --panel:#111A2E; --panel2:#16223A; --line:#23314E; --line2:#2E3F62;
  --text:#E5ECF6; --muted:#8B9BB7; --dim:#5B6B88;
  --accent:#22D3EE; --accent-ink:#67E8F9; --accent-soft:rgba(34,211,238,.12);
  --accent2:#A78BFA; --accent2-soft:rgba(167,139,250,.14);
  --hot:#FB7185; --hot-soft:rgba(251,113,133,.14); --warn:#FBBF24; --warn-soft:rgba(251,191,36,.14);
  --ok:#34D399; --ok-soft:rgba(52,211,153,.13); --minor:#64748B; --minor-soft:rgba(100,116,139,.18);
  --f1:#22D3EE; --f2:#A78BFA; --f3:#FBBF24; --f4:#34D399; --f5:#F472B6; --f6:#60A5FA; --f7:#FB923C; --f8:#4ADE80;
  --shadow:0 10px 30px rgba(0,0,0,.35);
  --ui:"Segoe UI",system-ui,-apple-system,"Helvetica Neue",Roboto,Arial,sans-serif;
  --mono:"Cascadia Code","JetBrains Mono","SF Mono",Consolas,"Liberation Mono",monospace;
  color-scheme:dark;
}
:root[data-theme="light"]{
  --bg:#F3F6FB; --bg2:#EAF0F8; --panel:#FFFFFF; --panel2:#F5F8FC; --line:#D9E1EC; --line2:#C5D1E2;
  --text:#0F172A; --muted:#475569; --dim:#64748B;
  --accent:#0891B2; --accent-ink:#0E7490; --accent-soft:rgba(8,145,178,.10);
  --accent2:#7C3AED; --accent2-soft:rgba(124,58,237,.10);
  --hot:#E11D48; --hot-soft:rgba(225,29,72,.10); --warn:#B45309; --warn-soft:rgba(180,83,9,.10);
  --ok:#047857; --ok-soft:rgba(4,120,87,.10); --minor:#64748B; --minor-soft:rgba(100,116,139,.12);
  --f1:#0891B2; --f2:#7C3AED; --f3:#B45309; --f4:#047857; --f5:#DB2777; --f6:#2563EB; --f7:#C2410C; --f8:#15803D;
  --shadow:0 8px 24px rgba(15,23,42,.10);
  color-scheme:light;
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--text);font:15px/1.5 var(--ui);min-height:100vh;
  background-image:linear-gradient(var(--bg2) 1px,transparent 1px),linear-gradient(90deg,var(--bg2) 1px,transparent 1px);
  background-size:32px 32px;background-attachment:fixed}
a{color:var(--accent-ink)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.mono,code,kbd{font-family:var(--mono)}
h1,h2,h3{margin:0;font-weight:650;letter-spacing:-.01em}
p{margin:0}
.wrap{max-width:1180px;margin:0 auto;padding:0 18px}
.ico{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;flex:none}

/* ---- header and tabs ---- */
.top{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line)}
.top .wrap{display:flex;align-items:center;gap:14px;height:54px}
.brand{display:flex;align-items:center;gap:9px;font:700 14px var(--mono);letter-spacing:.06em;color:var(--accent);white-space:nowrap}
.brand .dot{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent);animation:pulse 2.4s ease-in-out infinite}
@keyframes pulse{50%{opacity:.35}}
.case{display:flex;gap:8px;align-items:center;min-width:0;color:var(--muted);font-size:13px}
.case b{color:var(--text);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pill{display:inline-flex;align-items:center;gap:6px;padding:2px 9px;border-radius:999px;border:1px solid var(--line2);
  font:600 12px var(--mono);color:var(--muted);white-space:nowrap;background:var(--panel)}
.pill.acc{color:var(--accent-ink);border-color:color-mix(in srgb,var(--accent) 45%,var(--line))}
.spacer{flex:1}
.iconbtn{border:1px solid var(--line2);background:var(--panel);color:var(--muted);border-radius:8px;height:32px;min-width:32px;
  display:inline-grid;place-items:center;cursor:pointer;padding:0 8px;font:600 12px var(--ui)}
.iconbtn:hover{color:var(--text);border-color:var(--accent)}
.tabs{border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--bg) 92%,transparent);position:sticky;top:54px;z-index:19;backdrop-filter:blur(8px)}
.tabs .wrap{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none}
.tab{display:flex;align-items:center;gap:8px;padding:12px 14px 11px;color:var(--muted);text-decoration:none;font-weight:600;font-size:14px;
  border-bottom:2px solid transparent;white-space:nowrap;cursor:pointer;background:none;border-top:0;border-left:0;border-right:0}
.tab:hover{color:var(--text)}
.tab[aria-selected="true"]{color:var(--accent-ink);border-bottom-color:var(--accent)}
.tab .n{font:600 11px var(--mono);padding:0 6px;border-radius:999px;background:var(--panel2);color:var(--muted)}
.tab[aria-selected="true"] .n{background:var(--accent-soft);color:var(--accent-ink)}
.tab kbd{font-size:10px;color:var(--dim);border:1px solid var(--line2);border-radius:4px;padding:0 4px}
@media (max-width:760px){.tab kbd{display:none}.case .hide-s{display:none}}
@media (max-width:620px){.top .wrap{gap:8px}.case b{display:none}.brand{font-size:12px}.case{overflow:hidden}}

/* ---- panels ---- */
main{padding:22px 0 60px}
.panel{display:none;animation:enter .35s ease both}
.panel.on{display:block}
@keyframes enter{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.ph{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.ph h2{font-size:22px}
.ph .sub{color:var(--muted);font-size:14px;margin-top:3px}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}.g3{grid-template-columns:repeat(3,minmax(0,1fr))}.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:900px){.g3,.g4{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:620px){.g2,.g3{grid-template-columns:minmax(0,1fr)}.g4{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi .v{font-size:26px}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;min-width:0;position:relative}
.card h3{font-size:14px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.kpi .v{font:700 34px/1 var(--mono);letter-spacing:-.02em}
.kpi .l{color:var(--muted);font-size:13px;margin-top:6px}
.kpi.hot .v{color:var(--hot)}.kpi.acc .v{color:var(--accent)}.kpi.ok .v{color:var(--ok)}.kpi.warn .v{color:var(--warn)}
.kpi::after{content:"";position:absolute;left:16px;right:16px;bottom:0;height:2px;border-radius:2px;background:var(--line)}
.kpi.hot::after{background:var(--hot)}.kpi.acc::after{background:var(--accent)}.kpi.ok::after{background:var(--ok)}.kpi.warn::after{background:var(--warn)}
.muted{color:var(--muted)}.dim{color:var(--dim)}
.note{font-size:13px;color:var(--muted)}

/* ---- badges, chips, bars ---- */
.badge{display:inline-flex;align-items:center;gap:5px;font:700 11px var(--ui);letter-spacing:.06em;text-transform:uppercase;padding:3px 8px;border-radius:6px;white-space:nowrap}
.badge.hot{background:var(--hot-soft);color:var(--hot)}.badge.warn{background:var(--warn-soft);color:var(--warn)}
.badge.minor{background:var(--minor-soft);color:var(--muted)}.badge.ok{background:var(--ok-soft);color:var(--ok)}
.badge.acc{background:var(--accent-soft);color:var(--accent-ink)}
.chip{display:inline-flex;align-items:center;gap:5px;font:600 12px var(--ui);padding:3px 8px;border-radius:999px;border:1px solid var(--line2);
  color:var(--muted);background:var(--panel2);white-space:nowrap}
.chip b{font:700 11px var(--mono);color:var(--accent-ink)}
button.chip{cursor:pointer}
button.chip[aria-pressed="true"]{border-color:var(--accent);color:var(--text);background:var(--accent-soft)}
.bar{height:8px;border-radius:99px;background:var(--panel2);overflow:hidden}
.bar>i{display:block;height:100%;width:0;border-radius:99px;background:var(--accent);transition:width 1s cubic-bezier(.2,.8,.2,1)}
.bar.hot>i{background:var(--hot)}.bar.warn>i{background:var(--warn)}.bar.minor>i{background:var(--minor)}.bar.ok>i{background:var(--ok)}

/* ---- tables ---- */
table.t{border-collapse:collapse;width:100%;font-size:14px}
.t th,.t td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.t th{color:var(--dim);font:700 11px var(--ui);text-transform:uppercase;letter-spacing:.07em;white-space:nowrap}
.t tbody tr:hover td{background:var(--panel2)}
.t td.num,.t th.num{text-align:right;font-family:var(--mono)}
.scroll-x{overflow-x:auto}

/* ---- expanding rows (accordion) ---- */
.acc-item{border:1px solid var(--line);border-radius:10px;background:var(--panel);margin-bottom:8px;overflow:hidden;transition:border-color .2s}
.acc-item:hover{border-color:var(--line2)}
.acc-item.open{border-color:color-mix(in srgb,var(--accent) 50%,var(--line))}
.acc-head{display:flex;align-items:center;gap:12px;padding:11px 14px;cursor:pointer;width:100%;background:none;border:0;color:inherit;font:inherit;text-align:left}
.acc-head .chev{transition:transform .25s;color:var(--dim)}
.acc-item.open .acc-head .chev{transform:rotate(90deg);color:var(--accent)}
.acc-body{display:grid;grid-template-rows:0fr;transition:grid-template-rows .3s ease}
.acc-item.open>.acc-body{grid-template-rows:1fr}
.acc-body>div{overflow:hidden}
.acc-inner{padding:2px 16px 16px;border-top:1px dashed var(--line)}
details.more{margin-top:10px}
details.more>summary{cursor:pointer;color:var(--accent-ink);font-size:13px;font-weight:600;list-style:none;display:inline-flex;align-items:center;gap:6px}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::before{content:"▸";transition:transform .2s;display:inline-block}
details.more[open]>summary::before{transform:rotate(90deg)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;font-size:13px;margin-top:8px}
.kv dt{color:var(--dim)}.kv dd{margin:0;font-family:var(--mono);overflow-wrap:anywhere}

/* ---- tooltip ---- */
#tip{position:fixed;z-index:50;pointer-events:none;max-width:320px;background:var(--panel);border:1px solid var(--accent);border-radius:8px;
  padding:8px 10px;font-size:13px;box-shadow:var(--shadow);opacity:0;transform:translateY(4px);transition:opacity .12s,transform .12s}
#tip.on{opacity:1;transform:none}
#tip b{color:var(--accent-ink)}

/* ---- inputs ---- */
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.search{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line2);border-radius:8px;padding:0 10px;height:36px;min-width:220px;flex:1;max-width:380px}
.search input{border:0;background:none;color:var(--text);font:14px var(--ui);outline:none;width:100%}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden}
.seg button{border:0;background:var(--panel);color:var(--muted);font:600 13px var(--ui);padding:0 12px;height:34px;cursor:pointer;border-right:1px solid var(--line2)}
.seg button:last-child{border-right:0}
.seg button[aria-pressed="true"]{background:var(--accent-soft);color:var(--accent-ink)}

footer.foot{border-top:1px solid var(--line);color:var(--dim);font-size:12px;padding:16px 0 30px;overflow-wrap:anywhere}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
@media print{
  :root{--bg:#fff;--bg2:#fff;--panel:#fff;--panel2:#f4f6f9;--line:#d6dde8;--text:#000;--muted:#333;--dim:#555;color-scheme:light}
  body{background:#fff}.top,.tabs,.toolbar,.iconbtn{display:none!important}
  .panel{display:block!important;break-before:page}.acc-body{grid-template-rows:1fr!important}
}
"""

THEME_JS = r"""
(function(){
  const $=(s,r)=> (r||document).querySelector(s), $$=(s,r)=>Array.from((r||document).querySelectorAll(s));
  // theme toggle (remembered per viewer; works without storage too)
  const root=document.documentElement;
  try{const t=localStorage.getItem('ads-theme'); if(t) root.dataset.theme=t;}catch(e){}
  $$('[data-act="theme"]').forEach(b=>b.addEventListener('click',()=>{
    root.dataset.theme = root.dataset.theme==='light' ? 'dark' : 'light';
    try{localStorage.setItem('ads-theme',root.dataset.theme);}catch(e){}
  }));
  $$('[data-act="print"]').forEach(b=>b.addEventListener('click',()=>window.print()));
  // tabs: hash routing, number keys, arrow keys
  const tabs=$$('.tab[data-tab]'), names=tabs.map(t=>t.dataset.tab);
  function show(name,push){
    if(!names.length) return;            // a page without tabs (the control panel)
    if(!names.includes(name)) name=names[0];
    tabs.forEach(t=>t.setAttribute('aria-selected', t.dataset.tab===name?'true':'false'));
    $$('.panel').forEach(p=>p.classList.toggle('on', p.id==='p-'+name));
    if(push!==false && location.hash!=='#'+name) history.pushState(null,'','#'+name);
    window.scrollTo({top:0});
    document.dispatchEvent(new CustomEvent('ads:tab',{detail:name}));
  }
  window.ADS_SHOW=show;
  tabs.forEach(t=>t.addEventListener('click',e=>{e.preventDefault();show(t.dataset.tab);}));
  window.addEventListener('popstate',()=>show(location.hash.slice(1),false));
  document.addEventListener('keydown',e=>{
    if(e.target.closest('input,textarea')||e.ctrlKey||e.metaKey||e.altKey) return;
    const i=parseInt(e.key,10); if(i>=1&&i<=names.length){show(names[i-1]);return;}
    const cur=names.indexOf((tabs.find(t=>t.getAttribute('aria-selected')==='true')||tabs[0]||{}).dataset?.tab);
    if(e.key==='ArrowRight'&&cur<names.length-1) show(names[cur+1]);
    if(e.key==='ArrowLeft'&&cur>0) show(names[cur-1]);
  });
  // accordions
  document.addEventListener('click',e=>{
    const h=e.target.closest('.acc-head'); if(!h) return;
    const it=h.closest('.acc-item'); it.classList.toggle('open'); h.setAttribute('aria-expanded', it.classList.contains('open'));
  });
  // tooltip for anything with data-tip
  const tip=document.createElement('div'); tip.id='tip'; document.body.appendChild(tip);
  document.addEventListener('mouseover',e=>{const el=e.target.closest('[data-tip]'); if(!el){tip.classList.remove('on');return;}
    tip.innerHTML=el.dataset.tip; tip.classList.add('on');});
  document.addEventListener('mousemove',e=>{if(!tip.classList.contains('on'))return;
    const w=tip.offsetWidth,h=tip.offsetHeight; let x=e.clientX+14,y=e.clientY+16;
    if(x+w>innerWidth-8)x=e.clientX-w-14; if(y+h>innerHeight-8)y=e.clientY-h-16; tip.style.left=x+'px'; tip.style.top=y+'px';});
  // count-up numbers and growing bars when a panel is shown
  function animate(scope){
    $$('[data-count]',scope).forEach(el=>{const to=+el.dataset.count, t0=performance.now(), d=900;
      (function f(t){const k=Math.min(1,(t-t0)/d), v=Math.round(to*(1-Math.pow(1-k,3))); el.textContent=v.toLocaleString(); if(k<1)requestAnimationFrame(f);})(t0);});
    $$('.bar>i[data-w]',scope).forEach(i=>{i.style.width='0';requestAnimationFrame(()=>requestAnimationFrame(()=>i.style.width=i.dataset.w+'%'));});
  }
  window.ADS_ANIMATE=animate;
  document.addEventListener('ads:tab',e=>animate($('#p-'+e.detail)));
  // copy buttons
  document.addEventListener('click',e=>{const b=e.target.closest('[data-copy]'); if(!b)return;
    const txt=b.dataset.copy; const done=()=>{const o=b.textContent;b.textContent='copied';setTimeout(()=>b.textContent=o,1200);};
    if(navigator.clipboard) navigator.clipboard.writeText(txt).then(done,done); else done();});
  window.addEventListener('DOMContentLoaded',()=>show(location.hash.slice(1)||names[0],false));
  if(document.readyState!=='loading') show(location.hash.slice(1)||names[0],false);
})();
"""

ICONS = {
    "overview": '<path d="M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z"/>',
    "leads": '<path d="M3 6h18M3 12h12M3 18h7"/><circle cx="18" cy="17" r="3"/><path d="m20.5 19.5 2 2"/>',
    "drive": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 15h.01M10 15h8M6 9h12"/>',
    "keys": '<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 8.7-8.7M17 6l2 2M14.5 8.5l2 2"/>',
    "time": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "all": '<path d="M4 5h16M4 10h16M4 15h16M4 20h10"/>',
    "how": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5v.7M12 17h.01"/>',
    "events": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "chev": '<path d="m9 6 6 6-6 6"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "print": '<path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="7"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "check": '<path d="m5 12 5 5L20 7"/>',
}


def icon(name, cls="ico"):
    return '<svg class="%s" viewBox="0 0 24 24" aria-hidden="true">%s</svg>' % (cls, ICONS.get(name, ""))
