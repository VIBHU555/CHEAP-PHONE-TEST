// Thin fetch wrapper. Throws Error(message) with the server's error message.
async function req(path, opts = {}) {
  const r = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) { const e = new Error(data?.error?.message || `HTTP ${r.status}`); e.status = r.status; e.code = data?.error?.code; throw e; }
  return data;
}
export const api = {
  health: () => req('/health'), stats: () => req('/stats'), targets: () => req('/targets'), profiles: () => req('/profiles'),
  workflows: () => req('/workflows'), runs: (q = '') => req('/runs' + q), run: (id) => req(`/runs/${id}`), report: (id) => req(`/runs/${id}/report`),
  startRun: (b) => req('/runs', { method: 'POST', body: JSON.stringify(b) }), cancel: (id) => req(`/runs/${id}/cancel`, { method: 'POST' }),
  del: (id) => req(`/runs/${id}`, { method: 'DELETE' }), compare: (a, b) => req(`/compare?a=${a}&b=${b}`),
  regen: (id, use_llm) => req(`/runs/${id}/report/regenerate`, { method: 'POST', body: JSON.stringify({ use_llm }) }),
  rules: () => req('/settings/rules'), saveRules: (r) => req('/settings/rules', { method: 'PUT', body: JSON.stringify(r) }), resetRules: () => req('/settings/rules/reset', { method: 'POST' }),
  addProfile: (p) => req('/profiles', { method: 'POST', body: JSON.stringify(p) }), delProfile: (id) => req(`/profiles/${id}`, { method: 'DELETE' }),
  demoMode: () => req('/demo/mode'), setDemoMode: (optimized) => req('/demo/mode', { method: 'POST', body: JSON.stringify({ optimized }) }),
};
