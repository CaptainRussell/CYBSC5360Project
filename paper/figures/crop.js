const { chromium } = require('playwright');
const R = '/home/user/CYBSC5360Project/tool/results/';
const OUT = process.argv[2];
async function page(b, file, tab) {
  const p = await b.newPage({ viewport: { width: 640, height: 1400 }, deviceScaleFactor: 3 });
  await p.goto('file://' + R + file); await p.waitForTimeout(1500);
  if (tab) { await p.click('.tab[data-tab="' + tab + '"]'); await p.waitForTimeout(2200); }
  return p;
}
async function clip(p, sels, out, pad = 6) {
  const boxes = [];
  for (const [sel, idx] of sels) { const els = await p.$$(sel); boxes.push(await els[idx].boundingBox()); }
  const x = Math.min(...boxes.map(b => b.x)) - pad, y = Math.min(...boxes.map(b => b.y)) - pad;
  const r = Math.max(...boxes.map(b => b.x + b.width)) + pad, btm = Math.max(...boxes.map(b => b.y + b.height)) + pad;
  await p.screenshot({ path: OUT + '/' + out, clip: { x, y, width: r - x, height: btm - y } });
  console.log(out, Math.round(r - x), 'x', Math.round(btm - y));
}
(async () => {
  const b = await chromium.launch();
  let p = await page(b, '26Fall_Project2/briefing.html', 'overview');
  await clip(p, [['.panel.on .grid.g4', 0]], 'ov_kpis.png');
  await clip(p, [['.panel.on .card', 6]], 'ov_funnel.png');
  p = await page(b, '26Fall_Project2/briefing.html', 'leads');
  await clip(p, [['.panel.on .acc-item', 0], ['.panel.on .acc-item', 4]], 'leads_top5.png');
  const items = await p.$$('.panel.on .acc-item'); await (await items[1].$('.acc-head, button, [role=button]') || items[1]).click(); await p.waitForTimeout(1200);
  await clip(p, [['.panel.on .acc-item', 1]], 'lead_open.png');
  p = await page(b, '26Fall_Project2/briefing.html', 'timeline');
  const tl = await p.$$eval('.panel.on .card, .panel.on .grid', els => els.map(e => e.className));
  console.log('timeline elements', tl);
  await clip(p, [['.panel.on .grid', 0], ['.panel.on .card:not(.kpi)', 0]], 'timeline.png');
  p = await page(b, '26Fall_Project2_dates/briefing.html', 'overview');
  const dl = await p.$$eval('.panel.on .card, .panel.on .grid, .panel.on [class*=pattern], .panel.on .alert, .panel.on .banner', els => els.map(e => e.className + ' | ' + e.innerText.slice(0, 40).replace(/\s+/g, ' ')));
  console.log('dates elements', dl.slice(0, 8));
  await b.close();
})();
