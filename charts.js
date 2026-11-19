// Dependency-free SVG chart builders. Each returns an HTML string; empty data returns an explicit empty state.
import { esc } from './util.js';

const W = 560, H = 220, PAD = { l: 52, r: 12, t: 12, b: 44 };
const empty = (msg) => `<div class="empty">${esc(msg || 'Not enough data yet.')}</div>`;
const niceMax = (m) => { if (m <= 0) return 1; const p = 10 ** Math.floor(Math.log10(m)); return Math.ceil(m / p) * p; };

function axes(max, fmt) {
  let s = '';
  for (let i = 0; i <= 4; i++) {
    const y = PAD.t + ((H - PAD.t - PAD.b) * (4 - i)) / 4;
    s += `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y}" y2="${y}" class="grid"/><text x="${PAD.l - 6}" y="${y + 4}" class="axl" text-anchor="end">${esc(fmt((max * i) / 4))}</text>`;
  }
  return s;
}

export function barChart(items, { title, fmt = (v) => String(Math.round(v)), colorFor } = {}) {
  const d = items.filter((i) => i.value != null);
  if (!d.length) return empty();
  const max = niceMax(Math.max(...d.map((i) => i.value)));
  const bw = (W - PAD.l - PAD.r) / d.length;
  let bars = '';
  d.forEach((it, i) => {
    const h = ((H - PAD.t - PAD.b) * it.value) / max, x = PAD.l + i * bw + bw * 0.18, y = H - PAD.b - h;
    bars += `<rect x="${x}" y="${y}" width="${bw * 0.64}" height="${h}" rx="3" fill="${it.color || (colorFor ? colorFor(it) : 'var(--accent)')}"><title>${esc(it.label)}: ${esc(fmt(it.value))}</title></rect>`
      + `<text x="${x + bw * 0.32}" y="${y - 4}" class="vl" text-anchor="middle">${esc(fmt(it.value))}</text>`
      + `<text x="${x + bw * 0.32}" y="${H - PAD.b + 16}" class="axl" text-anchor="middle">${esc(String(it.label).slice(0, 14))}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title || 'bar chart')}">${axes(max, fmt)}${bars}</svg>`;
}

export function groupedBars(rows, { title, fmt = (v) => String(Math.round(v)), names = ['Baseline', 'New'] } = {}) {
  const d = rows.filter((r) => r.a != null || r.b != null);
  if (!d.length) return empty();
  const max = niceMax(Math.max(...d.flatMap((r) => [r.a || 0, r.b || 0])));
  const gw = (W - PAD.l - PAD.r) / d.length;
  let s = '';
  d.forEach((r, i) => {
    [[r.a, 'var(--muted2)', 0], [r.b, 'var(--accent)', 1]].forEach(([v, col, k]) => {
      if (v == null) return;
      const h = ((H - PAD.t - PAD.b) * v) / max, x = PAD.l + i * gw + gw * (0.12 + k * 0.38), y = H - PAD.b - h;
      s += `<rect x="${x}" y="${y}" width="${gw * 0.36}" height="${h}" rx="3" fill="${col}"><title>${esc(r.label)} ${names[k]}: ${esc(fmt(v))}</title></rect>`;
    });
    s += `<text x="${PAD.l + i * gw + gw / 2}" y="${H - PAD.b + 16}" class="axl" text-anchor="middle">${esc(String(r.label).slice(0, 16))}</text>`;
  });
  const legend = `<g class="axl"><rect x="${W - 190}" y="2" width="10" height="10" fill="var(--muted2)"/><text x="${W - 176}" y="11">${names[0]}</text><rect x="${W - 100}" y="2" width="10" height="10" fill="var(--accent)"/><text x="${W - 86}" y="11">${names[1]}</text></g>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title || 'comparison chart')}">${axes(max, fmt)}${s}${legend}</svg>`;
}

export function lineChart(points, { title, fmt = (v) => String(Math.round(v)) } = {}) {
  // points: [{label, value, color?, tip?}] in chronological order
  const d = points.filter((p) => p.value != null);
  if (d.length < 2) return empty('At least two completed runs are needed for a trend.');
  const max = niceMax(Math.max(...d.map((p) => p.value)));
  const step = (W - PAD.l - PAD.r) / (d.length - 1);
  const xy = d.map((p, i) => [PAD.l + i * step, H - PAD.b - ((H - PAD.t - PAD.b) * p.value) / max]);
  const path = xy.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const dots = xy.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="4.5" fill="${d[i].color || 'var(--accent)'}"><title>${esc(d[i].tip || d[i].label)}: ${esc(fmt(d[i].value))}</title></circle>`).join('');
  const every = Math.ceil(d.length / 8);
  const labels = d.map((p, i) => (i % every ? '' : `<text x="${xy[i][0]}" y="${H - PAD.b + 16}" class="axl" text-anchor="middle">${esc(String(p.label).slice(0, 10))}</text>`)).join('');
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title || 'trend')}">${axes(max, fmt)}<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>${dots}${labels}</svg>`;
}

export function donut(items, { title } = {}) {
  const tot = items.reduce((a, i) => a + i.value, 0);
  if (!tot) return empty();
  const R = 60, C = 2 * Math.PI * R;
  let off = 0, arcs = '';
  for (const it of items.filter((i) => i.value > 0)) {
    const len = (it.value / tot) * C;
    arcs += `<circle r="${R}" cx="80" cy="80" fill="none" stroke="${it.color}" stroke-width="26" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 80 80)"><title>${esc(it.label)}: ${it.value}</title></circle>`;
    off += len;
  }
  const legend = items.map((it) => `<li><span class="dot" style="background:${it.color}"></span>${esc(it.label)} <b>${it.value}</b></li>`).join('');
  return `<div class="donut"><svg viewBox="0 0 160 160" width="160" height="160" role="img" aria-label="${esc(title || 'donut')}">${arcs}<text x="80" y="86" text-anchor="middle" class="big">${tot}</text></svg><ul class="legend">${legend}</ul></div>`;
}
