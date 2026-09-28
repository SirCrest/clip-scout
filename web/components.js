// Shared pieces: the clip player, the waveform strip, the stream timeline, cards.
import { html, useEffect, useLayoutEffect, useMemo, useRef, useState } from './vendor/preact-htm.js';
import { Icon, FLAG_ICON } from './icons.js';
import { fmt } from './store.js';

export function useWidth(ref) {
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return w;
}

export const Stars = ({ n = 0, lg }) => html`<span class=${`stars ${lg ? 'lg' : ''}`} title=${`${n} of 5`}>
  ${[1, 2, 3, 4, 5].map((i) => html`<i class=${i <= n ? 'on' : ''}></i>`)}</span>`;

export const FlagIcons = ({ flags }) => (flags || []).filter((f) => FLAG_ICON[f]).slice(0, 3)
  .map((f) => html`<${Icon} n=${FLAG_ICON[f]} />`);

// ---- clip card

export function Card({ clip, selected, decision, parked, onClick, children = 0, pending, cardRef }) {
  const lane = clip.side === 'community' ? 'x' : 'yt';
  const mark = decision === 'keep' ? 'keep' : decision === 'maybe' ? 'maybe' : decision === 'cut' ? 'cut' : null;
  return html`<button class=${`card ${lane} ${selected ? 'sel' : ''} ${decision ? 'is-' + decision : ''} ${parked ? 'parked' : ''} ${pending ? 'pend' : ''}`}
    onClick=${onClick} ref=${cardRef} data-key=${clip.key} aria-label=${clip.title}>
    <span class="thumb"><img src=${`/thumb/${clip.key}`} alt="" loading="lazy" onError=${(e) => (e.target.style.opacity = 0)} />
      <span class="dur num">${fmt.dur(clip.dur)}</span>
      ${children ? html`<span class="nest"><${Icon} n="nested" />${children}</span>` : null}
      <span class="mark">${mark ? html`<${Icon} n=${mark} />` : null}</span></span>
    <span class="ct">${clip.title}</span>
    <span class="cm">${pending ? null : html`<${Stars} n=${clip.stars || clip.score || 0} />`}<${FlagIcons} flags=${clip.flags} /></span>
  </button>`;
}

// ---- the player: plays the source stream from a clip's kept segments, skipping what editing removed

export function Player({ sid, segments, poster, ctl, onTime, onEnded, autoplay = true, speed = 1, dest, label }) {
  const v = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showPoster, setShowPoster] = useState(true);
  const segs = segments && segments.length ? segments : null;
  const total = useMemo(() => (segs || []).reduce((a, s) => a + s.b - s.a, 0), [segs]);
  const segRef = useRef({ segs, i: 0 });
  segRef.current.segs = segs;

  const outTime = (t) => {
    let acc = 0;
    for (const s of segs || []) { if (t < s.b) return acc + Math.max(0, t - s.a); acc += s.b - s.a; }
    return acc;
  };

  const place = (i, into = 0) => {
    const el = v.current, s = segs?.[i];
    if (!el || !s) return;
    segRef.current.i = i;
    el.style.transform = s.z && s.z !== 1 ? `scale(${s.z})` : '';
    el.currentTime = s.a + into;
  };

  // New clip or new edits: start from the first kept segment.
  useEffect(() => {
    const el = v.current;
    if (!el || !segs) return;
    setShowPoster(true);
    const go = () => { place(0); if (autoplay) el.play().catch(() => {}); };
    if (el.readyState >= 1) go(); else el.addEventListener('loadedmetadata', go, { once: true });
  }, [sid, segs && segs.map((s) => `${s.a}-${s.b}-${s.z}`).join()]);

  useEffect(() => { if (v.current) v.current.playbackRate = speed; }, [speed, sid]);

  // Frame-accurate skipping where the browser supports it, timeupdate elsewhere.
  useEffect(() => {
    const el = v.current;
    if (!el) return;
    let handle, alive = true;
    const tick = () => {
      const { segs: S, i } = segRef.current;
      if (S && !el.paused) {
        const t = el.currentTime, s = S[i];
        if (s && t >= s.b - 0.012) {
          if (i + 1 < S.length) place(i + 1);
          else { el.pause(); onEnded?.(); }
        } else if (s && (t < s.a - 0.25 || t > s.b + 0.25)) {
          const j = S.findIndex((x) => t >= x.a && t < x.b);
          if (j >= 0) { segRef.current.i = j; el.style.transform = S[j].z !== 1 ? `scale(${S[j].z})` : ''; }
        }
        onTime?.(outTime(el.currentTime), el.currentTime);
      }
      if (alive) handle = el.requestVideoFrameCallback ? el.requestVideoFrameCallback(tick) : requestAnimationFrame(tick);
    };
    handle = el.requestVideoFrameCallback ? el.requestVideoFrameCallback(tick) : requestAnimationFrame(tick);
    return () => { alive = false; el.cancelVideoFrameCallback?.(handle); cancelAnimationFrame(handle); };
  }, [sid]);

  if (ctl) ctl.current = {
    toggle() { const el = v.current; if (!el) return; if (el.paused) { const S = segRef.current.segs; if (S && el.currentTime >= S.at(-1).b - 0.05) place(0); el.play().catch(() => {}); } else el.pause(); },
    pause() { v.current?.pause(); },
    play() { v.current?.play().catch(() => {}); },
    restart() { place(0); v.current?.play().catch(() => {}); },
    seekOut(t) { let acc = 0; (segs || []).some((s, i) => { if (t < acc + s.b - s.a) { place(i, t - acc); return true; } acc += s.b - s.a; return false; }); },
    seekSource(t) { const S = segs || []; const j = S.findIndex((s) => t < s.b); if (j >= 0) place(j, Math.max(0, t - S[j].a)); },
    total,
  };

  return html`<div class="frame">
    <video ref=${v} src=${sid ? `/media/${sid}` : undefined} preload="metadata" playsinline
      onPlay=${() => { setPlaying(true); setShowPoster(false); }} onPause=${() => setPlaying(false)}
      onWaiting=${() => setLoading(true)} onPlaying=${() => setLoading(false)} onCanPlay=${() => setLoading(false)}
      onClick=${() => ctl?.current?.toggle()} />
    ${poster && showPoster ? html`<img class="poster" src=${poster} alt="" />` : null}
    ${!playing ? html`<button class="big-play" onClick=${() => ctl?.current?.toggle()} aria-label="Play"><span><${Icon} n="play" /></span></button>` : null}
    ${dest ? html`<span class=${`dest ${dest}`}><${Icon} n=${dest} />${dest === 'yt' ? 'Elgato Clips' : 'X'}</span>` : null}
    ${label ? html`<span class="tc num">${label}</span>` : null}
    ${loading && playing ? html`<span class="loading"><${Icon} n="spinner" cls="spin" /></span>` : null}
  </div>`;
}

// ---- waveform strip: the clip's sound, with removed ranges dimmed and marked

function wavePath(peaks, W, H, y0, x0 = 0, x1 = W) {
  if (!peaks?.length) return '';
  const n = peaks.length, dx = W / n, mid = y0 + H / 2;
  const i0 = Math.max(0, Math.floor(x0 / dx)), i1 = Math.min(n, Math.ceil(x1 / dx));
  let t = '', b = '';
  for (let i = i0; i < i1; i++) { const a = Math.max(0.035, peaks[i]) * H / 2; t += `${i === i0 ? 'M' : 'L'}${(i * dx).toFixed(1)} ${(mid - a).toFixed(1)}`; }
  for (let i = i1 - 1; i >= i0; i--) { const a = Math.max(0.035, peaks[i]) * H / 2; b += `L${((i + 1) * dx).toFixed(1)} ${(mid + a).toFixed(1)}`; }
  return t + b + 'Z';
}

const KIND_ICON = { content: 'tangent', fumble: 'fumble', tangent: 'tangent' };

export function Strip({ wave, start, end, removed = [], nested = [], head, onSeek, onToggle, onRemove, interactive, estimate }) {
  const box = useRef(null);
  const W = useWidth(box) || 600, H = 88, wy = 16, wh = 54;
  const len = Math.max(0.1, end - start);
  const x = (t) => ((t - start) / len) * W;
  const tAt = (px) => start + (px / W) * len;
  const [drag, setDrag] = useState(null);
  const [hover, setHover] = useState(null);

  const down = (e) => {
    const r = box.current.getBoundingClientRect(), px = e.clientX - r.left;
    const hit = removed.find((m) => px >= x(m.from) - 2 && px <= x(m.to) + 2);
    if (hit && onToggle) { onToggle(hit); return; }
    if (!interactive) { onSeek?.(tAt(px)); return; }
    const d = { a: px, b: px };
    setDrag(d);
    const move = (ev) => setDrag({ a: d.a, b: Math.max(0, Math.min(W, ev.clientX - r.left)) });
    const up = (ev) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      const b = Math.max(0, Math.min(W, ev.clientX - r.left));
      setDrag(null);
      if (Math.abs(b - d.a) > 6) onRemove?.(tAt(Math.min(d.a, b)), tAt(Math.max(d.a, b)));
      else onSeek?.(tAt(b));
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  const ticks = [];
  const step = len > 600 ? 120 : len > 240 ? 60 : len > 90 ? 30 : 10;
  for (let t = 0; t <= len; t += step) ticks.push(t);

  return html`<div ref=${box} style="width:100%">
    <svg class="strip" viewBox=${`0 0 ${W} ${H}`} onPointerDown=${down}
      onPointerMove=${(e) => { const r = box.current.getBoundingClientRect(), px = e.clientX - r.left; setHover(removed.find((m) => px >= x(m.from) - 2 && px <= x(m.to) + 2)?.id || null); }}
      onPointerLeave=${() => setHover(null)} aria-label="The clip's sound and its edits">
      <path class="st-wave" d=${wavePath(wave, W, wh, wy)} />
      ${estimate ? removed.map((m) => html`<rect class="st-est" x=${x(m.from)} y=${wy} width=${Math.max(1.5, x(m.to) - x(m.from))} height=${wh}><title>Quiet stretch: editing will likely take it out</title></rect>`)
      : removed.map((m) => { const a = x(m.from), w = Math.max(1.5, x(m.to) - a), cx = a + w / 2; return html`
        <rect class=${`st-cut ${hover === m.id ? 'hover' : ''} ${m.tight ? 'tight' : ''}`} x=${a} y=${wy} width=${w} height=${wh}><title>${m.reason || m.kind} · ${(m.to - m.from).toFixed(1)} s${m.tight ? ' · words run together here, give it a listen' : ''}${onToggle ? ' · click to put back' : ''}</title></rect>
        <line class="st-cutline" x1=${a} x2=${a} y1=${wy} y2=${wy + wh} /><line class="st-cutline" x1=${a + w} x2=${a + w} y1=${wy} y2=${wy + wh} />
        ${KIND_ICON[m.kind] ? html`<g transform=${`translate(${cx - 7} 0) scale(${14 / 24})`} style="fill:none;stroke:var(--tung);stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round"><path d="M4 16h4c2.5 0 2.5-8 5.5-8H20M16.5 4.5L20 8l-3.5 3.5" /></g>`
          : m.kind === 'filler' ? html`<circle cx=${cx} cy="7" r="2.2" style="fill:var(--tung)" />`
          : html`<line x1=${cx} x2=${cx} y1="3" y2="11" style="stroke:var(--tung);stroke-width:1.5" />`}`; })}
      ${nested.map((n, i) => { const a = x(n.a), b = x(n.b), y = 78 + (i % 2) * 5; return html`<path d=${`M${a} ${y - 3}v3H${b}v-3`} style="stroke:var(--muted);stroke-width:1.2;fill:none" />`; })}
      ${drag ? html`<rect class="st-drag" x=${Math.min(drag.a, drag.b)} y=${wy - 2} width=${Math.abs(drag.b - drag.a)} height=${wh + 4} />` : null}
      ${head != null && head >= start && head <= end ? html`<line class="st-head" x1=${x(head)} x2=${x(head)} y1=${wy - 4} y2=${wy + wh + 2} /><path class="st-headcap" d=${`M${x(head) - 4} ${wy - 6}h8l-4 5z`} />` : null}
      ${ticks.map((t) => html`<text class="st-lbl num" x=${Math.min(x(start + t) + 2, W - 26)} y="87">${fmt.dur(t)}</text>`)}
    </svg></div>`;
}

// ---- the stream timeline: every clip of a stream on its lane, the current one lit

export function Timeline({ duration, clips, current, kept, onPick, height = 120 }) {
  const box = useRef(null);
  const W = useWidth(box) || 1000, H = height;
  const L = Math.max(1, duration || Math.max(1, ...clips.map((c) => c.out)));
  const x = (t) => (t / L) * W;
  const laneH = (H - 40) / 2, y1 = 20, y2 = 20 + laneH + 8;
  const ticks = [];
  for (let t = 0; t <= L; t += 600) ticks.push(t);
  const cur = clips.find((c) => c.key === current);
  return html`<div ref=${box} style="width:100%;height:100%">
    <svg class="timeline" viewBox=${`0 0 ${W} ${H}`} aria-label="Where this clip sits in the stream">
      ${ticks.map((t) => html`<line class="st-tick" x1=${x(t)} x2=${x(t)} y1=${t % 1800 ? 11 : 5} y2="16" />
        ${t % 1800 === 0 && x(t) < W - 60 ? html`<text class="st-lbl num" x=${x(t) + 3} y="10">${fmt.dur(t)}</text>` : null}`)}
      <rect class="tl-lane" x="0" y=${y1} width=${W} height=${laneH} rx="4" /><rect class="tl-lane" x="0" y=${y2} width=${W} height=${laneH} rx="4" />
      <rect class="tl-ly" x="0" y=${y1 + laneH - 2} width=${W} height="2" /><rect class="tl-lx" x="0" y=${y2 + laneH - 2} width=${W} height="2" />
      ${clips.map((c) => {
        const y = c.side === 'community' ? y2 : y1, X = x(c.hook), w = Math.max(2, x(c.out) - X);
        if (c.bin === 'off' || c.bin === 'dupe') return html`<rect class="tl-park" x=${X} y=${y + 8} width=${w} height=${laneH - 18} rx="1" onClick=${() => onPick?.(c.key)}><title>${c.title}</title></rect>`;
        return html`<rect class=${kept?.has(c.key) ? 'tl-kept' : c.side === 'community' ? 'tl-x' : 'tl-y'} x=${X} y=${y + 3} width=${w} height=${laneH - 8} rx="1.5"
          opacity=${c.bin === 'top' ? 0.85 : 0.4} onClick=${() => onPick?.(c.key)}><title>${c.title}</title></rect>`;
      })}
      ${cur ? html`<rect class="tl-cur" x=${x(cur.hook)} y=${(cur.side === 'community' ? y2 : y1)} width=${Math.max(3, x(cur.out) - x(cur.hook))} height=${laneH} rx="2" />
        <line class="tl-curline" x1=${x(cur.hook)} x2=${x(cur.hook)} y1="0" y2=${H - 16} />
        <rect class="tl-curtag" x=${Math.min(Math.max(0, x(cur.hook) - 30), W - 60)} y=${H - 18} width="60" height="18" rx="4" />
        <text class="tl-curtxt num" x=${Math.min(Math.max(30, x(cur.hook)), W - 30)} y=${H - 5} text-anchor="middle">${fmt.dur(cur.hook)}</text>` : null}
    </svg></div>`;
}

// ---- quiet-stretch estimate from a clip's waveform, for review before real edits exist

export function quietRuns(peaks, start, end, thr = 0.09, min = 0.7) {
  if (!peaks?.length) return [];
  const dt = (end - start) / peaks.length, out = [];
  let a = null;
  peaks.forEach((p, i) => {
    if (p < thr) { if (a === null) a = i; }
    else if (a !== null) { if ((i - a) * dt >= min) out.push({ id: `q${out.length}`, from: start + a * dt + 0.15, to: start + i * dt - 0.15, kind: 'pause', reason: 'quiet' }); a = null; }
  });
  return out.filter((r) => r.from > start + 0.5 && r.to < end - 0.3);
}
