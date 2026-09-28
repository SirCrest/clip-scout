// Settings: which agent does the thinking, how many at once, the machine check, and what's been happening.
import { html, useEffect, useState } from '../vendor/preact-htm.js';
import { Icon } from '../icons.js';
import { api } from '../api.js';
import { state, toast } from '../store.js';

const AGENTS = [
  { k: 'claude', n: 'Claude Code', hint: 'claude' },
  { k: 'codex', n: 'Codex', hint: 'codex' },
  { k: 'gemini', n: 'Gemini CLI', hint: 'gemini' },
  { k: 'opencode', n: 'opencode', hint: 'DeepSeek, GLM and more' },
  { k: 'custom', n: 'Other', hint: 'any command' },
];
const KIND_ICON = { pick: 'find', judge: 'judge', edit: 'edit', titles: 'yt' };
const STATE_ICON = { done: 'ready', open: 'clock', claimed: 'spinner', failed: 'alert', cancelled: 'cut' };

export function Settings() {
  const [s, setS] = useState(null);
  const [health, setHealth] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem('cs-theme') || 'system'; } catch { return 'system'; } });
  useEffect(() => { api.settings().then(setS); fetch('/api/health').then((r) => r.json()).then(setHealth); }, []);
  useEffect(() => { const l = () => api.tasks().then((t) => setTasks(t.slice(-60).reverse())); l(); const i = setInterval(l, 5000); return () => clearInterval(i); }, []);
  useEffect(() => {
    try { theme === 'system' ? localStorage.removeItem('cs-theme') : localStorage.setItem('cs-theme', theme); } catch {}
    if (theme === 'system') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme;
  }, [theme]);

  const save = (patch) => api.saveSettings(patch).then((v) => { setS({ ...s, ...v }); toast('Saved'); }).catch((e) => toast(e.message));
  if (!s) return html`<div class="space"><div class="empty"><${Icon} n="spinner" cls="spin" /></div></div>`;
  const cfg = s.agents[s.agent] || {};
  const feed = state.overview?.activity || [];

  return html`<div class="space settings">
    <section class="panel sp-card">
      <h3><${Icon} n="agent" />Your agent</h3>
      <div class="agents">${AGENTS.map((a) => { const has = a.k === 'custom' || s.available[a.k]; return html`
        <button class=${`agent ${s.agent === a.k ? 'on' : ''} ${has ? '' : 'missing'}`} onClick=${() => save({ agent: a.k })}>
          <b>${a.n}</b><span>${has ? html`<${Icon} n="check" />${a.hint}` : html`<${Icon} n="alert" />not installed`}</span></button>`; })}</div>
      <div class="form">
        ${s.agent === 'custom' ? html`<label>Command</label><input class="field" value=${cfg.command || ''} placeholder="mytool run {prompt}"
            onChange=${(e) => save({ agents: { custom: { command: e.target.value } } })} />`
          : html`<label>Model</label><input class="field" value=${cfg.model || ''} placeholder="the agent's default"
              onChange=${(e) => save({ agents: { [s.agent]: { model: e.target.value.trim() } } })} />
            ${'effort' in cfg ? html`<label>Effort</label><select class="field" value=${cfg.effort || ''} onChange=${(e) => save({ agents: { [s.agent]: { effort: e.target.value } } })}>
              <option value="">default</option>${['low', 'medium', 'high', 'xhigh', 'max'].map((x) => html`<option>${x}</option>`)}</select>` : null}`}
        <label>At once</label><div class="stepper"><button onClick=${() => save({ parallel: Math.max(1, s.parallel - 1) })}><${Icon} n="minus" /></button><b class="num">${s.parallel}</b>
          <button onClick=${() => save({ parallel: Math.min(8, s.parallel + 1) })}><${Icon} n="plus" /></button></div>
        <label>Autopilot</label><div class="row" style="justify-content:flex-start"><button class=${`toggle ${s.auto !== false ? 'on' : ''}`} onClick=${() => save({ auto: s.auto === false })} aria-label="Autopilot"></button>
          <span class="dim" style="font-size:12.5px">${s.auto !== false ? 'New streams run start to finish on their own' : 'Paused'}</span></div>
      </div>
    </section>

    <section class="panel sp-card">
      <h3><${Icon} n="ready" />This computer</h3>
      <ul class="health">${(health || []).map((h) => html`<li class=${h.status}><${Icon} n=${h.status === 'ok' ? 'check' : h.status === 'fail' ? 'alert' : 'minus'} /><span>${h.text}</span></li>`)}</ul>
      <div class="form"><label>Look</label><div class="seg">${[['system', 'sliders'], ['dark', 'moon'], ['light', 'sun']].map(([t, i]) => html`
        <button class=${theme === t ? 'on' : ''} onClick=${() => setTheme(t)} title=${t}><${Icon} n=${i} /></button>`)}</div></div>
    </section>

    <section class="panel sp-card">
      <h3><${Icon} n="layers" />Agent tasks</h3>
      <ul class="tasks">${tasks.length ? tasks.map((t) => { const r = (t.runs || []).at(-1); return html`<li>
        <${Icon} n=${STATE_ICON[t.state] || 'clock'} cls=${t.state === 'claimed' ? 'spin' : ''} />
        <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title=${t.reason || (t.errors || []).join('\n')}><${Icon} n=${KIND_ICON[t.kind] || 'agent'} /> ${t.id}</span>
        <span class="who">${r ? `${r.agent}${r.models?.length ? ' · ' + r.models.join(', ') : r.model && r.model !== 'default' ? ' · ' + r.model : ''} · ${Math.round(r.seconds)}s${r.cost_usd ? ` · $${r.cost_usd.toFixed(2)}` : ''}` : t.state}
          ${t.state === 'failed' ? html` <button class="btn" style="height:24px;padding:0 6px" onClick=${() => api.retryTask(t.id).then(() => toast('Queued again'))}><${Icon} n="retry" /></button>` : null}</span></li>`; })
        : html`<li><span></span><span class="dim">No tasks yet.</span><span></span></li>`}</ul>
    </section>

    <section class="panel sp-card">
      <h3><${Icon} n="clock" />What's been happening</h3>
      <div class="feed">${[...feed].reverse().map((l) => html`<div><span class="num faint">${l.t}</span><span>${l.text}</span></div>`)}</div>
    </section>
  </div>`;
}
