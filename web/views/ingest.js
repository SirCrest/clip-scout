// Ingest: drop a stream or paste a link, and watch it become clips.
import { html, useEffect, useMemo, useRef, useState } from '../vendor/preact-htm.js';
import { Icon } from '../icons.js';
import { api, get } from '../api.js';
import { state, fmt, toast, decisionOf, PARKED } from '../store.js';
import { Card, useWidth } from '../components.js';

const AGENT_NAME = { claude: 'Claude Code', codex: 'Codex', gemini: 'Gemini CLI', opencode: 'opencode', custom: 'Your agent' };

export function stageView(s, agent) {
  const st = s.stages, get = (n) => st[n] || { state: 'pending' };
  const cls = (x) => (x.state === 'done' || x.state === 'skipped' ? 'done' : x.state === 'running' ? 'run' : x.state === 'waiting' ? 'run agent' : x.state === 'failed' ? 'fail' : 'wait');
  const pct = (x) => (x.state === 'done' || x.state === 'skipped' ? 1 : x.progress || 0);
  const judgeParts = ['plan', 'music', 'judge'].map(get);
  const judgeState = judgeParts.find((x) => x.state === 'failed') || judgeParts.find((x) => x.state === 'running' || x.state === 'waiting')
    || (judgeParts.every((x) => x.state === 'done' || x.state === 'skipped') ? { state: 'done' } : { state: 'pending' });
  const who = AGENT_NAME[agent] || 'agent';
  const tr = get('transcribe');
  return [
    { k: 'fetch', icon: 'download', n: 'Download', x: get('fetch'), v: get('fetch').state === 'done' ? (s.source?.kind === 'file' ? 'from file' : 'downloaded') : get('fetch').note || '' },
    { k: 'transcribe', icon: 'transcribe', n: 'Transcribe', x: tr, v: tr.state === 'done' ? fmt.dur(s.duration || 0) : tr.note || '' },
    { k: 'pick', icon: 'find', n: 'Find', x: get('pick'), agent: get('pick').state === 'waiting', v: get('pick').state === 'done' ? `${s.clips} found` : get('pick').state === 'waiting' ? who : '' },
    { k: 'judge', icon: 'judge', n: 'Judge', x: judgeState, agent: get('judge').state === 'waiting', v: judgeState.state === 'done' ? `${s.top} top` : get('judge').state === 'waiting' ? `${who} · ${s.judged}/${s.clips}` : judgeState.note || '' },
    { k: 'edit', icon: 'edit', n: 'Edit', x: { state: s.kept ? 'done' : 'pending' }, v: s.kept ? `${s.kept} kept` : '' },
    { k: 'ready', icon: 'ready', n: 'Ready', x: { state: s.rendered ? 'done' : 'pending' }, v: s.rendered ? `${s.rendered} rendered` : '' },
  ].map((g) => ({ ...g, cls: cls(g.x), p: pct(g.x), error: g.x.error }));
}

function Roll({ s, clips }) {
  const box = useRef(null);
  const W = useWidth(box) || 800;
  const [H, setH] = useState(300);
  useEffect(() => { const ro = new ResizeObserver(([e]) => setH(Math.max(160, Math.round(e.contentRect.height)))); ro.observe(box.current); return () => ro.disconnect(); }, []);
  const [wave, setWave] = useState(null);
  const tr = s.stages.transcribe || {};
  const busy = tr.state === 'running' || tr.state === 'pending';
  useEffect(() => {
    let live = true, t;
    if (tr.state === 'skipped') return;
    const load = () => get(`/api/wave/${s.id}`).then((w) => { if (!live) return; setWave(w); if (w.pending || busy) t = setTimeout(load, 5000); }).catch(() => {});
    load();
    return () => { live = false; clearTimeout(t); };
  }, [s.id, busy]);
  const L = Math.max(1, s.duration || 1), x = (t) => (t / L) * W;
  const scan = tr.state === 'running' ? (tr.progress || 0) * L : !tr.state || tr.state === 'pending' ? 0 : null;
  const peaks = wave?.peaks || [];
  const step = wave?.step || 2, top = 30, mh = H - 110, mid = top + 44 + mh / 2;
  let done = '', todo = '';
  if (peaks.length) {
    const n = peaks.length, dx = W / Math.max(n, L / step), cut = scan == null ? n : Math.floor(scan / step);
    const path = (from, to) => { let a = '', b = ''; for (let i = from; i < to; i++) { const h = Math.max(0.02, peaks[i]) * mh / 2; a += `${i === from ? 'M' : 'L'}${(i * dx).toFixed(1)} ${(mid - h).toFixed(1)}`; } for (let i = to - 1; i >= from; i--) { const h = Math.max(0.02, peaks[i]) * mh / 2; b += `L${((i + 1) * dx).toFixed(1)} ${(mid + h).toFixed(1)}`; } return to > from ? a + b + 'Z' : ''; };
    done = path(0, Math.min(cut, n)); todo = path(Math.min(cut, n), n);
  }
  const ticks = [];
  for (let t = 0; t <= L; t += 600) ticks.push(t);
  return html`<div ref=${box} style="width:100%;height:100%;min-height:160px">
    <svg viewBox=${`0 0 ${W} ${H}`} aria-label="The stream, with clips as they're found">
      ${ticks.map((t) => html`<line class="st-tick" x1=${x(t)} x2=${x(t)} y1=${t % 1200 ? 10 : 4} y2="16" />${t % 1200 === 0 && x(t) < W - 50 ? html`<text class="st-lbl num" x=${x(t) + 3} y="10">${fmt.dur(t)}</text>` : null}`)}
      <text class="st-lbl num" x=${W} y="10" text-anchor="end">${fmt.dur(L)}</text>
      ${clips.map((c) => { const X = x(c.hook), w = Math.max(3, x(c.out) - X); return c.bin
        ? html`<rect class=${c.side === 'community' ? 'rl-x' : 'rl-y'} x=${X} y=${top} width=${w} height="30" rx="1.5" opacity=${c.bin === 'top' ? 0.9 : PARKED.has(c.bin) ? 0.15 : 0.45}><title>${c.title}</title></rect>`
        : html`<rect class="rl-pend" x=${X} y=${top + 0.5} width=${w} height="29" rx="1.5"><title>${c.title}</title></rect>`; })}
      ${done ? html`<path class="rl-done" d=${done} />` : null}${todo ? html`<path class="rl-todo" d=${todo} />` : null}
      ${!peaks.length ? html`<text class="st-lbl" x=${W / 2} y=${mid} text-anchor="middle">${wave?.pending ? 'Drawing the waveform…' : busy ? 'Listening…' : ''}</text>` : null}
      ${scan != null ? html`<rect class="rl-glow" x=${x(scan) - 40} y=${top - 6} width="40" height=${H - top - 30} /><line class="rl-scan" x1=${x(scan)} x2=${x(scan)} y1=${top - 6} y2=${H - 36} />
        <rect class="rl-tag" x=${Math.min(Math.max(0, x(scan) - 32), W - 64)} y=${H - 32} width="64" height="20" rx="4" /><text class="rl-tagt num" x=${Math.min(Math.max(32, x(scan)), W - 32)} y=${H - 18} text-anchor="middle">${fmt.dur(scan)}</text>` : null}
    </svg></div>`;
}

export function Ingest({ ui, go, upload }) {
  const ov = state.overview;
  const active = (x) => Object.values(x.stages).some((g) => ['running', 'waiting', 'failed', 'pending'].includes(g.state))
    || Object.keys(x.stages).length < 6;
  const streams = useMemo(() => [...(ov?.streams || [])].sort((a, b) => active(b) - active(a) || b.date.localeCompare(a.date)), [ov]);
  const [selId, setSelId] = useState(ui.focusStream || null);
  useEffect(() => { if (ui.focusStream) setSelId(ui.focusStream); }, [ui.focusStream]);
  const s = streams.find((x) => x.id === selId) || streams[0];
  const [link, setLink] = useState('');
  const [over, setOver] = useState(false);
  const fileInput = useRef(null);
  const agent = ov?.agent?.name;

  async function addLink(e) {
    e?.preventDefault();
    const v = link.trim();
    if (!v) return;
    try { const r = await api.ingest(v); setLink(''); setSelId(r.id); toast('Added. Clip Scout is on it.'); }
    catch (err) { toast(err.message); }
  }
  const clips = useMemo(() => (s ? state.clips.filter((c) => c.sid === s.id && !c.inside).sort((a, b) => a.hook - b.hook) : []), [s?.id, state.clips]);
  const stages = s ? stageView(s, agent) : [];
  const failed = stages.find((g) => g.cls === 'fail');

  return html`<div class="space ingest">
    <div class="ing-left">
      <div class=${`panel drop ${over ? 'over' : ''}`} onClick=${(e) => { if (!e.target.closest('.url')) fileInput.current.click(); }}
        onDragOver=${(e) => { e.preventDefault(); setOver(true); }} onDragLeave=${() => setOver(false)}
        onDrop=${(e) => { e.preventDefault(); e.stopPropagation(); setOver(false); const f = e.dataTransfer.files[0]; if (f) upload(f).then((id) => id && setSelId(id)); }}>
        <div class="big"><${Icon} n="import" /></div><h4>Drop a stream</h4>
        <form class="url" onSubmit=${addLink} onClick=${(e) => e.stopPropagation()}>
          <${Icon} n="link" /><input value=${link} onInput=${(e) => setLink(e.target.value)} placeholder="Paste a Twitch or YouTube link, or a file path" aria-label="Link or path" />
          <button class="go" type="submit" aria-label="Add"><${Icon} n="next" /></button></form>
        ${ui.uploading != null ? html`<div class="upbar" title="Uploading"><i style=${`width:${ui.uploading * 100}%`}></i></div>` : null}
        <input type="file" accept="video/*,.mkv,.flv,.ts" ref=${fileInput} hidden onChange=${(e) => { const f = e.target.files[0]; if (f) upload(f).then((id) => id && setSelId(id)); e.target.value = ''; }} />
      </div>
      <div class="panel queue">
        ${streams.length ? streams.map((x) => { const g = stageView(x, agent); return html`<button class=${`qi ${x.id === s?.id ? 'on' : ''}`} onClick=${() => setSelId(x.id)}>
          <span class="poster">${x.poster ? html`<img src=${`/thumb/${x.poster}`} alt="" loading="lazy" />` : html`<${Icon} n="transcribe" />`}</span>
          <span><h4>${x.title}</h4><span class="meta"><span class="num">${fmt.date(x.date)}</span>${x.duration ? html`<span class="num">${fmt.dur(x.duration)}</span>` : null}
            ${g.every((y) => y.cls === 'done' || y.k === 'edit' || y.k === 'ready')
              ? html`<span class="ok"><${Icon} n="ready" /><span class="num">${x.clips}</span></span>`
              : g.some((y) => y.cls === 'fail') ? html`<span class="bad"><${Icon} n="alert" /></span>`
              : html`<span class="mini">${g.slice(0, 4).map((y) => html`<i class=${y.cls === 'done' ? 'd' : y.cls === 'fail' ? 'f' : y.cls.includes('agent') ? 'w' : y.cls === 'run' ? 'r' : ''} style=${`--p:${Math.round(y.p * 100)}%`}></i>`)}</span>`}
          </span></span></button>`; })
          : html`<div class="empty"><${Icon} n="transcribe" /><span>Streams you add show up here.</span></div>`}
      </div>
    </div>
    ${s ? html`<div class="ing-right">
      <div class="panel stages">${stages.map((g) => html`<div class=${`stage ${g.cls}`}>
        <div class="top-l"><${Icon} n=${g.icon} /><span>${g.n}</span></div>
        <div class="pb"><i style=${`width:${g.p * 100}%`}></i></div>
        <div class="v num">${g.cls === 'done' ? html`<${Icon} n="check" />` : g.agent ? html`<${Icon} n="agent" />` : g.cls === 'fail' ? html`<${Icon} n="alert" />` : null}${g.v}</div></div>`)}</div>
      <div class="panel roll">${failed
        ? html`<div class="empty"><${Icon} n="alert" /><b>${failed.n} stopped</b><span class="dim">${failed.error || ''}</span>
            <button class="btn hot" onClick=${() => api.retryStream(s.id).then(() => toast('Trying again'))}><${Icon} n="retry" />Try again</button></div>`
        : html`<${Roll} s=${s} clips=${clips} />`}</div>
      <div class="panel found">
        <div class="found-h"><${Icon} n="find" /><b class="num">${s.clips} found</b><span class="num">${s.judged} judged · ${s.top} top</span>
          <span style="margin-left:auto;display:flex;align-items:center;gap:10px">${agent ? html`<span class="chip"><${Icon} n="agent" />${AGENT_NAME[agent] || agent}</span>` : null}
          ${clips.length ? html`<button class="btn hot" onClick=${() => { ui.setSid(s.id); go('review'); }}><${Icon} n="grid" />Review</button>` : null}</span></div>
        <div class="grid">${clips.slice(0, 60).map((c) => html`<${Card} key=${c.key} clip=${c} decision=${decisionOf(c.key)} pending=${!c.bin} parked=${PARKED.has(c.bin)}
          onClick=${() => { ui.setSid(s.id); ui.setFocus(c.key); go('review'); }} />`)}</div>
      </div>
    </div>` : html`<div class="panel"><div class="empty"><${Icon} n="import" /><b>Drop a stream to begin</b>
      <span>A video file from your computer, or a Twitch or YouTube link.</span></div></div>`}
  </div>`;
}
