// Clip Scout app shell: the top bar, the four spaces, drop-anywhere, toasts.
import { html, render, useEffect, useMemo, useState } from './vendor/preact-htm.js';
import { Icon } from './icons.js';
import { upload as sendFile } from './api.js';
import { state, start, useStore, toasts, toast, binList, today } from './store.js';
import { Review } from './views/review.js';
import { Ingest } from './views/ingest.js';
import { Edit } from './views/edit.js';
import { Publish } from './views/publish.js';
import { Settings } from './views/settings.js';

const SPACES = [
  { k: 'ingest', icon: 'import', t: 'Streams' },
  { k: 'review', icon: 'grid', t: 'Review' },
  { k: 'edit', icon: 'edit', t: 'Edit' },
  { k: 'publish', icon: 'upload', t: 'Publish' },
];
const AGENT_NAME = { claude: 'Claude Code', codex: 'Codex', gemini: 'Gemini CLI', opencode: 'opencode', custom: 'Your agent' };
const KIND_WORD = { pick: 'finding clips', judge: 'judging', edit: 'tightening edits', titles: 'writing titles' };

function App() {
  const s = useStore();
  const initial = (location.hash.slice(1) || '').split('?')[0];
  const [space, setSpace] = useState(SPACES.some((x) => x.k === initial) || initial === 'settings' ? initial : null);
  const [sid, setSid] = useState('');
  const [query, setQuery] = useState('');
  const [focus, setFocus] = useState(null);
  const [focusStream, setFocusStream] = useState(null);
  const [uploading, setUploading] = useState(null);
  const [dragging, setDragging] = useState(false);

  const go = (k) => { setSpace(k); history.replaceState(null, '', `#${k}`); };
  // First visit: land on Review when there are clips, Streams when there aren't.
  useEffect(() => { if (s.ready && !space) go(s.clips.length ? 'review' : 'ingest'); }, [s.ready]);

  async function upload(file) {
    if (!/\.(mp4|mkv|mov|flv|ts|m4v|webm)$/i.test(file.name)) { toast('Drop a video file (mp4, mkv, mov…)'); return null; }
    go('ingest');
    setUploading(0);
    try {
      const r = await sendFile(file, setUploading);
      setFocusStream(r.id);
      toast('Added. Clip Scout is on it.');
      return r.id;
    } catch (e) { toast(`Upload failed: ${e.message}`); return null; }
    finally { setUploading(null); }
  }
  useEffect(() => {
    let depth = 0;
    const has = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
    const enter = (e) => { if (has(e)) { depth++; setDragging(true); } };
    const leave = () => { depth = Math.max(0, depth - 1); if (!depth) setDragging(false); };
    const over = (e) => { if (has(e)) e.preventDefault(); };
    const drop = (e) => { if (!has(e)) return; e.preventDefault(); depth = 0; setDragging(false); const f = e.dataTransfer.files[0]; if (f && !e.defaultPrevented) upload(f); };
    window.addEventListener('dragenter', enter); window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', over); window.addEventListener('drop', drop);
    return () => { window.removeEventListener('dragenter', enter); window.removeEventListener('dragleave', leave); window.removeEventListener('dragover', over); window.removeEventListener('drop', drop); };
  }, []);

  const ov = s.overview;
  const ui = { sid, setSid, query, setQuery, focus, setFocus, focusStream, uploading };
  const decided = Object.values(s.decisions.decisions);
  const sortedToday = decided.filter((d) => (d.at || '').slice(0, 10) === today()).length;
  const topLeft = useMemo(() => (s.ready ? binList('top', { dest: 'yt', hideSeen: false, sid }).length + binList('top', { dest: 'x', hideSeen: false, sid }).length : 0), [s.ready, s.decisions, s.pending.size, sid, s.catalog]);
  const maybes = decided.filter((d) => d.d === 'maybe').length;
  const inFlight = (ov?.streams || []).filter((x) => ['fetch', 'transcribe', 'pick', 'plan', 'music', 'judge'].some((n) => ['running', 'waiting'].includes(x.stages[n]?.state))).length;
  const running = ov?.tasks?.running || [];
  const badges = { ingest: inFlight, review: topLeft, edit: maybes, publish: 0 };
  const streams = [...(ov?.streams || [])].filter((x) => x.clips).sort((a, b) => b.date.localeCompare(a.date));

  let body = null;
  if (!s.ready) body = html`<div class="space"><div class="empty"><${Icon} n="find" cls="spin" /><span>Opening the library…</span></div></div>`;
  else if (space === 'review') body = html`<${Review} ui=${ui} go=${go} />`;
  else if (space === 'ingest') body = html`<${Ingest} ui=${{ ...ui, setFocus: (k) => setFocus(k) }} go=${go} upload=${upload} />`;
  else if (space === 'edit') body = html`<${Edit} ui=${ui} go=${go} />`;
  else if (space === 'publish') body = html`<${Publish} go=${go} />`;
  else if (space === 'settings') body = html`<${Settings} />`;

  return html`
    <header class="top">
      <div class="brand"><${Icon} n="find" /><span>Clip Scout</span></div>
      <nav class="spaces" aria-label="Spaces">${SPACES.map((x) => html`<button class=${`space-btn ${space === x.k ? 'on' : ''}`} onClick=${() => go(x.k)} title=${x.t} aria-label=${x.t}>
        <${Icon} n=${x.icon} /><span class="label">${x.t}</span>${badges[x.k] ? html`<span class=${`badge ${x.k === 'review' ? 'quiet' : ''} num`}>${badges[x.k] > 999 ? '999+' : badges[x.k]}</span>` : null}</button>`)}</nav>
      ${space === 'review' && streams.length ? html`<label class="stream-pick"><select value=${sid} onChange=${(e) => setSid(e.target.value)} aria-label="Stream"
          style="background:none;border:0;color:inherit;max-width:360px;text-overflow:ellipsis">
          <option value="">All streams</option>${streams.map((x) => html`<option value=${x.id}>${x.date.slice(5)} · ${x.title}</option>`)}</select></label>` : null}
      <div class="meter" title="Sorted today, and top picks still to sort">
        <div class="bar"><i style=${`width:${sortedToday + topLeft ? (sortedToday / (sortedToday + topLeft)) * 100 : 0}%`}></i></div>
        <span class="num">${sortedToday}<span class="dim"> / ${sortedToday + topLeft}</span></span></div>
      ${running.length ? html`<button class="pulse" onClick=${() => go('settings')} title="Your agent is working">
        <i></i><${Icon} n="agent" /><span>${AGENT_NAME[ov.agent.name] || ov.agent.name} · ${KIND_WORD[running[0].kind] || 'working'}${running.length > 1 ? ` +${running.length - 1}` : ''}</span></button>` : null}
      <div class="tools"><button class=${`ib ${space === 'settings' ? 'on' : ''}`} onClick=${() => go('settings')} aria-label="Settings" title="Settings"><${Icon} n="sliders" /></button></div>
    </header>
    ${body}
    ${dragging ? html`<div class="dropall"><div><${Icon} n="import" />Drop to add this stream</div></div>` : null}
    <div class="toasts" aria-live="polite">${toasts.map((t) => html`<div class="toast" key=${t.id}><span>${t.text}</span>
      ${t.action ? html`<button onClick=${() => { t.action.run(); toasts.splice(toasts.indexOf(t), 1); }}>${t.action.icon ? html`<${Icon} n=${t.action.icon} />` : null}${t.action.label}</button>` : null}</div>`)}</div>`;
}

render(html`<${App} />`, document.getElementById('app'));
start().catch((e) => { document.getElementById('app').textContent = `Clip Scout couldn't load the library: ${e.message}`; });
