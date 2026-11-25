// WCAG 2.x contrast audit for the psychtool prototype (Playwright).
// Text: >=4.5:1 normal, >=3:1 large (>=24px, or >=18.66px bold).
// Non-text (1.4.11): focus rings, selected-state indicators, form-control borders >=3:1.
const inPage = () => {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [v[0], v[1], v[2], v[3] === undefined ? 1 : v[3]]; };
  const over = (top, bot) => { const a = top[3]; return [0, 1, 2].map(i => top[i] * a + bot[i] * (1 - a)).concat(1); };
  const lum = c => { const f = x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = c => '#' + c.slice(0, 3).map(x => Math.round(x).toString(16).padStart(2, '0')).join('').toUpperCase();
  const effBg = el => { const layers = []; let img = false; for (let e = el; e && e.nodeType === 1; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.backgroundImage !== 'none') img = true; const c = parse(cs.backgroundColor); if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } } let bg = [255, 255, 255, 1]; for (let i = layers.length - 1; i >= 0; i--) bg = over(layers[i], bg); return { bg, img }; };
  const opac = el => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
  const path = el => { const out = []; for (let e = el; e && e !== document.body && out.length < 4; e = e.parentElement) { let s = e.tagName.toLowerCase(); if (e.id) s += '#' + e.id; else if (e.classList.length) s += '.' + [...e.classList].slice(0, 2).join('.'); out.unshift(s); } return out.join(' > '); };
  const vis = el => el.checkVisibility ? el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && el.getClientRects().length > 0 && !el.closest('.sr') : true;
  const textOf = el => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').replace(/\s+/g, ' ').trim();
  const measureText = (root, kind) => {
    const out = [];
    const els = [root, ...root.querySelectorAll('*')];
    for (const el of els) {
      if (['SCRIPT', 'STYLE', 'OPTION'].includes(el.tagName) || !vis(el)) continue;
      let t = textOf(el);
      if (!t && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) && el.type !== 'checkbox' && el.type !== 'file') t = el.tagName === 'SELECT' ? (el.selectedOptions[0] || {}).text || '' : el.value;
      if (!t) continue;
      const cs = getComputedStyle(el); const fg0 = parse(cs.color); const { bg, img } = effBg(el);
      const o = opac(el); const fg = over([fg0[0], fg0[1], fg0[2], fg0[3] * o], bg);
      const px = parseFloat(cs.fontSize), w = +cs.fontWeight; const large = px >= 24 || (px >= 18.66 && w >= 700);
      const r = ratio(fg, bg); const need = large ? 3 : 4.5;
      out.push({ kind, where: path(el), text: t.slice(0, 50), fg: hex(fg), bg: hex(bg), ratio: +r.toFixed(2), need, pass: r >= need, img, disabled: !!el.closest('[disabled]') });
      if (el.matches('input,textarea') && el.placeholder) { const pc = parse(getComputedStyle(el, '::placeholder').color) || fg0; const pr = ratio(over(pc, bg), bg); out.push({ kind: kind + ':placeholder', where: path(el), text: el.placeholder.slice(0, 40), fg: hex(pc), bg: hex(bg), ratio: +pr.toFixed(2), need: 4.5, pass: pr >= 4.5 }); }
    }
    return out;
  };
  return { parse, over, ratio, hex, effBg, path, vis, measureText };
};

const inject = p => p.evaluate(`window.__cc = window.__cc || (${inPage.toString()})()`);
async function audit(p, label) {
  await inject(p);
  return p.evaluate(([src, label]) => {
    const L = window.__cc;
    const out = L.measureText(document.body, label + ':text');
    for (const d of document.querySelectorAll('dialog[open]')) out.push(...L.measureText(d, label + ':dialog'));
    const ind = (el, colorStr, what) => { if (!el || !L.vis(el)) return; const c = L.parse(colorStr); if (!c) return; const { bg } = L.effBg(el.parentElement || el); const r = L.ratio(L.over(c, bg), bg); out.push({ kind: label + ':indicator', where: what + ' ' + L.path(el), fg: L.hex(c), bg: L.hex(bg), ratio: +r.toFixed(2), need: 3, pass: r >= 3 }); };
    const g = (el, prop) => getComputedStyle(el)[prop];
    document.querySelectorAll('.tab[aria-selected="true"],.rtab[aria-selected="true"]').forEach(e => ind(e, g(e, 'borderBottomColor'), 'selected tab underline'));
    document.querySelectorAll('.navbtn[aria-current="true"]').forEach(e => ind(e, innerWidth > 1100 ? g(e, 'borderLeftColor') : g(e, 'borderBottomColor'), 'current section bar'));
    document.querySelectorAll('.row.sel').forEach(e => ind(e, g(e, 'borderLeftColor'), 'selected evidence bar'));
    document.querySelectorAll('mark.hl').forEach(e => { const m = g(e, 'boxShadow').match(/rgba?\([^)]+\)/); if (m) ind(e, m[0], 'source highlight start bar'); });
    document.querySelectorAll('.sent.sel').forEach(e => { const m = g(e, 'boxShadow').match(/rgba?\([^)]+\)/); if (m) ind(e, m[0], 'selected sentence ring'); });
    document.querySelectorAll('input[type=text],select,textarea').forEach(e => { if (L.vis(e)) ind(e, g(e, 'borderTopColor'), 'form control border'); });
    return out;
  }, [inPage.toString(), label]);
}

async function interact(p, label) {
  await inject(p);
  const out = [];
  await p.emulateMedia({ reducedMotion: 'reduce' });
  const sels = ['.btn.primary', '.btn.onred', '.btn.dark', '.btn:not(.primary):not(.onred):not(.dark):not(.link):not([disabled])', '.btn.link', '.btn[disabled]', '.fbtn:not([aria-pressed="true"])', '.fbtn[aria-pressed="true"]', '.navbtn:not([aria-current="true"])', '.tab:not([aria-selected="true"])', '.rtab:not([aria-selected="true"])', '.matbtn', '.row:not(.sel)', '.sent:not(.sel)', '.cite', '.seg button', '.row select', '#caseSel'];
  for (const s of sels) {
    const loc = p.locator(s).filter({ visible: true }).first();
    if (!(await loc.count())) continue;
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    await loc.hover({ force: true, timeout: 2000 }).catch(() => {});
    await p.waitForTimeout(40);
    const r = await loc.evaluate((el, [src, label, s]) => { const L = window.__cc; return L.measureText(el, label + ':hover ' + s); }, [inPage.toString(), label, s]);
    out.push(...r);
  }
  await p.mouse.move(2, 2);
  // focus rings: keyboard Tab through the screen
  await p.evaluate(() => { document.activeElement && document.activeElement.blur(); });
  const seen = new Set();
  for (let i = 0; i < 90; i++) {
    await p.keyboard.press('Tab');
    const f = await p.evaluate(([src, label]) => {
      const L = window.__cc; const el = document.activeElement; if (!el || el === document.body) return null;
      const cs = getComputedStyle(el); const key = L.path(el) + '|' + (el.dataset.v || '') + '|' + el.textContent.slice(0, 20);
      const { bg } = L.effBg(el.parentElement); const own = L.effBg(el).bg;
      const res = { key, kind: label + ':focus', where: L.path(el) + (el.dataset.v ? '[' + el.dataset.v + ']' : ''), text: (el.innerText || el.value || '').slice(0, 40) };
      if (cs.outlineStyle === 'none' || parseFloat(cs.outlineWidth) < 1) return Object.assign(res, { ratio: 0, need: 3, pass: false, fg: 'none', bg: L.hex(bg) });
      const c = L.parse(cs.outlineColor); const off = parseFloat(cs.outlineOffset); const against = off > 0 ? bg : own;
      const r = L.ratio(L.over(c, against), against);
      const text = L.measureText(el, label + ':focused-text');
      return Object.assign(res, { fg: L.hex(c), bg: L.hex(against), ratio: +r.toFixed(2), need: 3, pass: r >= 3 && parseFloat(cs.outlineWidth) >= 2, text2: text });
    }, [inPage.toString(), label]);
    if (!f) continue; if (seen.has(f.key)) break; seen.add(f.key);
    const t2 = f.text2 || []; delete f.text2; delete f.key; out.push(f, ...t2);
  }
  await p.evaluate(() => document.activeElement && document.activeElement.blur());
  await p.emulateMedia({ reducedMotion: 'no-preference' });
  return out;
}

async function statusShapes(p) {
  return p.evaluate(() => {
    const mk = c => { const s = document.createElement('span'); s.className = 'tag ' + c; s.textContent = 'x'; document.body.appendChild(s); const cs = getComputedStyle(s), b = getComputedStyle(s, '::before'); const r = { glyph: b.content, border: cs.borderTopStyle, color: cs.color, bg: cs.backgroundColor }; s.remove(); return r; };
    return { verified: mk('ok'), needs: mk('chk'), unverified: mk('un') };
  });
}
module.exports = { audit, interact, statusShapes };
