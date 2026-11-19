import { api } from './api.js';
import * as C from './charts.js';
import { esc, fmtMs, fmtBytes, fmtPct, median, histogram, deltaClass, timeAgo, profileSummary } from './util.js';

const main = document.getElementById('main');
let timers = [];
const SEV_COLORS = { critical: 'var(--crit)', high: 'var(--high)', medium: 'var(--med)', low: 'var(--low)' };
const PALETTE = ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f472b6', '#fb923c'];

function toast(msg, isErr) {
  const t = document.getElementById('toast');
  const d = document.createElement('div');
  if (isErr) d.className = 'err';
  d.textContent = msg;
  t.appendChild(d);
  setTimeout(() => d.remove(), isErr ? 8000 : 4000);
}
const badge = (txt, cls) => `<span class="badge b-${esc(cls || txt)}">${esc(txt)}</span>`;
const modeBadge = (m) => (m && typeof m.optimized === 'boolean' ? `<span class="badge b-low" title="Demo app mode recorded when the test started">demo app: ${m.optimized ? 'optimized' : 'unoptimized'}</span>` : '');
const stat = (l, v, cls = '') => `<div class="card stat ${cls}"><div class="l">${esc(l)}</div><div class="v">${v}</div></div>`;
const runName = (r) => esc(r.label || `${r.profile?.name || r.profile} · ${r.workflow_id}`);
const when = (iso) => `<span title="${esc(iso)}">${new Date(iso).toLocaleString()} <small class="m">(${timeAgo(iso)})</small></span>`;
const errBox = (e) => `<div class="notice err" role="alert"><b>Something went wrong.</b> ${esc(e.message || e)}</div>`;
const download = (path) => `/api${path}`;

function setTitle(h1, sub) { return `<div><h1>${h1}</h1><p class="sub">${sub || ''}</p></div>`; }

// ------------------------------------------------------------------ router
const routes = [
  [/^\/?$/, 'dashboard', dashboard], [/^\/new$/, 'new', newTest], [/^\/runs\/([\w]+)\/execution$/, 'new', execution],
  [/^\/runs\/([\w]+)\/report$/, 'history', report], [/^\/runs\/([\w]+)$/, 'history', results], [/^\/compare$/, 'compare', compare],
  [/^\/history$/, 'history', history], [/^\/settings$/, 'settings', settings],
];
async function route() {
  timers.forEach(clearInterval); timers = [];
  const [path, qs] = (location.hash.slice(1) || '/').split('?');
  const q = Object.fromEntries(new URLSearchParams(qs || ''));
  for (const [re, nav, fn] of routes) {
    const m = path.match(re);
    if (m) {
      document.querySelectorAll('#nav a').forEach((a) => (a.dataset.r === nav ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
      main.innerHTML = '<p class="muted">Loading…</p>';
      try { await fn(m[1], q); } catch (e) { main.innerHTML = errBox(e); }
      main.focus({ preventScroll: true });
      return;
    }
  }
  main.innerHTML = setTitle('Not found', 'That page does not exist.') + '<a class="btn" href="#/">Go to dashboard</a>';
}
document.querySelector('.skip').addEventListener('click', (e) => { e.preventDefault(); main.focus(); });  // don't let '#main' hit the hash router
window.addEventListener('hashchange', route);
window.addEventListener('load', route);

// ------------------------------------------------------------------ dashboard
async function dashboard() {
  const [s, h] = await Promise.all([api.stats(), api.health()]);
  const profIdx = {}; s.trend.forEach((t) => { if (!(t.profile_id in profIdx)) profIdx[t.profile_id] = Object.keys(profIdx).length; });
  const trendPts = s.trend.map((t, i) => ({ label: '#' + (i + 1), value: t.slowest_page_load_ms, color: PALETTE[profIdx[t.profile_id] % PALETTE.length],
    tip: `#${i + 1} ${t.profile}${t.optimized === true ? ' (optimized app)' : t.optimized === false ? ' (unoptimized app)' : ''}` }));
  const legend = Object.keys(profIdx).map((pid) => { const t = s.trend.find((x) => x.profile_id === pid); return `<span><span class="dot" style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${PALETTE[profIdx[pid] % PALETTE.length]}"></span> ${esc(t.profile)}</span>`; }).join(' &nbsp; ');
  const CAT = { step_failed: 'step failed', http_error: 'HTTP error', network_failure: 'network', simulated_fault: 'simulated', js_error: 'JS error' };
  const cats = Object.entries(s.failure_categories).map(([k, v]) => ({ label: CAT[k] || k, value: v }));
  const recent = s.recent.map((r) => `<tr><td><a href="#/runs/${r.id}">${runName(r)}</a></td><td>${esc(r.profile)}</td><td>${badge(r.verdict || r.status)}</td>
    <td>${r.issue_counts ? Object.entries(r.issue_counts).filter(([, v]) => v).map(([k, v]) => `${badge(k)} ${v}`).join(' ') || '<span class="good">none</span>' : '—'}</td><td>${when(r.created_at)}</td></tr>`).join('');
  main.innerHTML = `<div class="row spread">${setTitle('Dashboard', 'All figures below are computed from test runs stored in this installation — nothing is pre-filled.')}<a class="btn" href="#/new">Start a new test</a></div>
  ${!s.total_runs ? `<div class="notice">No test runs yet. Start the demo app (<code>python demo-app/server.py</code>) and run your first test from <a href="#/new">New Test</a>.</div>` : ''}
  <div class="grid g4" style="margin-bottom:14px">${stat('Tests executed', s.total_runs)}${stat('Passed', s.passed, 'good')}${stat('Failed', s.failed, s.failed ? 'bad' : '')}${stat('Issues identified', s.total_issues)}</div>
  <div class="grid g2"><div class="card"><h2>Test outcomes</h2>${C.donut([{ label: 'Passed', value: s.passed, color: 'var(--good)' }, { label: 'Failed (issues found)', value: s.failed, color: 'var(--bad)' }, { label: 'Could not execute', value: s.failed_to_execute, color: 'var(--muted2)' }], { title: 'Test outcomes' })}
    <p class="muted" style="margin:8px 0 0">A run fails if a core step cannot complete or any ${esc('critical/high')} issue is found (configurable rule).</p></div>
  <div class="card"><h2>Issues by severity</h2>${C.barChart(['critical', 'high', 'medium', 'low'].map((k) => ({ label: k, value: s.issues[k], color: SEV_COLORS[k] })), { title: 'Issues by severity' })}</div>
  <div class="card"><h2>Performance trend — slowest page load (median) per run</h2>${C.lineChart(trendPts, { title: 'Median page load per run', fmt: (v) => fmtMs(v) })}<p class="muted" style="margin:6px 0 0">${legend}<br>Points from different profiles are not like-for-like; hover a point for its profile.</p></div>
  <div class="card"><h2>Failure categories (all runs)</h2>${C.barChart(cats, { title: 'Failure categories' })}</div></div>
  <div class="card"><h2>Recent reports</h2>${recent ? `<div class="tw"><table><thead><tr><th>Run</th><th>Profile</th><th>Result</th><th>Issues</th><th>When</th></tr></thead><tbody>${recent}</tbody></table></div>` : '<div class="empty">No reports yet.</div>'}</div>
  <p class="muted">Engine: Playwright + Chromium · LLM explanations: ${h.llm_configured ? 'configured' : 'not configured (deterministic reports are used)'} · Active runs: ${h.active_runs}</p>`;
}

// ------------------------------------------------------------------ new test
async function newTest(_, q) {
  const [targets, profiles, workflows, h] = await Promise.all([api.targets(), api.profiles(), api.workflows(), api.health()]);
  const opt = (arr, sel, f) => arr.map((x) => `<option value="${esc(x.id)}" ${x.id === sel ? 'selected' : ''}>${esc(f(x))}</option>`).join('');
  main.innerHTML = `${setTitle('New Test', 'Configure a reproducible browser test. Network and CPU settings are <b>test configurations</b>, not representations of any specific phone or carrier.')}
  <form id="f" class="grid g2" novalidate>
   <div class="card"><h2>1. Target &amp; workflow</h2>
    <div class="field"><label for="t">Target application</label><select id="t">${opt(targets, q.target, (t) => t.name + ' — ' + t.url)}</select><div class="hint" id="tmeta"></div></div>
    <div class="field"><label for="w">Test workflow</label><select id="w"></select><div class="hint" id="wdesc"></div></div>
    <div class="field"><label for="r">Repetitions (1–10)</label><input id="r" type="number" min="1" max="10" value="${esc(q.reps || 3)}"><div class="hint">Each repetition uses a fresh browser context; findings use all repetitions (e.g. “exceeded in 3 of 3 attempts”).</div></div>
    <div class="field"><label for="l">Label (optional)</label><input id="l" maxlength="80" placeholder="e.g. before optimisation" value="${esc(q.label || '')}"></div></div>
   <div class="card"><h2>2. Testing profile</h2>
    <div class="field"><label for="p">Profile</label><select id="p">${opt(profiles, q.profile || 'standard', (p) => p.name)}</select></div>
    <div id="pdesc"></div>
    <div class="notice warn" style="margin-top:12px">Enforcement: bandwidth and latency use Chromium's DevTools network emulation; CPU slowdown uses DevTools CPU throttling; packet loss is <b>simulated</b> by aborting a share of requests. If a requested constraint cannot be applied, the run fails instead of silently running unconstrained.</div>
    <div class="row" style="margin-top:12px"><button class="btn" id="go" type="submit">Start test</button><a class="btn sec" href="#/settings">Edit profiles</a></div>
    ${h.active_runs ? '<p class="bad">A test is already running; wait for it to finish.</p>' : ''}</div>
  </form>`;
  const $ = (id) => document.getElementById(id);
  const refresh = () => {
    const t = targets.find((x) => x.id === $('t').value);
    $('tmeta').innerHTML = esc(t.description) + (t.meta && typeof t.meta.optimized === 'boolean' ? ` Current demo-app mode: <b>${t.meta.optimized ? 'optimized' : 'unoptimized (deliberate faults on)'}</b>.` : t.meta?.unavailable ? ' <span class="bad">Target is not reachable.</span>' : '');
    const ws = workflows.filter((w) => t.workflows.includes(w.id));
    $('w').innerHTML = opt(ws, q.workflow || (ws.find((w) => w.id === 'shop_checkout') ? 'shop_checkout' : ws[0].id), (w) => w.name);
    wd();
    const p = profiles.find((x) => x.id === $('p').value);
    $('pdesc').innerHTML = `<table><tbody><tr><th>Download</th><td>${p.download_kbps ? p.download_kbps + ' kbps' : 'unrestricted'}</td></tr><tr><th>Upload</th><td>${p.upload_kbps ? p.upload_kbps + ' kbps' : 'unrestricted'}</td></tr>
      <tr><th>Added latency</th><td>${p.latency_ms} ms</td></tr><tr><th>Packet loss</th><td>${p.packet_loss_pct}% <small class="m">(simulated fault injection)</small></td></tr><tr><th>CPU slowdown</th><td>${p.cpu_slowdown}x <small class="m">(relative to this machine)</small></td></tr><tr><th>Step timeout</th><td>${p.step_timeout_ms} ms</td></tr></tbody></table><p class="muted">${esc(p.description)}</p>`;
  };
  const wd = () => { const w = workflows.find((x) => x.id === $('w').value); $('wdesc').innerHTML = esc(w.description) + '<ol class="tight">' + w.steps.map((s) => `<li>${esc(s.name)} ${s.core ? '' : '<small class="m">(non-core)</small>'}</li>`).join('') + '</ol>'; };
  $('t').onchange = refresh; $('p').onchange = refresh; $('w').onchange = wd; refresh();
  $('f').onsubmit = async (e) => {
    e.preventDefault();
    const reps = parseInt($('r').value, 10);
    if (!(reps >= 1 && reps <= 10)) return toast('Repetitions must be between 1 and 10.', true);
    $('go').disabled = true;
    try { const r = await api.startRun({ target_id: $('t').value, profile_id: $('p').value, workflow_id: $('w').value, repetitions: reps, label: $('l').value }); location.hash = `#/runs/${r.id}/execution`; }
    catch (err) { toast(err.message, true); $('go').disabled = false; }
  };
}

// ------------------------------------------------------------------ execution
async function execution(id) {
  const draw = async () => {
    const { run, steps } = await api.run(id);
    const p = run.progress || { events: [], done: 0, total: 0 };
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    const live = run.status === 'running' || run.status === 'queued';
    main.innerHTML = `<div class="row spread">${setTitle('Test Execution', `${runName(run)} · ${esc(run.target_url)} ${modeBadge(run.target_meta)}`)}${badge(run.status)}</div>
    <div class="card"><div class="row spread"><b>${p.done} / ${p.total} step executions</b><span>${pct}%</span></div><div class="progress" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${pct}%"></i></div>
     <div class="row" style="margin-top:12px">${live ? '<button class="btn danger" id="cx">Cancel test</button>' : ''}${run.status === 'completed' ? `<a class="btn" href="#/runs/${id}">View results</a><a class="btn sec" href="#/runs/${id}/report">Open diagnostic report</a>` : ''}${run.status === 'failed' || run.status === 'cancelled' ? '<a class="btn sec" href="#/new">Configure another test</a>' : ''}</div>
     ${run.error ? `<div class="notice err" style="margin-top:12px" role="alert">${esc(run.error)}</div>` : ''}</div>
    <div class="card"><h2>Step results so far</h2>${steps.length ? `<div class="stepline">${steps.map((s) => `<div class="${s.status}"><b>rep ${s.repetition}</b> · ${esc(s.step_name)}<br>${badge(s.status)} ${fmtMs(s.duration_ms)}</div>`).join('')}</div>` : '<div class="empty">Waiting for the first step…</div>'}</div>
    <div class="card"><h2>Execution log</h2><div class="log" id="log">${p.events.map((e) => `${esc(e.t.slice(11, 23))}  ${esc(e.msg)}`).join('<br>') || 'Queued…'}</div></div>`;
    const cx = document.getElementById('cx'); if (cx) cx.onclick = async () => { await api.cancel(id); toast('Cancellation requested; stops after the current step.'); };
    const log = document.getElementById('log'); log.scrollTop = log.scrollHeight;
    if (!live) { timers.forEach(clearInterval); timers = []; if (run.status === 'completed') timers.push(setTimeout(() => { if (location.hash.includes('execution')) location.hash = `#/runs/${id}`; }, 2500)); }
  };
  await draw();
  timers.push(setInterval(() => draw().catch(() => {}), 1000));
}

// ------------------------------------------------------------------ results
const rows = (arr) => arr.join('');
async function results(id) {
  const d = await api.run(id); const r = d.run, s = r.summary;
  if (r.status !== 'completed') { location.hash = `#/runs/${id}/execution`; return; }
  const completed = (await api.runs('?status=completed')).filter((x) => x.id !== id);
  const enf = (r.environment?.enforcement || []).map((e) => `<tr><td>${esc(e.setting)}</td><td>${esc(e.requested ?? '—')}</td><td>${badge(e.status)}</td><td>${esc(e.method || '—')}${e.verification ? `<br><small class="m">verification: ${esc(e.verification)}${e.observed_max_kbps ? ` (observed max ${e.observed_max_kbps} kbps)` : ''}</small>` : ''}</td></tr>`);
  const findings = d.findings.map((f) => `<tr><td>${badge(f.severity)}</td><td><a href="#/runs/${id}/report">${esc(f.title)}</a><br><small class="m">${esc(f.rule_id)} · ${esc(f.operation)}</small></td></tr>`);
  const pages = Object.entries(s.by_page).map(([p, m]) => `<tr><td class="mono">${esc(p)}</td><td class="num">${fmtMs(m.dcl_ms)}</td><td class="num">${fmtMs(m.load_ms)}</td><td class="num">${fmtMs(m.fcp_ms)}</td><td class="num">${fmtMs(m.lcp_ms)}</td><td class="num">${fmtBytes(m.transfer_bytes)}</td><td class="num">${m.samples}</td></tr>`);
  const eps = Object.entries(s.by_endpoint).map(([e, m]) => `<tr><td class="mono">${esc(e)}</td><td class="num">${fmtMs(m.median_ms)}</td><td class="num">${fmtMs(m.p95_ms)}</td><td class="num">${m.median_server_ms != null ? fmtMs(m.median_server_ms) : 'n/a'}</td><td class="num">${fmtBytes(m.median_bytes)}</td><td class="num">${m.failed}</td><td class="num">${m.samples}</td></tr>`);
  const stepRows = d.steps.map((x) => `<tr><td>${x.repetition}</td><td>${esc(x.step_name)} ${x.core ? '' : '<small class="m">(non-core)</small>'}</td><td>${badge(x.status)}</td><td class="num">${fmtMs(x.duration_ms)}</td><td>${esc(x.error || '')}${x.pending ? `<br><small class="m">pending: ${esc(x.pending.join(', '))}</small>` : ''}</td></tr>`);
  const hist = histogram(s.latencies_ms || [], 6).map((b) => ({ label: b.label, value: b.count }));
  const CAT = { step_failed: 'step failed', http_error: 'HTTP error', network_failure: 'network', simulated_fault: 'simulated', js_error: 'JS error' };
  const cats = Object.entries(s.failure_categories).map(([k, v]) => ({ label: CAT[k] || k, value: v }));
  const loads = Object.entries(s.by_page).map(([p, m]) => ({ label: p, value: m.load_ms }));
  main.innerHTML = `<div class="row spread">${setTitle(`Test Results — ${runName(r)}`, `${esc(r.target_url)} · workflow <code>${esc(r.workflow_id)}</code> · ${r.repetitions} repetition(s) · ${when(r.created_at)}`)}
   <div class="row">${badge(r.verdict)} ${modeBadge(r.target_meta)}</div></div>
  <div class="row" style="margin-bottom:14px"><a class="btn" href="#/runs/${id}/report">Open AI diagnostic report</a>
   <a class="btn sec" href="${download(`/runs/${id}/export?format=json`)}" download>Export JSON</a>
   <label class="row" style="margin:0"><span class="sr" style="position:absolute;left:-999px">CSV part</span><select id="csvp" style="width:auto"><option>findings</option><option>requests</option><option>steps</option><option>page_metrics</option><option>js_errors</option></select></label>
   <a class="btn sec" id="csv" href="#" download>Export CSV</a><span class="btn sec off" title="Not implemented in this prototype" aria-disabled="true">PDF export (unavailable)</span>
   <span style="flex:1"></span><label class="row" style="margin:0"><span style="position:absolute;left:-999px">Compare with</span><select id="cmp" style="width:auto"><option value="">Compare with…</option>${completed.map((x) => `<option value="${x.id}">${esc(x.label || x.profile.name)} · ${new Date(x.created_at).toLocaleString()}</option>`).join('')}</select></label>
   <button class="btn sec" id="cmpgo">Compare (selected = baseline)</button><button class="btn danger" id="del">Delete run</button></div>
  <div class="grid g4" style="margin-bottom:14px">${stat('Step executions passed', `${s.steps_passed}/${s.steps_total}`, s.steps_failed ? 'bad' : 'good')}${stat('Median page load', fmtMs(s.median_load_ms))}${stat('Median API latency', fmtMs(s.median_api_ms))}${stat('Failed requests', s.failed_requests, s.failed_requests ? 'bad' : '')}${stat('JavaScript errors', s.js_errors, s.js_errors ? 'bad' : '')}${stat('Issues', Object.values(s.issue_counts).reduce((a, b) => a + b, 0))}</div>
  <div class="card"><h2>Test conditions &amp; enforcement</h2><p class="muted">Profile: <b>${esc(r.profile.name)}</b> — ${esc(profileSummary(r.profile))}. These are example test configurations.</p>
   <div class="tw"><table><thead><tr><th>Setting</th><th>Requested</th><th>Status</th><th>Method / verification</th></tr></thead><tbody>${rows(enf)}</tbody></table></div>
   <p class="muted">${esc(r.environment?.browser || '')} · ${esc(r.environment?.viewport || '')} · requests blocked by origin safeguard: ${r.environment?.blocked_requests ?? 0}</p></div>
  <div class="card"><h2>Findings (${d.findings.length})</h2>${findings.length ? `<table><tbody>${rows(findings)}</tbody></table>` : '<div class="empty">No issues found by the configured rules.</div>'}</div>
  <div class="grid g3"><div class="card"><h2>API latency distribution</h2>${C.barChart(hist, { title: 'API latency distribution (ms)' })}<small class="m">Browser-measured, ${s.latencies_ms.length} requests (ms ranges)</small></div>
   <div class="card"><h2>Failure categories</h2>${C.barChart(cats, { title: 'Failure categories' })}</div>
   <div class="card"><h2>Page load by path (median)</h2>${C.barChart(loads, { title: 'Page load by path', fmt: (v) => fmtMs(v) })}</div></div>
  <div class="card"><h2>Page metrics (median across repetitions)</h2><div class="tw"><table><thead><tr><th>Path</th><th class="num">DOMContentLoaded</th><th class="num">Load</th><th class="num">FCP</th><th class="num">LCP</th><th class="num">Transferred</th><th class="num">Samples</th></tr></thead><tbody>${rows(pages)}</tbody></table></div>
   <p class="muted">Source: browser Navigation/Paint Timing APIs. “n/a” means the browser did not report the metric for that page (e.g. no paint on a JSON page).</p></div>
  <div class="card"><h2>API requests</h2>${eps.length ? `<div class="tw"><table><thead><tr><th>Endpoint</th><th class="num">Median (browser)</th><th class="num">p95</th><th class="num">Server time (header)</th><th class="num">Size</th><th class="num">Failed</th><th class="num">Samples</th></tr></thead><tbody>${rows(eps)}</tbody></table></div>` : '<div class="empty">No API requests in this workflow.</div>'}
   <p class="muted">Browser latency and server-reported time (<code>X-Server-Time-Ms</code>) are separate measurements; “n/a” when the target does not send the header.</p></div>
  <div class="card"><h2>Step results</h2><div class="tw"><table><thead><tr><th>Rep</th><th>Step</th><th>Status</th><th class="num">Duration</th><th>Error</th></tr></thead><tbody>${rows(stepRows)}</tbody></table></div></div>`;
  const csvA = document.getElementById('csv'); const upd = () => (csvA.href = download(`/runs/${id}/export?format=csv&part=${document.getElementById('csvp').value}`)); upd(); document.getElementById('csvp').onchange = upd;
  document.getElementById('cmpgo').onclick = () => { const v = document.getElementById('cmp').value; v ? (location.hash = `#/compare?a=${v}&b=${id}`) : toast('Pick a run to compare with.', true); };
  document.getElementById('del').onclick = async () => { if (confirm('Delete this run and its report permanently?')) { await api.del(id); location.hash = '#/history'; } };
}

// ------------------------------------------------------------------ report
async function report(id) {
  const [{ report: rep, run }, h] = await Promise.all([api.report(id), api.health()]);
  const demo = run.target_meta && typeof run.target_meta.optimized === 'boolean';
  const items = rep.findings.map((f) => `<details class="f" open><summary>${badge(f.severity)} <b>${esc(f.title)}</b> <small class="m">${esc(f.operation)}</small></summary><div class="body">
    <div class="cols"><div><h3>Observation ${badge('measured')}</h3><p>${esc(f.observation)} <small class="m">${esc(f.observation_status)}</small></p>
      <h3>Evidence</h3><ul class="tight">${f.evidence.map((e) => `<li>${badge(e.kind)} <small>${esc(e.text)}</small></li>`).join('')}</ul>
      <h3>Reproduction steps</h3><ol class="tight">${f.reproduction_steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol></div>
     <div><h3>Possible causes <small class="m">(not confirmed unless marked measured)</small></h3><ul class="tight">${f.possible_causes.map((c) => `<li>${badge(c.basis)} <small class="m">confidence: ${esc(c.confidence)}</small><br>${esc(c.text)}</li>`).join('') || '<li class="muted">None derived from the collected evidence.</li>'}</ul>
      <h3>Recommended next investigation</h3><ul class="tight">${f.recommended_investigation.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>
      <p class="muted"><b>Confidence:</b> ${esc(f.confidence_note)}</p>
      ${f.ai_explanation ? `<div class="notice"><b>${esc(f.ai_explanation.label)}</b><br>${esc(f.ai_explanation.text)}${f.ai_explanation.additional_hypotheses.length ? '<ul class="tight">' + f.ai_explanation.additional_hypotheses.map((x) => `<li>${esc(x)}</li>`).join('') + '</ul>' : ''}</div>` : ''}</div></div></div></details>`).join('');
  main.innerHTML = `<div class="row spread">${setTitle('AI Diagnostic Report', `${runName(run)} · generator: <b>${esc(rep.generator)}</b> · ${esc(rep.generated_at)}`)}<div class="row">${badge(run.verdict)} ${modeBadge(run.target_meta)}</div></div>
  <div class="notice ${run.verdict === 'failed' ? 'err' : ''}"><b>${esc(rep.headline)}</b></div>
  ${rep.ai_summary ? `<div class="notice"><b>${esc(rep.ai_summary.label)}</b><br>${esc(rep.ai_summary.text)}</div>` : ''}
  <div class="row" style="margin-bottom:14px"><a class="btn sec" href="#/runs/${id}">Back to results</a>
   <button class="btn sec" id="regen">Regenerate (deterministic)</button>
   <button class="btn sec" id="llm" ${h.llm_configured ? '' : 'disabled title="Set ANTHROPIC_API_KEY on the server to enable"'}>Add LLM explanations${h.llm_configured ? '' : ' (unavailable: no API key)'}</button>
   ${demo ? `<button class="btn sec" id="opt">${run.target_meta.optimized ? 'Revert demo app to unoptimized' : 'Apply sample optimization to demo app'}</button>` : ''}
   <a class="btn" href="#/new?profile=${esc(run.profile.id)}&workflow=${esc(run.workflow_id)}&label=${encodeURIComponent('re-run')}">Re-run this test</a></div>
  ${rep.llm.status === 'error' ? `<div class="notice warn">LLM step failed (${esc(rep.llm.detail)}); showing the deterministic report.</div>` : ''}
  <div class="card"><h2>How to read this report</h2><div class="row">${Object.entries(rep.legend).map(([k, v]) => `<div style="flex:1;min-width:220px">${badge(k)}<br><small class="muted">${esc(v)}</small></div>`).join('')}</div>
   <p class="muted">Severity comes from the documented rules in Settings — never from an LLM.</p></div>
  <h2>Findings (${rep.findings.length})</h2>${items || '<div class="empty">No issues were found under the configured rules.</div>'}
  <div class="card"><h2>What was and was not measured</h2><div class="cols"><div><h3>Conditions</h3><ul class="tight">${(rep.measurement_notes.enforcement || []).map((e) => `<li>${esc(e.setting)} = ${esc(e.requested ?? '—')}: ${badge(e.status)} ${esc(e.method || '')}${e.verification ? `<br><small class="m">${esc(e.verification)}</small>` : ''}</li>`).join('')}</ul><ul class="tight">${rep.measurement_notes.environment.filter(Boolean).map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>
   <div><h3>Not measured by this tool</h3><ul class="tight">${rep.measurement_notes.not_measured.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div></div></div>`;
  document.getElementById('regen').onclick = async () => { await api.regen(id, false); toast('Report regenerated.'); report(id); };
  document.getElementById('llm').onclick = async () => { try { await api.regen(id, true); toast('LLM explanations added.'); report(id); } catch (e) { toast(e.message, true); } };
  const o = document.getElementById('opt');
  if (o) o.onclick = async () => { try { await api.setDemoMode(!run.target_meta.optimized); toast(run.target_meta.optimized ? 'Demo app reverted (unoptimized).' : 'Sample optimization applied to the demo app. Re-run the same test to compare.'); location.hash = `#/new?profile=${run.profile.id}&workflow=${run.workflow_id}&label=${encodeURIComponent(run.target_meta.optimized ? 're-run (unoptimized)' : 'after optimization')}`; } catch (e) { toast(e.message, true); } };
}

// ------------------------------------------------------------------ compare
const dcell = (d, fmt, lowerBetter = true) => d ? `<td class="num">${fmt(d.baseline)}</td><td class="num">${fmt(d.new)}</td><td class="num ${lowerBetter ? deltaClass(d.pct) : 'flat'}">${d.abs == null ? '—' : (d.abs > 0 ? '+' : '') + (fmt === fmtBytes ? fmtBytes(Math.abs(d.abs)).replace(/^/, d.abs < 0 ? '-' : '') : Math.round(d.abs))}</td><td class="num ${deltaClass(d.pct)}">${fmtPct(d.pct)}</td>` : '<td colspan="4"></td>';
async function compare(_, q) {
  const completed = await api.runs('?status=completed');
  const o = (sel) => `<option value="">Select…</option>` + completed.map((x) => `<option value="${x.id}" ${x.id === sel ? 'selected' : ''}>${esc(x.label || x.profile.name)} · ${esc(x.profile.name)} · ${new Date(x.created_at).toLocaleString()} · ${x.id}</option>`).join('');
  main.innerHTML = `${setTitle('Run Comparison', 'Compare a baseline run with a new run of the same target and workflow. Percent change is shown only where the baseline is non-zero.')}
  <div class="card"><div class="row"><div style="flex:1;min-width:260px"><label for="ca">Baseline run</label><select id="ca">${o(q.a)}</select></div><div style="flex:1;min-width:260px"><label for="cb">New run</label><select id="cb">${o(q.b)}</select></div><div style="align-self:end"><button class="btn" id="go">Compare</button></div></div></div><div id="out"></div>`;
  const go = async () => {
    const a = document.getElementById('ca').value, b = document.getElementById('cb').value, out = document.getElementById('out');
    if (!a || !b) { out.innerHTML = completed.length < 2 ? '<div class="empty">You need at least two completed runs to compare.</div>' : '<div class="empty">Select two runs.</div>'; return; }
    try {
      const c = await api.compare(a, b);
      const pg = Object.entries(c.pages), ep = Object.entries(c.endpoints);
      out.innerHTML = `${c.warnings.map((w) => `<div class="notice warn" role="alert"><b>Warning:</b> ${esc(w)}</div>`).join('')}${c.notes.map((w) => `<div class="notice">${esc(w)}</div>`).join('')}
      <div class="grid g2"><div class="card"><h3>Baseline</h3>${esc(c.baseline.label || '')} ${badge(c.baseline.verdict)} ${modeBadge(c.baseline.target_meta)}<br><small class="m">${esc(c.baseline.profile)} · <a href="#/runs/${c.baseline.id}">open</a></small></div>
       <div class="card"><h3>New</h3>${esc(c.new.label || '')} ${badge(c.new.verdict)} ${modeBadge(c.new.target_meta)}<br><small class="m">${esc(c.new.profile)} · <a href="#/runs/${c.new.id}">open</a></small></div></div>
      <div class="grid g2" style="margin-top:14px"><div class="card"><h2>Page load (median): baseline vs new</h2>${C.groupedBars(pg.map(([p, m]) => ({ label: p, a: m.load_ms.baseline, b: m.load_ms.new })), { fmt: (v) => fmtMs(v), title: 'Page load comparison' })}</div>
       <div class="card"><h2>API latency (median): baseline vs new</h2>${C.groupedBars(ep.map(([e, m]) => ({ label: e.replace(/^GET |^POST /, ''), a: m.median_ms.baseline, b: m.median_ms.new })), { fmt: (v) => fmtMs(v), title: 'API latency comparison' })}</div></div>
      <div class="card"><h2>Page metrics</h2><div class="tw"><table><thead><tr><th>Path / metric</th><th class="num">Baseline</th><th class="num">New</th><th class="num">Δ abs</th><th class="num">Δ %</th></tr></thead><tbody>${pg.map(([p, m]) => `<tr><td class="mono">${esc(p)} load</td>${dcell(m.load_ms, fmtMs)}</tr><tr><td class="mono">${esc(p)} LCP</td>${dcell(m.lcp_ms, fmtMs)}</tr><tr><td class="mono">${esc(p)} transferred</td>${dcell(m.transfer_bytes, fmtBytes)}</tr>`).join('')}</tbody></table></div></div>
      <div class="card"><h2>API endpoints</h2>${ep.length ? `<div class="tw"><table><thead><tr><th>Endpoint / metric</th><th class="num">Baseline</th><th class="num">New</th><th class="num">Δ abs</th><th class="num">Δ %</th></tr></thead><tbody>${ep.map(([e, m]) => `<tr><td class="mono">${esc(e)} median</td>${dcell(m.median_ms, fmtMs)}</tr><tr><td class="mono">${esc(e)} p95</td>${dcell(m.p95_ms, fmtMs)}</tr><tr><td class="mono">${esc(e)} failed</td>${dcell(m.failed, (v) => v ?? '—')}</tr>`).join('')}</tbody></table></div>` : '<div class="empty">No API requests.</div>'}</div>
      <div class="card"><h2>Totals</h2><div class="tw"><table><thead><tr><th>Metric</th><th class="num">Baseline</th><th class="num">New</th><th class="num">Δ abs</th><th class="num">Δ %</th></tr></thead><tbody>${Object.entries(c.totals).map(([k, m]) => `<tr><td>${esc(k.replace(/_/g, ' '))}</td>${dcell(m, (v) => (v == null ? '—' : String(Math.round(v * 10) / 10)))}</tr>`).join('')}</tbody></table></div></div>
      <div class="grid g2"><div class="card"><h2>New failures (${c.new_failures.length})</h2>${c.new_failures.map((f) => `<p>${badge(f.severity)} ${esc(f.title)}</p>`).join('') || '<div class="empty">None</div>'}</div>
       <div class="card"><h2>Resolved failures (${c.resolved_failures.length})</h2>${c.resolved_failures.map((f) => `<p>${badge(f.severity)} ${esc(f.title)}</p>`).join('') || '<div class="empty">None</div>'}</div></div>
      <div class="card"><h2>Regressions (${c.regressions.length})</h2>${c.regressions.map((r) => `<p>${badge('medium')} ${esc(r.metric)}: ${fmtMs(r.baseline)} → ${fmtMs(r.new)} (${fmtPct(r.pct)}) <small class="m">rule: ${esc(r.rule)}</small></p>`).join('') || '<div class="empty">No regressions under the configured rule.</div>'}</div>`;
    } catch (e) { out.innerHTML = `<div class="notice ${e.status === 409 ? 'warn' : 'err'}" role="alert">${esc(e.message)}</div>`; }
  };
  document.getElementById('go').onclick = go;
  if (q.a && q.b) go();
}

// ------------------------------------------------------------------ history
async function history() {
  const profiles = await api.profiles();
  main.innerHTML = `${setTitle('Test History', 'Open earlier reports, filter, and select two runs to compare.')}
  <div class="card"><div class="row"><div><label for="fs">Status</label><select id="fs"><option value="">Any</option><option>completed</option><option>failed</option><option>cancelled</option><option>running</option></select></div>
   <div><label for="fv">Result</label><select id="fv"><option value="">Any</option><option>passed</option><option>failed</option></select></div>
   <div><label for="fp">Profile</label><select id="fp"><option value="">Any</option>${profiles.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></div>
   <div><label for="ff">From</label><input id="ff" type="date"></div><div><label for="ft">To</label><input id="ft" type="date"></div>
   <div style="align-self:end"><button class="btn" id="apply">Apply</button> <button class="btn sec" id="cmpsel" disabled>Compare selected (2)</button></div></div></div><div class="card" id="tbl"></div>`;
  const sel = new Set();
  const load = async () => {
    const p = new URLSearchParams(); const g = (i) => document.getElementById(i).value;
    if (g('fs')) p.set('status', g('fs')); if (g('fv')) p.set('verdict', g('fv')); if (g('fp')) p.set('profile_id', g('fp'));
    if (g('ff')) p.set('from', g('ff')); if (g('ft')) p.set('to', g('ft') + 'T23:59:59');
    const runs = await api.runs('?' + p);
    const t = document.getElementById('tbl');
    if (!runs.length) { t.innerHTML = '<div class="empty">No runs match these filters.</div>'; return; }
    t.innerHTML = `<div class="tw"><table><thead><tr><th><span style="position:absolute;left:-999px">Select</span></th><th>Run</th><th>Workflow</th><th>Profile</th><th>Status</th><th>Result</th><th>Issues</th><th>When</th></tr></thead><tbody>${runs.map((r) => `<tr><td><input type="checkbox" aria-label="Select ${esc(r.id)}" data-id="${r.id}" ${r.status === 'completed' ? '' : 'disabled'} style="width:auto"></td>
      <td><a href="#/runs/${r.id}">${runName(r)}</a> ${modeBadge(r.target_meta)}<br><small class="m">${r.id}</small></td><td>${esc(r.workflow_id)}</td><td>${esc(r.profile.name)}</td><td>${badge(r.status)}</td><td>${r.verdict ? badge(r.verdict) : '—'}</td>
      <td>${r.summary ? Object.values(r.summary.issue_counts).reduce((a, b) => a + b, 0) : '—'}</td><td>${when(r.created_at)}</td></tr>`).join('')}</tbody></table></div>`;
    t.querySelectorAll('input[type=checkbox]').forEach((c) => (c.onchange = () => { c.checked ? sel.add(c.dataset.id) : sel.delete(c.dataset.id); document.getElementById('cmpsel').disabled = sel.size !== 2; }));
  };
  document.getElementById('apply').onclick = load;
  document.getElementById('cmpsel').onclick = async () => { const ids = [...sel]; const rs = await Promise.all(ids.map((i) => api.run(i))); rs.sort((x, y) => x.run.created_at.localeCompare(y.run.created_at)); location.hash = `#/compare?a=${rs[0].run.id}&b=${rs[1].run.id}`; };
  await load();
}

// ------------------------------------------------------------------ settings
const RULE_FIELDS = [['api_latency_ms', 'API latency threshold (ms)', 'number'], ['api_latency_min_exceed_ratio', 'Share of attempts that must exceed it (0–1)', 'number'], ['api_latency_high_multiplier', 'Escalate to High when median > N × threshold', 'number'],
  ['page_load_ms', 'Page-load threshold (ms)', 'number'], ['page_transfer_kb', 'Page transfer threshold (KB)', 'number'], ['failure_ratio_high', 'Failure share treated as High (0–1)', 'number'], ['regression_pct', 'Regression: % worse (comparison)', 'number'], ['regression_min_abs_ms', 'Regression: minimum absolute ms', 'number']];
const SEV_FIELDS = [['severity_slow_api', 'Severity: slow API'], ['severity_slow_page', 'Severity: slow page load'], ['severity_js_error', 'Severity: JavaScript error'], ['severity_large_transfer', 'Severity: large transfer']];
async function settings() {
  const [{ rules }, profiles, targets, h, demo] = await Promise.all([api.rules(), api.profiles(), api.targets(), api.health(), api.demoMode()]);
  main.innerHTML = `${setTitle('Settings &amp; Testing Profiles', 'Severity rules are deterministic and configurable. Changes apply to future runs (each run stores the rules it used).')}
  <div class="grid g2"><div class="card"><h2>Classification rules</h2><form id="rf">${RULE_FIELDS.map(([k, l]) => `<div class="field"><label for="r_${k}">${l}</label><input id="r_${k}" type="number" step="any" value="${rules[k]}"></div>`).join('')}
   ${SEV_FIELDS.map(([k, l]) => `<div class="field"><label for="r_${k}">${l}</label><select id="r_${k}">${['critical', 'high', 'medium', 'low'].map((s) => `<option ${rules[k] === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div>`).join('')}
   <fieldset style="border:1px solid var(--line);border-radius:8px;margin-bottom:12px"><legend class="muted">Run fails when a finding has severity</legend>${['critical', 'high', 'medium', 'low'].map((s) => `<label style="display:inline-block;margin-right:14px"><input type="checkbox" style="width:auto" data-fail="${s}" ${rules.fail_on_severity.includes(s) ? 'checked' : ''}> ${s}</label>`).join('')}</fieldset>
   <div class="row"><button class="btn" type="submit">Save rules</button><button class="btn sec" type="button" id="rr">Reset to defaults</button></div></form>
   <p class="muted">Fixed rules: a core step failing in every attempt = Critical; any step failing in every attempt, or in ≥ the failure share = High; flaky failures = Medium. Details in docs/ARCHITECTURE.md.</p></div>
  <div><div class="card"><h2>Testing profiles</h2><div class="tw"><table><thead><tr><th>Name</th><th>Settings</th><th></th></tr></thead><tbody>${profiles.map((p) => `<tr><td>${esc(p.name)} ${p.builtin ? '<small class="m">(built-in)</small>' : ''}</td><td><small>${esc(profileSummary(p))}</small></td><td>${p.builtin ? '' : `<button class="btn danger" data-del="${p.id}">Delete</button>`}</td></tr>`).join('')}</tbody></table></div>
   <h3 style="margin-top:14px">Add custom profile</h3><form id="pf" class="grid g2" style="gap:8px">
   <div><label for="pn">Name</label><input id="pn" required maxlength="60"></div><div><label for="pd">Download kbps (blank = unlimited)</label><input id="pd" type="number" min="50"></div>
   <div><label for="pu">Upload kbps</label><input id="pu" type="number" min="50"></div><div><label for="pl">Latency ms</label><input id="pl" type="number" min="0" value="0"></div>
   <div><label for="pp">Packet loss % (simulated)</label><input id="pp" type="number" min="0" max="100" value="0"></div><div><label for="pc">CPU slowdown ×</label><input id="pc" type="number" min="1" max="20" value="1"></div>
   <div><label for="pt">Step timeout ms</label><input id="pt" type="number" min="1000" value="15000"></div><div style="align-self:end"><button class="btn" type="submit">Add profile</button></div></form></div>
  <div class="card"><h2>Targets</h2><p class="muted">Only these registered targets can be tested. Others are rejected (SSRF protection).</p>${targets.map((t) => `<p><b>${esc(t.name)}</b><br><span class="mono">${esc(t.url)}</span></p>`).join('')}
   <h3>Demo app control</h3>${typeof demo.optimized === 'boolean' ? `<p>Current mode: <b>${demo.optimized ? 'optimized' : 'unoptimized (deliberate faults)'}</b></p><button class="btn sec" id="dm">${demo.optimized ? 'Revert to unoptimized' : 'Apply sample optimization'}</button>` : '<p class="bad">Demo app not reachable. Start it with <code>python demo-app/server.py</code>.</p>'}</div>
  <div class="card"><h2>Environment</h2><ul class="tight"><li>API version ${esc(h.version)} · database ${h.database ? 'ok' : 'error'}</li><li>LLM explanations: ${h.llm_configured ? 'enabled (ANTHROPIC_API_KEY set on server)' : 'not configured — deterministic reports only'}</li><li>Max concurrent runs: ${h.max_concurrent_runs}</li><li>PDF export: not implemented</li></ul></div></div></div>`;
  document.getElementById('rf').onsubmit = async (e) => { e.preventDefault(); const b = {}; RULE_FIELDS.forEach(([k]) => (b[k] = parseFloat(document.getElementById('r_' + k).value))); SEV_FIELDS.forEach(([k]) => (b[k] = document.getElementById('r_' + k).value)); b.fail_on_severity = [...document.querySelectorAll('[data-fail]')].filter((c) => c.checked).map((c) => c.dataset.fail); try { await api.saveRules(b); toast('Rules saved.'); } catch (er) { toast(er.message, true); } };
  document.getElementById('rr').onclick = async () => { await api.resetRules(); toast('Rules reset.'); settings(); };
  document.getElementById('pf').onsubmit = async (e) => { e.preventDefault(); const n = (i) => { const v = document.getElementById(i).value; return v === '' ? null : parseFloat(v); }; try { await api.addProfile({ name: document.getElementById('pn').value, download_kbps: n('pd'), upload_kbps: n('pu'), latency_ms: n('pl'), packet_loss_pct: n('pp'), cpu_slowdown: n('pc'), step_timeout_ms: n('pt') }); toast('Profile added.'); settings(); } catch (er) { toast(er.message, true); } };
  document.querySelectorAll('[data-del]').forEach((b) => (b.onclick = async () => { await api.delProfile(b.dataset.del); settings(); }));
  const dm = document.getElementById('dm'); if (dm) dm.onclick = async () => { try { await api.setDemoMode(!demo.optimized); toast('Demo app mode changed.'); settings(); } catch (er) { toast(er.message, true); } };
}
