const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ deviceScaleFactor: 4 });
  for (const f of process.argv.slice(2)) {
    await p.goto('file://' + require('path').resolve(f));
    await (await p.$('#fig')).screenshot({ path: f.replace('.html', '.png') });
  }
  await b.close();
})();
