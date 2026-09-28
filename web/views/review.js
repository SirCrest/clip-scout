// Review: sort the judge's picks. Grid on the left, the clip in the middle, what we know about it on the right,
// and the whole stream along the bottom.
import { html, useEffect, useMemo, useRef, useState } from '../vendor/preact-htm.js';
import { Icon, CUT_REASONS, MAYBE_NEEDS, FLAG_ICON, FLAG_WORD } from '../icons.js';
import { api, get } from '../api.js';
import { state, binList, decisionOf, decide, setReason, markSeen, childrenOf, mergeRun, fmt, toast, PARKED, lane } from '../store.js';
import { Card, Player, Strip, Timeline, Stars, quietRuns, useWidth } from '../components.js';

const BINS = [
  { k: 'top', icon: 'top', l: 'Top', t: 'Top picks, best first' },
  { k: 'effort', icon: 'layers', l: 'Effort', t: 'Best effort' },
  { k: 'spot', icon: 'spot', l: 'Spot check', t: 'Spot check: a few clips the judge set aside' },
  { k: 'seen', icon: 'eye', l: 'Seen', t: 'Seen but not sorted' },
  { k: 'sorted', icon: 'check', l: 'Sorted', t: 'Sorted, newest first' },
];
const SPEEDS = [1, 1.25, 1.5, 2];
const details = new Map(), waves = new Map();
const pref = (k, d) => { try { const v = localStorage.getItem('cs-' + k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem('cs-' + k, JSON.stringify(v)); } catch {} };

function useAsync(key, load, cache) {
  const [val, set] = useState(() => (key && cache.get(key)) || null);
  useEffect(() => {
    if (!key) return set(null);
    if (cache.has(key)) return set(cache.get(key));
    set(null);
    let live = true;
    load().then((v) => { cache.set(key, v); if (live) set(v); }).catch(() => {});
    return () => { live = false; };
  }, [key]);
  return val;
}

export function Review({ ui, go }) {
  const [dest, setDest] = useState(pref('dest', 'yt'));
  const [bin, setBin] = useState(pref('bin', 'top'));
  const [topic, setTopic] = useState('');
  const [hideSeen, setHideSeen] = useState(pref('hideSeen', true));
  const [speed, setSpeed] = useState(pref('speed', 1));
  const [refresh, setRefresh] = useState(0);
  const [selKey, setSelKey] = useState(null);
  const [leaving, setLeaving] = useState(() => new Set());
  const [gone, setGone] = useState(() => new Set());
  const [ask, setAsk] = useState(null);
  const [limit, setLimit] = useState(48);
  const [head, setHead] = useState({ out: 0, src: null });
  const last = useRef(null);
  const player = useRef(null);
  const gridRef = useRef(null);
  const gridW = useWidth(gridRef);
  const cols = Math.max(1, Math.floor((gridW - 20 + 9) / (118 + 9)));

  useEffect(() => keep('dest', dest), [dest]);
  useEffect(() => keep('bin', bin), [bin]);
  useEffect(() => keep('hideSeen', hideSeen), [hideSeen]);
  useEffect(() => keep('speed', speed), [speed]);

  // The list is fixed while a tab is open, so cards never jump under the cursor.
  const listKey = [dest, bin, topic, hideSeen, ui.sid, ui.query, state.ready, refresh].join('|');
  const list = useMemo(() => binList(bin, { dest, topic, query: ui.query, hideSeen, sid: ui.sid }), [listKey]);
  useEffect(() => { setGone(new Set()); setLeaving(new Set()); setLimit(48); }, [listKey]);
  const visible = bin === 'sorted' ? list : list.filter((c) => !gone.has(c.key));
  const shown = visible.slice(0, limit);

  const counts = useMemo(() => ({
    yt: binList('top', { dest: 'yt', hideSeen: false, sid: ui.sid }).length + binList('effort', { dest: 'yt', hideSeen: false, sid: ui.sid }).length,
    x: binList('top', { dest: 'x', hideSeen: false, sid: ui.sid }).length + binList('effort', { dest: 'x', hideSeen: false, sid: ui.sid }).length,
  }), [ui.sid, state.ready, refresh, state.decisions]);
  const topics = useMemo(() => [...new Set(state.clips.map((c) => c.topic).filter(Boolean))].sort(), [state.clips]);

  useEffect(() => {
    if (!selKey || (!visible.some((c) => c.key === selKey) && !state.byKey.get(selKey)?.inside))
      setSelKey(visible[0]?.key || null);
  }, [visible.length && visible[0]?.key, bin, dest]);

  // A clip handed over from another screen: show it, in its own lane and bin.
  useEffect(() => {
    const c = ui.focus && state.byKey.get(ui.focus);
    if (!c) return;
    setDest(lane(c));
    setBin(decisionOf(c.key) ? 'sorted' : PARKED.has(c.bin) ? 'spot' : c.bin === 'effort' ? 'effort' : 'top');
    setHideSeen(false);
    setTimeout(() => setSelKey(c.key), 0);
    ui.setFocus(null);
  }, [ui.focus]);

  const sel = selKey ? state.byKey.get(selKey) : null;
  const d = useAsync(selKey, () => api.clip(selKey), details);
  const w = useAsync(sel ? `${sel.key}` : null, () => get(`/api/wave/${sel.sid}?a=${sel.hook}&b=${sel.out}&n=900`), waves);
  useEffect(() => { if (selKey) markSeen(selKey); }, [selKey]);

  const idx = visible.findIndex((c) => c.key === selKey);
  const move = (n) => {
    const i = idx < 0 ? 0 : Math.max(0, Math.min(visible.length - 1, idx + n));
    if (visible[i]) { setSelKey(visible[i].key); if (i >= limit - 6) setLimit((l) => l + 36); }
  };

  async function onDecide(dec) {
    if (!sel) return;
    const key = sel.key, before = decisionOf(key);
    const next = visible[idx + 1]?.key || visible[idx - 1]?.key || null;
    last.current = { key, before };
    decide(key, dec);
    if (bin !== 'sorted' && !sel.inside) {
      setLeaving((s) => new Set(s).add(key));
      setTimeout(() => setGone((s) => new Set(s).add(key)), 320);
      if (next) setSelKey(next);
    }
    setAsk(dec === 'cut' || dec === 'maybe' ? { key, dec, t: Date.now() } : null);
    const msg = dec === 'keep' ? (lane(sel) === 'x' ? 'Kept for X' : 'Kept. It will be edited and rendered.') : dec === 'maybe' ? 'Maybe: it goes to Edit' : 'Cut';
    toast(msg, { label: 'Undo', icon: 'undo', run: undo });
  }
  function undo() {
    const l = last.current;
    if (!l) return;
    decide(l.key, l.before);
    setGone((s) => { const n = new Set(s); n.delete(l.key); return n; });
    setLeaving((s) => { const n = new Set(s); n.delete(l.key); return n; });
    setSelKey(l.key);
    setAsk(null);
    last.current = null;
  }
  useEffect(() => { if (!ask) return; const t = setTimeout(() => setAsk(null), 5000); return () => clearTimeout(t); }, [ask]);

  // keyboard
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest('input, textarea, select') || e.metaKey || e.altKey) return;
      if (e.ctrlKey && e.key.toLowerCase() !== 'z') return;
      const k = e.key.toLowerCase();
      if (ask && /^[1-5]$/.test(k)) { const r = (ask.dec === 'cut' ? CUT_REASONS : MAYBE_NEEDS)[+k - 1]; setReason(ask.key, r.k); setAsk(null); return e.preventDefault(); }
      const act = {
        arrowright: () => move(1), arrowleft: () => move(-1), arrowdown: () => move(cols), arrowup: () => move(-cols),
        k: () => onDecide('keep'), m: () => onDecide('maybe'), x: () => onDecide('cut'), u: undo, z: undo,
        ' ': () => player.current?.toggle(), enter: () => player.current?.restart(),
        s: () => setSpeed((v) => SPEEDS[(SPEEDS.indexOf(v) + 1) % SPEEDS.length]),
      }[k];
      if (act) { act(); e.preventDefault(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // seen: on screen for half a second, then scrolled past
  const vis = useRef(new Map());
  const io = useMemo(() => new IntersectionObserver((entries) => {
    for (const e of entries) {
      const key = e.target.dataset.key;
      if (e.isIntersecting) vis.current.set(key, performance.now());
      else if (vis.current.has(key)) { if (performance.now() - vis.current.get(key) > 500) markSeen(key); vis.current.delete(key); }
    }
  }, { threshold: 0.6 }), []);
  useEffect(() => () => io.disconnect(), []);
  const more = useRef(null);
  useEffect(() => {
    if (!more.current) return;
    const o = new IntersectionObserver(([e]) => e.isIntersecting && setLimit((l) => l + 36), { rootMargin: '50%' });
    o.observe(more.current);
    return () => o.disconnect();
  }, [shown.length < visible.length]);

  const segs = useMemo(() => (sel ? [{ a: sel.hook, b: sel.out, z: 1 }] : null), [sel?.key]);
  const quiet = useMemo(() => (w && sel ? quietRuns(w.peaks, sel.hook, sel.out) : []), [w, sel?.key]);
  const quietS = quiet.reduce((a, r) => a + r.to - r.from, 0);
  const kids = sel ? childrenOf(sel.key) : [];
  const run = sel ? mergeRun(sel) : null;
  const streamClips = useMemo(() => (sel ? state.clips.filter((c) => c.sid === sel.sid) : []), [sel?.sid, state.clips]);
  const keptSet = useMemo(() => new Set(Object.entries(state.decisions.decisions).filter(([, v]) => v.d === 'keep').map(([k]) => k)), [state.decisions, state.pending.size]);
  const streamInfo = sel && state.overview?.streams.find((s) => s.id === sel.sid);
  const destLane = sel ? lane(sel) : dest;

  const onHead = useRef(0);
  const timeUpdate = (out, src) => { const n = performance.now(); if (n - onHead.current > 120) { onHead.current = n; setHead({ out, src }); } };

  async function makeOne() {
    try {
      const r = await api.merge(run.parts.map((p) => p.key));
      toast('Made one clip from the whole discussion');
      setTimeout(() => { setRefresh((n) => n + 1); setSelKey(r.key); }, 1500);
    } catch (e) { toast(`Couldn't combine: ${e.message}`); }
  }

  const empty = !state.clips.length
    ? html`<div class="empty"><${Icon} n="find" /><b>No clips yet</b><span>Add a stream and Clip Scout finds the moments worth posting.</span>
        <button class="btn hot" onClick=${() => go('ingest')}><${Icon} n="import" />Add a stream</button></div>`
    : html`<div class="empty"><${Icon} n=${bin === 'top' ? 'ready' : 'check'} /><b>${bin === 'top' ? 'Every top pick is sorted' : 'Nothing here'}</b>
        ${bin === 'top' ? html`<button class="btn" onClick=${() => setBin('effort')}><${Icon} n="layers" />Look at best effort</button>` : null}
        ${hideSeen && bin !== 'sorted' ? html`<button class="btn" onClick=${() => setHideSeen(false)}><${Icon} n="eye" />Show clips I've seen</button>` : null}</div>`;

  return html`<div class="space review">
    <section class="panel bin">
      <div class="bin-head">
        <button class=${`lane-btn yt ${dest === 'yt' ? 'on' : ''}`} onClick=${() => setDest('yt')} title="Staff clips for the Elgato Clips YouTube channel"><${Icon} n="yt" /><span class="num">${counts.yt}</span></button>
        <button class=${`lane-btn x ${dest === 'x' ? 'on' : ''}`} onClick=${() => setDest('x')} title="Community clips for X"><${Icon} n="x" /><span class="num">${counts.x}</span></button>
        <span class="sp"></span>
        <div class="seg">${BINS.map((b) => html`<button class=${bin === b.k ? 'on' : ''} title=${b.t} aria-label=${b.t} onClick=${() => setBin(b.k)}><${Icon} n=${b.icon} /><span class="lbl">${b.l}</span></button>`)}</div>
      </div>
      <div class="bin-sub">
        <${Icon} n="search" /><input class="q" placeholder="Search" value=${ui.query} onInput=${(e) => ui.setQuery(e.target.value)} />
        <select value=${topic} onChange=${(e) => setTopic(e.target.value)} aria-label="Topic"><option value="">All topics</option>${topics.map((t) => html`<option>${t}</option>`)}</select>
        <button class="ib" style="width:26px;height:26px" title=${hideSeen ? 'Showing only clips you haven\'t seen' : 'Showing every clip'} onClick=${() => setHideSeen(!hideSeen)}><${Icon} n=${hideSeen ? 'eyeoff' : 'eye'} /></button>
        <span class="prog num">${visible.length}</span>
      </div>
      <div class="scroll" style="flex:1">
        ${visible.length ? html`<div class="grid" ref=${gridRef}>
          ${shown.map((c) => html`<${Card} key=${c.key} clip=${c} selected=${c.key === selKey} decision=${decisionOf(c.key)} parked=${PARKED.has(c.bin)}
              children=${childrenOf(c.key).length} onClick=${() => setSelKey(c.key)}
              cardRef=${(el) => { if (el) { io.observe(el); el.classList.toggle('leaving', leaving.has(c.key)); } }} />`)}
          ${shown.length < visible.length ? html`<div class="more" ref=${more}></div>` : null}
        </div>` : html`<div ref=${gridRef}>${empty}</div>`}
      </div>
    </section>

    <section class="viewer">
      ${sel ? html`<${Player} sid=${sel.sid} segments=${segs} poster=${`/thumb/${sel.key}`} ctl=${player} speed=${speed}
          dest=${destLane} onTime=${timeUpdate} label=${`${fmt.dur(head.out)} / ${fmt.dur(sel.dur)}`} />
        <div class="panel strip-panel">
          <div class="strip-head">
            <span class="res"><span class=${quietS > 1 ? 'from num' : 'num'}>${fmt.dur(sel.dur)}</span>${quietS > 1 ? html`<${Icon} n="next" /><b class="num">≈ ${fmt.dur(sel.dur - quietS)}</b>` : null}</span>
            ${quietS > 1 ? html`<span class="dim num" title="Quiet stretches editing is likely to remove">${Math.round(quietS)} s of pauses</span>` : null}
            <span class="kinds">${kids.length ? html`<span title="Shorter clips inside this one"><${Icon} n="nested" /><span class="num">${kids.length}</span></span>` : null}
              <span title="Where it is in the stream"><${Icon} n="clock" /><span class="num">${fmt.dur(sel.hook)}</span></span></span>
          </div>
          <${Strip} wave=${w?.peaks} start=${sel.hook} end=${sel.out} removed=${quiet} estimate head=${head.src}
            nested=${kids.map((k) => ({ a: k.hook, b: k.out }))} onSeek=${(t) => player.current?.seekSource(t)} />
          ${d?.hook ? html`<div class="callout"><${Icon} n="find" /><q>${d.hook}</q></div>` : null}
        </div>
        <div class="dock">
          <div class="trans">
            <button onClick=${() => move(-1)} aria-label="Previous clip" title="Previous (←)"><${Icon} n="prev" /></button>
            <button class="play" onClick=${() => player.current?.toggle()} aria-label="Play or pause" title="Play (Space)"><${Icon} n="play" /></button>
            <button onClick=${() => move(1)} aria-label="Next clip" title="Next (→)"><${Icon} n="next" /></button>
            <button class="spd num" onClick=${() => setSpeed((v) => SPEEDS[(SPEEDS.indexOf(v) + 1) % SPEEDS.length])} title="Speed (S)">${speed}×</button>
          </div>
          <div class="dec">
            <button class=${`d cut ${decisionOf(sel.key) === 'cut' ? 'on' : ''}`} onClick=${() => onDecide('cut')} aria-label="Cut" title="Cut: not for our channels"><${Icon} n="cut" /><span class="lbl">Cut</span><kbd>X</kbd></button>
            <button class=${`d maybe ${decisionOf(sel.key) === 'maybe' ? 'on' : ''}`} onClick=${() => onDecide('maybe')} aria-label="Maybe" title="Maybe: worth posting after careful editing"><${Icon} n="maybe" /><span class="lbl">Maybe</span><kbd>M</kbd></button>
            <button class=${`d keep ${decisionOf(sel.key) === 'keep' ? 'on' : ''}`} onClick=${() => onDecide('keep')} aria-label="Keep"><${Icon} n="keep" /><span>Keep</span><kbd>K</kbd></button>
          </div>
          ${ask ? html`<div class="reasons" role="group" aria-label=${ask.dec === 'cut' ? 'Why cut?' : 'What does it need?'}>
            ${(ask.dec === 'cut' ? CUT_REASONS : MAYBE_NEEDS).map((r, i) => html`<button onClick=${() => { setReason(ask.key, r.k); setAsk(null); }} aria-label=${r.t}>
              <${Icon} n=${r.icon} /><kbd>${i + 1}</kbd><span class="tip">${r.t}</span></button>`)}
            <span class="timer" key=${ask.t}></span></div>` : null}
        </div>` : html`<div class="panel" style="flex:1">${empty}</div>`}
    </section>

    <aside class="panel insp">
      ${sel ? html`
        <div class="prod"><${Icon} n="grid" />${sel.product}${sel.topic && sel.topic !== sel.product ? html`<span class="faint">· ${sel.topic}</span>` : null}</div>
        <h3 class="title">${sel.title}</h3>
        <div class="row"><span class=${`destc ${destLane}`}><${Icon} n=${destLane} />${destLane === 'yt' ? 'Elgato Clips' : 'X post'}</span><${Stars} n=${sel.stars || sel.score || 0} lg /></div>
        ${sel.reason ? html`<p class="reason">${sel.reason}</p>` : null}
        ${sel.speakers ? html`<div class="people"><${Icon} n="people" />${sel.speakers}</div>` : null}
        ${(sel.flags || []).some((f) => FLAG_WORD[f]) ? html`<div class="flags">${sel.flags.filter((f) => FLAG_WORD[f]).map((f) => html`<div class="flag"><${Icon} n=${FLAG_ICON[f] || 'alert'} />${FLAG_WORD[f]}</div>`)}</div>` : null}
        ${run ? html`<div class="merge"><${Icon} n="nested" /><span>One discussion across <b class="num">${run.parts.length}</b> clips, <span class="num">${fmt.dur(run.length)}</span></span>
          <button class="btn" onClick=${makeOne} title="Combine them into one clip"><${Icon} n="plus" /></button></div>` : null}
        ${destLane === 'x' ? html`<${XPost} clip=${sel} d=${d} />` : d?.yt_titles?.length ? html`<div class="sec"><div class="sech"><${Icon} n="yt" /><span>Title ideas</span></div>
          <ul class="abc">${d.yt_titles.map((t, i) => html`<li><b>${'ABC'[i]}</b><span>${t}</span></li>`)}</ul></div>` : null}
        ${kids.length ? html`<div class="sec"><div class="sech"><${Icon} n="nested" /><span class="num">${kids.length} shorter cuts inside</span></div>
          <div class="nestl">${kids.map((k) => html`<button onClick=${() => player.current?.seekSource(k.hook)}><span class="num">${fmt.dur(k.hook - sel.hook)}</span><span>${k.title}</span></button>`)}</div></div>` : null}
        ${d?.source_url ? html`<div class="sec"><a class="people" href=${d.source_url} target="_blank" rel="noreferrer"><${Icon} n="external" />Open the stream here</a></div>` : null}
      ` : null}
    </aside>

    <section class="panel tl">
      <div class="tl-g"><span class="yt"><${Icon} n="yt" /></span><span class="x"><${Icon} n="x" /></span></div>
      ${sel ? html`<${Timeline} duration=${streamInfo?.duration} clips=${streamClips} current=${sel.key} kept=${keptSet} onPick=${(k) => setSelKey(k)} height=${118} />` : null}
    </section>
  </div>`;
}

function XPost({ clip, d }) {
  const initial = state.decisions.posts[clip.key] ?? d?.judge?.post ?? '';
  const [text, setText] = useState(initial);
  useEffect(() => setText(state.decisions.posts[clip.key] ?? d?.judge?.post ?? ''), [clip.key, d]);
  const save = () => { state.decisions.posts[clip.key] = text; api.post(clip.key, text).catch(() => {}); };
  return html`<div class="sec post"><div class="sech"><${Icon} n="x" /><span>Post</span></div>
    <textarea class="field" rows="4" value=${text} onInput=${(e) => setText(e.target.value)} onBlur=${save}></textarea>
    <div class="row"><button class="btn" onClick=${() => { navigator.clipboard?.writeText(text); toast('Copied'); }}><${Icon} n="copy" /></button>
      <span class=${`cnt num ${text.length > 280 ? 'over' : ''}`}>${text.length} / 280</span></div></div>`;
}
