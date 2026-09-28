// Publish: kept clips get three titles and a description from your agent; you approve; Clip Scout uploads them to
// Elgato Clips as private videos on a schedule you set (or gives you a sheet to copy from).
import { html, useEffect, useMemo, useState } from '../vendor/preact-htm.js';
import { Icon } from '../icons.js';
import { api } from '../api.js';
import { state, fmt, toast, lane } from '../store.js';

const SENT = new Set(['uploaded', 'scheduled', 'public']);
const WORD = { draft: 'Draft', approved: 'Approved', uploaded: 'Uploaded', scheduled: 'Scheduled', public: 'Live', failed: 'Failed' };
const bytes = (s) => new TextEncoder().encode(s || '').length;

function usePublish() {
  const [p, set] = useState(null);
  const load = () => api.publish().then(set).catch((e) => set({ error: e.message, clips: {} }));
  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, []);
  return [p, load];
}

function Slot({ i, value, onInput }) {
  const n = [...(value || '')].length, over = n > 100;
  return html`<div class=${`slot ${i === 0 ? 'a' : ''}`}><b>${'ABC'[i]}</b>
    <input value=${value} onInput=${(e) => onInput(e.target.value)} aria-label=${`Title ${'ABC'[i]}`} maxlength="100" />
    <span class=${`len ${over ? 'over' : ''}`} title="Elgato Clips titles run about 55 to 75 characters"><i style=${`--p:${Math.min(100, n)}%`}></i><span class="num">${n}</span></span></div>`;
}

export function Publish({ go }) {
  const [p, reload] = usePublish();
  const [renders, setRenders] = useState({});
  useEffect(() => { const l = () => api.renders().then(setRenders).catch(() => {}); l(); const t = setInterval(l, 6000); return () => clearInterval(t); }, []);
  const [dest, setDest] = useState('yt');
  const dec = state.decisions.decisions;
  const kept = useMemo(() => Object.entries(dec).filter(([k, v]) => v.d === 'keep' && state.byKey.get(k))
    .map(([k, v]) => ({ clip: state.byKey.get(k), at: v.at })).sort((a, b) => (b.at || '').localeCompare(a.at || '')), [dec, state.clips]);
  const list = kept.filter((x) => lane(x.clip) === dest);
  const [selKey, setSelKey] = useState(null);
  useEffect(() => { if (!list.some((x) => x.clip.key === selKey)) setSelKey(list[0]?.clip.key || null); }, [list.length, dest]);
  const c = selKey && state.byKey.get(selKey);
  const entry = (c && p?.clips?.[c.key]) || null;
  const [draft, setDraft] = useState(null);
  useEffect(() => { setDraft(entry ? { titles: [...(entry.titles || []), '', '', ''].slice(0, 3), description: entry.description || '', playlist: entry.playlist || '' } : null); }, [selKey, entry?.status, entry?.titles?.join('|')]);
  const [confirm, setConfirm] = useState(false);
  const [plan, setPlan] = useState({ start: new Date(Date.now() + 864e5).toISOString().slice(0, 10), per_day: 1, at: '17:00' });

  const noCopy = list.filter((x) => !p?.clips?.[x.clip.key]?.titles?.length).map((x) => x.clip.key);
  const approved = list.filter((x) => p?.clips?.[x.clip.key]?.status === 'approved');
  const ready = approved.filter((x) => renders[x.clip.key]);

  async function act(action, body, done) {
    try { const r = await api.publishAction(action, body); const res = r.result ?? r; if (res.ok === false) toast(res.error || 'That didn\'t work'); else done?.(res); reload(); }
    catch (e) { toast(e.message); }
  }
  const approve = () => act('approve', { key: c.key, fields: { titles: draft.titles.filter(Boolean), description: draft.description, playlist: draft.playlist || null } }, () => toast('Approved'));

  const post = c ? state.decisions.posts[c.key] ?? '' : '';

  return html`<div class="space pub">
    <aside class="panel eq">
      <div class="bin-head">
        <button class=${`lane-btn yt ${dest === 'yt' ? 'on' : ''}`} onClick=${() => setDest('yt')}><${Icon} n="yt" /><span class="num">${kept.filter((x) => lane(x.clip) === 'yt').length}</span></button>
        <button class=${`lane-btn x ${dest === 'x' ? 'on' : ''}`} onClick=${() => setDest('x')}><${Icon} n="x" /><span class="num">${kept.filter((x) => lane(x.clip) === 'x').length}</span></button>
        <span class="sp" style="flex:1"></span>
        ${dest === 'yt' && noCopy.length ? html`<button class="btn" title="Have your agent write titles and descriptions" onClick=${() => act('metadata', { keys: noCopy }, (r) => toast(`${r.tasks.length} writing task${r.tasks.length === 1 ? '' : 's'} for your agent`))}>
          <${Icon} n="agent" /><span class="num">${noCopy.length}</span></button>` : null}
      </div>
      <div class="pq-list" style="flex:1">
        ${list.length ? list.map(({ clip }) => { const e = p?.clips?.[clip.key]; const r = renders[clip.key]; return html`
          <button class=${`eqi ${lane(clip)} ${clip.key === selKey ? 'on' : ''}`} onClick=${() => setSelKey(clip.key)}>
            <span class="poster"><img src=${`/thumb/${clip.key}`} alt="" loading="lazy" /></span>
            <span><h4>${e?.titles?.[0] || clip.title}</h4><span class="when">
              ${dest === 'yt' ? html`<span class=${`status-pill ${e?.status || ''}`}>${e ? WORD[e.status] : 'No copy yet'}</span>` : null}
              ${e?.publish_at ? html`<span class="num"><${Icon} n="cal" /> ${new Date(e.publish_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span>` : null}</span></span>
            <span class=${`st ${r ? 'ready' : ''}`} title=${r ? 'Rendered' : 'Not rendered yet'}><${Icon} n=${r ? 'ready' : 'clock'} /></span></button>`; })
          : html`<div class="empty"><${Icon} n=${dest} /><b>No kept clips here yet</b><button class="btn" onClick=${() => go('review')}><${Icon} n="grid" />Go sort clips</button></div>`}
      </div>
    </aside>

    <section class="viewer">
      ${c ? html`<div class="frame">${renders[c.key]
          ? html`<video src=${`/out/${c.key}`} controls preload="metadata" poster=${`/thumb/${c.key}`}></video>`
          : html`<img class="poster" src=${`/thumb/${c.key}`} alt="" /><span class="tc">Rendering…</span>`}</div>
        ${dest === 'yt' ? html`<div class="panel strip-panel">
          ${draft ? html`<div class="slots">${draft.titles.map((t, i) => html`<${Slot} i=${i} value=${t} onInput=${(v) => setDraft({ ...draft, titles: draft.titles.map((x, j) => (j === i ? v : x)) })} />`)}</div>
            <textarea class="field" rows="5" value=${draft.description} onInput=${(e) => setDraft({ ...draft, description: e.target.value })} aria-label="Description"
              disabled=${SENT.has(entry.status)}></textarea>
            <div class="row"><span class=${`dim num ${bytes(draft.description) > 5000 ? 'over' : ''}`} style="font-size:12px">${bytes(draft.description)} / 5000 bytes · B and C go into YouTube's title test</span>
              ${!SENT.has(entry.status) ? html`<button class="btn hot" onClick=${approve}><${Icon} n="check" />${entry.status === 'approved' ? 'Save' : 'Approve'}</button>` : null}</div>`
          : html`<div class="empty" style="min-height:120px"><${Icon} n="agent" /><span>No titles yet. Your agent writes three and a description.</span>
              <button class="btn hot" onClick=${() => act('metadata', { keys: [c.key] }, () => toast('Asked your agent to write them'))}><${Icon} n="agent" />Write them</button></div>`}
        </div>` : html`<div class="panel strip-panel post">
          <textarea class="field" rows="4" value=${post} onInput=${(e) => { state.decisions.posts[c.key] = e.target.value; }} onBlur=${(e) => api.post(c.key, e.target.value)} aria-label="Post"></textarea>
          <div class="row"><span class="dim num" style="font-size:12px">${post.length} / 280</span>
            <div class="row"><button class="btn" onClick=${() => { navigator.clipboard?.writeText(post); toast('Copied'); }}><${Icon} n="copy" /></button>
              ${renders[c.key] ? html`<button class="btn" onClick=${() => api.reveal(c.key)}><${Icon} n="folder" /></button>` : null}
              <a class="btn hot" href=${`https://x.com/intent/post?text=${encodeURIComponent(post)}`} target="_blank" rel="noreferrer"><${Icon} n="x" />Post</a></div></div></div>`}
        ${entry?.warnings?.length ? html`<div class="warns">${entry.warnings.map((w) => html`<div><${Icon} n="alert" /><span>${w}</span></div>`)}</div>` : null}
      ` : html`<div class="panel" style="flex:1"><div class="empty"><${Icon} n="upload" /><span>Kept clips get their titles here.</span></div></div>`}
    </section>

    <aside class="panel pside">
      ${dest === 'yt' ? html`
        <div class="chan"><div class=${`av ${p?.channel ? '' : 'off'}`}>EC</div><div><b>Elgato Clips</b>
          <span>${p?.channel ? html`<${Icon} n="check" cls="ok" />Connected` : p?.signed_in ? 'Checking…' : 'Not connected'}</span></div></div>
        ${!p?.channel ? html`<div class="warns"><div><${Icon} n="key" /><span>${p?.client_secrets
            ? 'Sign in with the Google account that manages Elgato Clips.'
            : 'Needs a Google Cloud sign-in file first (secrets/google-client.json). Until then, approve copy here and export the sheet.'}</span></div>
          ${p?.client_secrets ? html`<button class="btn hot" onClick=${() => act('signin', {}, () => toast('Connected to Elgato Clips'))}><${Icon} n="yt" />Sign in</button>` : null}</div>` : null}
        <div class="line"><${Icon} n="lock" /><span>Uploads stay private until they're scheduled</span></div>
        <div class="sec"><div class="sech"><${Icon} n="cal" /><span>Schedule the approved</span></div>
          <div class="form"><label>From</label><input class="field" type="date" value=${plan.start} onInput=${(e) => setPlan({ ...plan, start: e.target.value })} />
            <label>Per day</label><div class="stepper"><button onClick=${() => setPlan({ ...plan, per_day: Math.max(1, plan.per_day - 1) })}><${Icon} n="minus" /></button><b class="num">${plan.per_day}</b><button onClick=${() => setPlan({ ...plan, per_day: plan.per_day + 1 })}><${Icon} n="plus" /></button></div>
            <label>At</label><input class="field" type="time" value=${plan.at} onInput=${(e) => setPlan({ ...plan, at: e.target.value })} /></div>
          <button class="btn" disabled=${!approved.length} onClick=${() => act('schedule', { keys: approved.map((x) => x.clip.key), start: plan.start, per_day: plan.per_day, at_time: plan.at, tz: Intl.DateTimeFormat().resolvedOptions().timeZone }, (r) => toast(`${r.planned?.length ?? 0} scheduled (not sent yet)`))}>
            <${Icon} n="cal" />Plan <span class="num">${approved.length}</span></button></div>
        ${p?.quota ? html`<div class="line"><${Icon} n="speed" /><span class="num">${p.quota.uploads_left} uploads · ${p.quota.units_left} units left today</span></div>` : null}
        <div class="sec">
          ${confirm ? html`<div class="warns"><div><${Icon} n="upload" /><span>Upload <b class="num">${ready.length}</b> to Elgato Clips as private videos${ready.some((x) => p.clips[x.clip.key].publish_at) ? ', each going live at its scheduled time' : ''}?</span></div>
              <div class="row"><button class="btn" onClick=${() => setConfirm(false)}><${Icon} n="cut" /></button>
                <button class="btn hot" onClick=${() => { setConfirm(false); act('upload', { keys: ready.map((x) => x.clip.key), confirm: 'upload' }, (r) => toast(`${r.uploaded?.length ?? 0} uploaded`)); }}><${Icon} n="upload" />Upload</button></div></div>`
          : html`<button class="btn hot" disabled=${!p?.channel || !ready.length} onClick=${() => setConfirm(true)} title=${!p?.channel ? 'Connect Elgato Clips first' : ''}><${Icon} n="upload" />Upload <span class="num">${ready.length}</span></button>`}
          <div class="row"><button class="btn" onClick=${() => act('sheet', {}, (r) => toast(`Sheet saved: ${r.path}`))} title="Everything in a spreadsheet to copy from"><${Icon} n="sheet" />Sheet</button>
            ${p?.channel ? html`<button class="btn" onClick=${() => act('sync', {}, () => toast('Synced with YouTube'))} title="Match videos you uploaded in Studio"><${Icon} n="retry" />Sync</button>` : null}</div>
        </div>
        ${entry?.url ? html`<a class="line" href=${entry.url} target="_blank" rel="noreferrer"><${Icon} n="external" /><span>Open on YouTube</span></a>` : null}`
      : html`<div class="line"><${Icon} n="x" /><span>Community clips go to X with a short post crediting the creator.</span></div>
        <div class="line"><${Icon} n="folder" /><span>Attach the rendered file from the folder.</span></div>`}
    </aside>
  </div>`;
}
