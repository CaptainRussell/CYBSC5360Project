const { chromium } = require('playwright');
const R = '/home/user/CYBSC5360Project/tool/results/', OUT = process.argv[2];
(async () => {
  const b = await chromium.launch();
  for (const [file, tab, idx, out] of [['26Fall_Project2/briefing.html', 'overview', 5, 'ov_funnel.png'], ['26Fall_Project2_dates/briefing.html', 'overview', 4, 'dates_pattern.png']]) {
    const p = await b.newPage({ viewport: { width: 640, height: 1400 }, deviceScaleFactor: 3 });
    await p.goto('file://' + R + file); await p.waitForTimeout(1500);
    await p.click('.tab[data-tab="' + tab + '"]'); await p.waitForTimeout(2200);
    const el = (await p.$$('.panel.on .card'))[idx]; const bb = await el.boundingBox();
    await p.screenshot({ path: OUT + '/' + out, clip: { x: bb.x - 6, y: bb.y - 6, width: bb.width + 12, height: bb.height + 12 } });
    console.log(out, (await el.innerText()).slice(0, 50).replace(/\s+/g, ' '));
  }
  await b.close();
})();
