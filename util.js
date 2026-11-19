// Pure helpers (no DOM access) so they can be unit-tested with `node --test`.
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmtMs = (v) => (v == null || Number.isNaN(v) ? 'n/a' : v >= 10000 ? (v / 1000).toFixed(1) + ' s' : Math.round(v) + ' ms');
export const fmtBytes = (v) => (v == null ? 'n/a' : v >= 1048576 ? (v / 1048576).toFixed(2) + ' MB' : v >= 1024 ? Math.round(v / 1024) + ' KB' : v + ' B');
export const fmtPct = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(1) + '%');
export function median(xs) {
  const a = xs.filter((x) => x != null).sort((p, q) => p - q);
  if (!a.length) return null;
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
export function histogram(values, bins = 6) {
  const v = values.filter((x) => x != null);
  if (!v.length) return [];
  const lo = Math.min(...v), hi = Math.max(...v);
  if (lo === hi) return [{ from: lo, to: hi, count: v.length, label: Math.round(lo) + '' }];
  const w = (hi - lo) / bins;
  const out = Array.from({ length: bins }, (_, i) => ({ from: lo + i * w, to: lo + (i + 1) * w, count: 0 }));
  for (const x of v) out[Math.min(bins - 1, Math.floor((x - lo) / w))].count++;
  return out.map((b) => ({ ...b, label: `${Math.round(b.from)}–${Math.round(b.to)}` }));
}
// Direction of change for "lower is better" metrics: returns css class
export const deltaClass = (pct) => (pct == null || Math.abs(pct) < 1 ? 'flat' : pct < 0 ? 'good' : 'bad');
export const sevOrder = { critical: 0, high: 1, medium: 2, low: 3 };
export function timeAgo(iso, now = Date.now()) {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.round(s / 60) + 'm ago';
  if (s < 86400) return Math.round(s / 3600) + 'h ago';
  return Math.round(s / 86400) + 'd ago';
}
export const profileSummary = (p) =>
  `${p.download_kbps ? p.download_kbps + ' kbps down' : 'unlimited down'} · ${p.latency_ms || 0} ms latency · ${p.packet_loss_pct || 0}% loss (simulated) · ${p.cpu_slowdown || 1}x CPU`;
