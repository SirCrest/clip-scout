// One shared store for the app: the server's overview (live over SSE), every clip, and people's decisions.
import { useEffect, useState } from './vendor/preact-htm.js';
import { api, events } from './api.js';

const listeners = new Set();
export const state = {
  overview: null,
  clips: [],
  byKey: new Map(),
  catalog: -1,
  decisions: { decisions: {}, seen: {}, merges: [], posts: {} },
  pending: new Map(), // key -> decision shown before the server confirms it
  ready: false,
};

export function emit() { for (const fn of listeners) fn(); }

export function useStore() {
  const [, tick] = useState(0);
  useEffect(() => {
    const fn = () => tick((n) => n + 1);
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);
  return state;
}

async function loadClips() {
  const { version, clips } = await api.clips();
  state.catalog = version;
  state.clips = clips;
  state.byKey = new Map(clips.map((c) => [c.key, c]));
}

export async function start() {
  const [, d] = await Promise.all([loadClips(), api.decisions()]);
  state.decisions = d;
  state.ready = true;
  emit();
  events(async (ov) => {
    state.overview = ov;
    if (ov.catalog !== state.catalog) await loadClips();
    emit();
  });
}

export const decisionOf = (key) =>
  state.pending.has(key) ? state.pending.get(key) : state.decisions.decisions[key]?.d || null;

export async function decide(key, d, why = null) {
  const before = decisionOf(key);
  state.pending.set(key, d);
  emit();
  try {
    await api.decide(key, d, why);
    if (d) state.decisions.decisions[key] = { d, why, at: new Date().toISOString() };
    else delete state.decisions.decisions[key];
    state.decisions.seen[key] ??= today();
  } catch (e) {
    toast(`Couldn't save that: ${e.message}`);
    state.pending.delete(key);
    emit();
    return before;
  }
  state.pending.delete(key);
  emit();
  return before;
}

export async function setReason(key, why) {
  const rec = state.decisions.decisions[key];
  if (rec) rec.why = why;
  emit();
  await api.reason(key, why).catch(() => {});
}

// Seen marks are batched: the review grid reports many as the reviewer scrolls.
let seenQueue = new Set(), seenTimer;
export function markSeen(key) {
  if (state.decisions.seen[key] || seenQueue.has(key)) return;
  seenQueue.add(key);
  clearTimeout(seenTimer);
  seenTimer = setTimeout(() => {
    const keys = [...seenQueue];
    seenQueue = new Set();
    for (const k of keys) state.decisions.seen[k] = today();
    api.seen(keys).catch(() => {});
    emit();
  }, 800);
}

export const today = () => new Date().toISOString().slice(0, 10);

// ---- toasts
export const toasts = [];
export function toast(text, action = null, ms = 4000) {
  const t = { id: Math.random(), text, action };
  toasts.push(t);
  emit();
  setTimeout(() => { const i = toasts.indexOf(t); if (i >= 0) toasts.splice(i, 1); emit(); }, ms);
}

// ---- review lists

export const PARKED = new Set(['off', 'dupe']);

// Stable per-build pseudo-random: spot-check picks change daily, not on every render.
function hash(s) { let h = 2166136261; for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); return h >>> 0; }

export function lane(clip) {
  const side = clip.side || 'staff';
  return side === 'community' ? 'x' : 'yt';
}

// The clips a reviewer sees in one bin, in the order they see them.
export function binList(bin, { dest, topic, query, hideSeen, sid }) {
  const seen = state.decisions.seen;
  const q = (query || '').trim().toLowerCase();
  let list = state.clips.filter((c) => lane(c) === dest && !c.inside && (!sid || c.sid === sid));
  if (topic) list = list.filter((c) => c.topic === topic);
  if (q) list = list.filter((c) => `${c.title} ${c.product} ${c.speakers} ${c.reason}`.toLowerCase().includes(q));
  const undecided = (c) => !decisionOf(c.key);
  if (bin === 'top' || bin === 'effort') {
    list = list.filter((c) => (c.bin || 'effort') === bin && undecided(c) && !(hideSeen && seen[c.key]));
    return list.sort((a, b) => (b.stars || b.score || 0) - (a.stars || a.score || 0) || b.date.localeCompare(a.date) || a.hook - b.hook);
  }
  if (bin === 'spot') {
    const day = today();
    const parked = list.filter((c) => PARKED.has(c.bin) && undecided(c));
    const perStream = new Map();
    for (const c of parked.sort((a, b) => hash(day + a.key) - hash(day + b.key))) {
      const n = perStream.get(c.sid) || 0;
      if (n < 2) { perStream.set(c.sid, n + 1); }
      else c._skip = true;
    }
    const out = parked.filter((c) => !c._skip);
    parked.forEach((c) => delete c._skip);
    return out.sort((a, b) => b.date.localeCompare(a.date));
  }
  if (bin === 'seen') return list.filter((c) => seen[c.key] && undecided(c) && !PARKED.has(c.bin))
    .sort((a, b) => (seen[b.key] || '').localeCompare(seen[a.key] || ''));
  if (bin === 'sorted') {
    const at = (c) => state.decisions.decisions[c.key]?.at || '';
    return state.clips.filter((c) => lane(c) === dest && decisionOf(c.key) && (!sid || c.sid === sid))
      .sort((a, b) => at(b).localeCompare(at(a)));
  }
  return list;
}

export function childrenOf(key) {
  return state.clips.filter((c) => c.inside === key).sort((a, b) => a.hook - b.hook);
}

export function mergeRun(clip) {
  if (!clip.merge) return null;
  const parts = clip.merge.map((id) => state.byKey.get(`${clip.sid}/${id}`)).filter(Boolean);
  if (parts.length < 2) return null;
  return { parts, length: parts.at(-1).out - parts[0].hook };
}

export const fmt = {
  dur(s) { s = Math.max(0, Math.round(s)); const m = Math.floor(s / 60); return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}` : `${m}:${String(s % 60).padStart(2, '0')}`; },
  date(d) { return new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }); },
};
