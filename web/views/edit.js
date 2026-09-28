// Edit: every kept (and maybe) clip, tightened. See exactly what editing removed, put anything back, take more out,
// and choose a hard cut or a punch-in at each join.
import { html, useEffect, useMemo, useRef, useState } from '../vendor/preact-htm.js';
import { Icon } from '../icons.js';
import { api, get } from '../api.js';
import { state, fmt, toast, decide, decisionOf, lane } from '../store.js';
import { Player, Strip } from '../components.js';

const KIND = { pause: { icon: 'pause', t: 'Pauses' }, filler: { icon: 'filler', t: 'Fillers' }, content: { icon: 'tangent', t: 'Detours and false starts' },
  trim: { icon: 'bounds', t: 'Start and end' } };
const waves = new Map();

function useRenders() {
  const [r, set] = useState({});
  useEffect(() => { let live = true; const load = () => api.renders().then((v) => live && set(v)).catch(() => {}); load(); const t = setInterval(load, 4000); return () => { live = false; clearInterval(t); }; }, []);
  return r;
}

export function Edit({ ui, go }) {
  const renders = useRenders();
  const dec = state.decisions.decisions;
  const items = useMemo(() => Object.entries(dec).filter(([k, v]) => (v.d === 'keep' || v.d === 'maybe') && state.byKey.get(k))
    .sort((a, b) => (b[1].at || '').localeCompare(a[1].at || '')).map(([k, v]) => ({ clip: state.byKey.get(k), d: v.d, why: v.why })),
  [dec, state.clips, state.pending.size]);
  const [selKey, setSelKey] = useState(null);
  useEffect(() => { if (!selKey || !items.some((i) => i.clip.key === selKey)) setSelKey(items[0]?.clip.key || null); }, [items.length]);
  const cur = items.find((i) => i.clip.key === selKey);
  const [view, setView] = useState(null);
  const [busy, setBusy] = useState(false);
  const [head, setHead] = useState({ out: 0, src: null });
  const [anchor, setAnchor] = useState(null);
  const player = useRef(null);
  const rs = state.overview?.renders || { queued: [], active: null };

  useEffect(() => {
    if (!selKey) return setView(null);
    let live = true;
    setView(null); setBusy(true);
    api.edit(selKey).then((v) => live && setView(v)).catch((e) => toast(`Couldn't load edits: ${e.message}`)).finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [selKey]);
  // Pick up the agent's refinement when its task finishes.
  useEffect(() => {
    if (!view?.task || view.task.state === 'done' || !selKey) return;
    const t = setInterval(() => api.edit(selKey).then((v) => { if (v.task?.state !== view.task.state) setView(v); }).catch(() => {}), 6000);
    return () => clearInterval(t);
  }, [view?.task?.state, selKey]);

  const edl = view?.edl;
  const segs = useMemo(() => (edl ? edl.segments.map((s) => ({ a: s.src_in, b: s.src_out, z: s.zoom })) : null), [edl]);
  const c = cur?.clip;
  const range = edl && c ? [Math.min(c.hook, edl.range[0]) - 0.4, Math.max(c.out, edl.range[1]) + 0.4] : null;
  const [wave, setWave] = useState(null);
  useEffect(() => {
    if (!range) return;
    const k = `${c.key}:${range[0].toFixed(1)}`;
    if (waves.has(k)) return setWave(waves.get(k));
    get(`/api/wave/${c.sid}?a=${range[0]}&b=${range[1]}&n=1000`).then((w) => { waves.set(k, w); setWave(w); }).catch(() => {});
  }, [c?.key, range && range[0].toFixed(1)]);

  async function change(changes, note) {
    setBusy(true);
    try { const e = await api.saveEdit(selKey, changes); setView((v) => ({ ...v, edl: e })); if (note) toast(note); }
    catch (err) { toast(`Couldn't change that: ${err.message}`); }
    finally { setBusy(false); }
  }
  const removedAt = (t) => edl?.removed.find((r) => t >= r.from && t <= r.to);
  const outside = (t) => edl && (t < edl.range[0] || t > edl.range[1]);
  function clickWord(w, e) {
    const mid = (w.s + w.e) / 2, r = removedAt(mid);
    if (e.shiftKey && anchor) {
      const a = Math.min(anchor.s, w.s), b = Math.max(anchor.e, w.e);
      setAnchor(null);
      return change({ remove: [{ from: a, to: b }] }, 'Removed');
    }
    if (r) return change({ restore: [r.id] }, 'Put back');
    if (outside(mid)) return change({ trim: mid < edl.range[0] ? { in: w.s - 0.05 } : { out: w.e + 0.1 } }, 'Clip extended');
    setAnchor(w);
    player.current?.seekSource(w.s);
  }

  const kept = cur?.d === 'keep';
  const render = c ? renders[c.key] : null;
  const active = rs.active?.key === c?.key ? rs.active : null;
  const queued = c && rs.queued.includes(c.key);
  const stats = edl?.stats;

  return html`<div class="space editsp">
    <aside class="panel eq">
      <div class="eq-h"><${Icon} n="edit" /><b class="num">${items.length}</b><span>kept or maybe</span></div>
      <div class="scroll" style="flex:1">
        ${items.length ? items.map(({ clip, d }) => {
          const r = renders[clip.key], a = rs.active?.key === clip.key, q = rs.queued.includes(clip.key);
          const st = d === 'maybe' ? { i: 'maybe', t: 'Needs you' } : r ? { i: 'ready', t: 'Rendered', cls: 'ready' } : a ? { i: 'spinner', t: rs.active.stage === 'planning' ? 'Planning edits' : `Rendering ${Math.round((rs.active.progress || 0) * 100)}%`, spin: 1 }
            : q ? { i: 'clock', t: 'Waiting for edits' } : { i: 'edit', t: 'Planned' };
          return html`<button class=${`eqi ${lane(clip)} ${clip.key === selKey ? 'on' : ''}`} onClick=${() => setSelKey(clip.key)}>
            <span class="poster"><img src=${`/thumb/${clip.key}`} alt="" loading="lazy" /></span>
            <span><h4>${clip.title}</h4><span class="when num">${fmt.dur(clip.dur)}</span></span>
            <span class=${`st ${st.cls || ''}`} title=${st.t}><${Icon} n=${st.i} cls=${st.spin ? 'spin' : ''} /></span></button>`; })
        : html`<div class="empty"><${Icon} n="edit" /><b>Nothing to edit yet</b><span>Clips you keep land here, already tightened.</span>
            <button class="btn" onClick=${() => go('review')}><${Icon} n="grid" />Go sort clips</button></div>`}
      </div>
    </aside>

    <section class="viewer">
      ${c ? html`
        <${Player} sid=${c.sid} segments=${segs} poster=${`/thumb/${c.key}`} ctl=${player} dest=${lane(c)}
          onTime=${(out, src) => setHead({ out, src })} label=${edl ? `${fmt.dur(head.out)} / ${fmt.dur(stats.edited)}` : ''} />
        <div class="panel strip-panel">
          <div class="strip-head">
            ${stats ? html`<span class="res"><span class="from num">${fmt.dur(stats.original)}</span><${Icon} n="next" /><b class="num">${fmt.dur(stats.edited)}</b></span>
              <span class="dim num">${Math.max(0, Math.round(stats.original - stats.edited))} s tighter</span>
              <span class="kinds">${Object.entries(KIND).map(([k, v]) => { const n = edl.removed.filter((r) => r.kind === k).length; return n ? html`<span title=${v.t}><${Icon} n=${v.icon} /><span class="num">${n}</span></span>` : null; })}
                <span title="Cuts"><${Icon} n="edit" /><span class="num">${edl.cuts.length}</span></span></span>`
            : html`<span class="dim">${busy ? 'Listening for pauses, fillers and shot changes…' : ''}</span>`}
          </div>
          ${range ? html`<${Strip} wave=${wave?.peaks} start=${range[0]} end=${range[1]} removed=${edl.removed} head=${head.src} interactive
            onSeek=${(t) => player.current?.seekSource(t)} onToggle=${(m) => change({ restore: [m.id] }, 'Put back')}
            onRemove=${(a, b) => change({ remove: [{ from: a, to: b }] }, 'Removed')} />` : html`<div style="height:88px"></div>`}
          <div class="callout"><${Icon} n="edit" /><span>Click a dimmed stretch to put it back · drag across the sound to take more out</span></div>
        </div>
        <div class="panel proof" aria-label="What's said, with removed words struck through">
          ${view ? view.words.map((w, i) => {
            const mid = (w.s + w.e) / 2, r = removedAt(mid), out = outside(mid);
            const prev = view.words[i - 1];
            const gap = prev && edl.removed.find((x) => x.kind === 'pause' && x.from >= prev.e - 0.3 && x.to <= w.s + 0.3);
            const nowish = head.src != null && head.src >= w.s && head.src < w.e;
            return html`${gap ? html`<span class="gap" title=${`${gap.reason}: click to put back`} onClick=${() => change({ restore: [gap.id] }, 'Put back')}><${Icon} n="pause" />${(gap.to - gap.from).toFixed(1)}</span>` : ' '}<span
              class=${`w ${r || out ? 'gone' : ''} ${w.f ? 'filler' : ''} ${w.m && out ? 'margin' : ''} ${nowish ? 'now' : ''} ${anchor === w ? 'now' : ''}`}
              title=${r ? `${r.reason || r.kind} (${r.by}): click to put back` : out ? 'Outside the clip: click to include it' : 'Click to jump here · shift-click another word to remove the words between'}
              onClick=${(e) => clickWord(w, e)}>${w.w}</span>`; })
          : html`<span class="dim">${busy ? 'Reading the words…' : ''}</span>`}
        </div>` : html`<div class="panel" style="flex:1"><div class="empty"><${Icon} n="edit" /><span>Pick a clip on the left.</span></div></div>`}
    </section>

    <aside class="panel pside">
      ${c ? html`
        <div class="prod"><${Icon} n="grid" />${c.product}</div>
        <h3 class="title">${c.title}</h3>
        ${cur.d === 'maybe' ? html`<div class="warns"><div><${Icon} n="maybe" /><span>Marked maybe${cur.why ? `: ${cur.why.replace('-', ' ')}` : ''}. Fix what it needs, then keep it.</span></div>
          <button class="btn hot" onClick=${() => { decide(c.key, 'keep'); toast('Kept. Rendering now.'); }}><${Icon} n="keep" />Keep it</button></div>` : null}
        ${view?.task ? html`<div class="line"><${Icon} n="agent" /><span>${view.task.state === 'done' ? 'Tightened by your agent' : view.task.state === 'failed' ? 'The agent couldn\'t edit it; rules only' : 'Your agent is reviewing the edit…'}</span></div>` : null}
        ${edl ? html`<div class="sec"><div class="sech"><${Icon} n="edit" /><span>Removed</span></div>
          ${Object.entries(edl.stats.removed || {}).map(([k, s]) => html`<div class="flag"><${Icon} n=${KIND[k]?.icon || 'cut'} />${KIND[k]?.t || k}<span class="num" style="margin-left:auto">${s.toFixed(1)} s</span></div>`)}</div>
        <div class="sec"><div class="sech"><${Icon} n="hardcut" /><span>Cuts</span></div>
          <div class="cuts">${edl.cuts.map((k) => html`<div class="cutrow"><button class="num" style="text-align:left" onClick=${() => player.current?.seekOut(Math.max(0, (k.at ?? 0) - 2))} title="Hear this cut">${fmt.dur(k.at ?? 0)}</button>
            <span title=${k.tight ? 'The words run together here: give this cut a listen' : k.why} style=${k.tight ? 'color:var(--tung)' : ''}>${k.tight ? html`<${Icon} n="alert" /> ` : null}${k.why}</span>
            <div class="seg"><button class=${k.style === 'hard' ? 'on' : ''} title="Hard cut" onClick=${() => change({ style: { [k.i]: 'hard' } })}><${Icon} n="hardcut" /></button>
              <button class=${k.style === 'punch' ? 'on' : ''} title="Punch in" onClick=${() => change({ style: { [k.i]: 'punch' } })}><${Icon} n="punch" /></button></div></div>`)}
            ${!edl.cuts.length ? html`<span class="dim" style="font-size:12.5px">No cuts: it already flows.</span>` : null}</div></div>` : null}
        <div class="sec">
          ${render && !active ? html`<div class="render-state"><${Icon} n="ready" /><span>Rendered</span></div>
            <div class="row"><button class="btn" onClick=${() => api.reveal(c.key)}><${Icon} n="folder" />Show file</button>
              <a class="btn" href=${`/out/${c.key}`} target="_blank"><${Icon} n="play" /></a></div>`
          : active ? html`<div class="render-state"><${Icon} n="spinner" cls="spin" /><span>${active.stage === 'planning' ? 'Listening for pauses and fillers…' : 'Rendering'}</span></div>
              ${active.stage !== 'planning' ? html`<div class="pbar"><i style=${`width:${(active.progress || 0) * 100}%`}></i></div>` : null}`
          : queued ? html`<div class="render-state"><${Icon} n="clock" /><span>${view?.task && view.task.state !== 'done' ? 'Renders when your agent is done' : 'Waiting to render'}</span></div>` : null}
          ${kept ? html`<button class="btn hot" disabled=${!!active} onClick=${() => api.render(c.key).then(() => toast('Rendering with these edits'))}><${Icon} n="retry" />${render ? 'Render again' : 'Render now'}</button>` : null}
        </div>` : null}
    </aside>
  </div>`;
}
