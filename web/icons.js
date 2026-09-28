// One consistent line-icon set (24px grid, 1.6 stroke), drawn for Clip Scout.
import { html } from './vendor/preact-htm.js';

const P = {
  keep: '<path d="M5 12.5l4.5 4.5L19 7"/>',
  maybe: '<circle cx="12" cy="12" r="7.5"/><path class="f" d="M12 4.5a7.5 7.5 0 0 0 0 15z"/>',
  cut: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  play: '<path class="f" d="M8 5.5v13l10.5-6.5z"/>',
  pause: '<path d="M9 7v10M15 7v10"/>',
  prev: '<path d="M15 6l-6 6 6 6"/>', next: '<path d="M9 6l6 6-6 6"/>',
  yt: '<rect x="2.5" y="5.5" width="19" height="13" rx="3.5"/><path class="f" d="M10 9.2v5.6l4.8-2.8z"/>',
  x: '<path d="M5 4.5h3.6l10.4 15h-3.6z"/><path d="M18.5 4.5l-5.6 6.4M5.5 19.5l5.6-6.4"/>',
  music: '<path d="M9 17.5V6.5l10-2v11"/><circle cx="6.8" cy="17.5" r="2.2"/><circle cx="16.8" cy="15.5" r="2.2"/>',
  dated: '<path d="M7 4h10M7 20h10M8 4c0 4.5 4 5.5 4 8s-4 3.5-4 8M16 4c0 4.5-4 5.5-4 8s4 3.5 4 8"/>',
  verify: '<path d="M12 3.5l7 3v5c0 4.6-3 7.7-7 9-4-1.3-7-4.4-7-9v-5z"/><path d="M12 8.5v4.5M12 16v.2"/>',
  guest: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 19.5c1.3-3.6 3.9-5.2 7-5.2s5.7 1.6 7 5.2"/>',
  people: '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19c1-3 3-4.4 5.5-4.4s4.5 1.4 5.5 4.4"/><path d="M15 5.8a3 3 0 0 1 0 5.6M17 14.8c1.8.5 3 1.8 3.7 4.2"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-2.8 2.8a4 4 0 0 0 5.7 5.7l1-1"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.6-4.6"/>',
  import: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M4.5 15v2.5a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V15"/>',
  download: '<path d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/>',
  transcribe: '<path d="M4 11v2M7 8.5v7M10 5.5v13M13 8.5v7M16 6.5v11M19 10v4"/>',
  find: '<circle cx="12" cy="12" r="6.5"/><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4"/><circle class="f" cx="12" cy="12" r="1.4"/>',
  judge: '<path d="M12 4.2l2.3 4.8 5.2.7-3.8 3.6.9 5.2L12 16l-4.6 2.5.9-5.2-3.8-3.6 5.2-.7z"/>',
  edit: '<circle cx="6.5" cy="7" r="2.5"/><circle cx="6.5" cy="17" r="2.5"/><path d="M8.6 8.4L20 16.5M8.6 15.6L20 7.5"/>',
  ready: '<circle cx="12" cy="12" r="8"/><path d="M8.5 12.3l2.4 2.4 4.8-5"/>',
  nested: '<path d="M8 5H5v14h3M16 5h3v14h-3M9.5 12h5"/>',
  undo: '<path d="M9 7.5L5 11.5l4 4M5 11.5h9.5a4.5 4.5 0 0 1 0 9H12"/>',
  lock: '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  cal: '<rect x="4" y="5.5" width="16" height="14" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  sliders: '<path d="M5 7h9M18 7h1M5 17h3M12 17h7"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  chev: '<path d="M7 10l5 5 5-5"/>',
  upload: '<path d="M12 20V8.5M7 13l5-5 5 5M5 4h14"/>',
  filler: '<circle cx="12" cy="12" r="3.2"/><path d="M4.5 12h2.5M17 12h2.5"/>',
  tangent: '<path d="M4 16h4c2.5 0 2.5-8 5.5-8H20M16.5 4.5L20 8l-3.5 3.5"/>',
  fumble: '<path d="M3.5 14l3-4 3 4 3-4 3 4 3-4 2 2.7"/>',
  agent: '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M7.5 10l3 2.5-3 2.5M12.5 15.5h4"/>',
  top: '<path d="M12 4.5l2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5-3.6-3.5 5-.7z"/>',
  layers: '<path d="M12 4l8 4-8 4-8-4z"/><path d="M4 12l8 4 8-4M4 16l8 4 8-4"/>',
  spot: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  moon: '<path d="M19 14.5A7.5 7.5 0 1 1 9.5 5a6 6 0 0 0 9.5 9.5z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
  folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  external: '<path d="M13.5 4.5h6v6M19.5 4.5l-8 8M17 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7H10"/>',
  retry: '<path d="M19 12a7 7 0 1 1-2.1-5M19 4.5V9h-4.5"/>',
  alert: '<path d="M12 4l9 15.5H3z"/><path d="M12 10v4.5M12 17v.2"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
  punch: '<rect x="3.5" y="5.5" width="17" height="13" rx="1.5"/><rect x="8" y="9" width="8" height="6" rx="1"/><path d="M5.5 7.5L8 9M18.5 7.5L16 9M5.5 16.5L8 15M18.5 16.5L16 15"/>',
  hardcut: '<rect x="3.5" y="5.5" width="7" height="13" rx="1.5"/><rect x="13.5" y="5.5" width="7" height="13" rx="1.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  notelgato: '<circle cx="12" cy="12" r="8"/><path d="M6.5 17.5l11-11"/>',
  boring: '<path d="M5 6.5h6l-6 7h6M14 11h5l-5 6.5h5"/>',
  bounds: '<path d="M8 5H5v14h3M16 5h3v14h-3"/><path d="M9.5 12h5M12.5 10l2 2-2 2"/>',
  have: '<rect x="8" y="8" width="11.5" height="11.5" rx="2"/><path d="M5.5 15.5A1.5 1.5 0 0 1 4.5 14V6a1.5 1.5 0 0 1 1.5-1.5h8a1.5 1.5 0 0 1 1.5 1"/>',
  shield: '<path d="M12 3.5l7 3v5c0 4.6-3 7.7-7 9-4-1.3-7-4.4-7-9v-5z"/>',
  question: '<circle cx="12" cy="12" r="8"/><path d="M9.8 9.5a2.3 2.3 0 1 1 3.4 2c-.8.4-1.2 1-1.2 1.8M12 16.5v.2"/>',
  speed: '<path d="M4.5 16a8 8 0 1 1 15 0"/><path d="M12 13l3.5-4"/>',
  spinner: '<path d="M12 4a8 8 0 1 1-8 8"/>',
  mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M4 7l8 6 8-6"/>',
  sheet: '<rect x="4.5" y="3.5" width="15" height="17" rx="2"/><path d="M4.5 9h15M4.5 14.5h15M10 3.5v17"/>',
  key: '<circle cx="8" cy="15" r="3.5"/><path d="M10.5 12.5L19 4M16 7l2.5 2.5M14 9l2 2"/>',
};

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// Paths come only from the constant table above; a tooltip title is escaped.
export const Icon = ({ n, cls = '', title }) => html`<svg class=${`ic ${cls}`} viewBox="0 0 24 24" aria-hidden=${title ? undefined : 'true'}
  dangerouslySetInnerHTML=${{ __html: (title ? `<title>${esc(title)}</title>` : '') + (P[n] || '') }} />`;

export const FLAG_ICON = { music: 'music', 'music-faint': 'music', dated: 'dated', 'verify-claim': 'verify',
  'guest-creator': 'guest', gameplay: 'play', profanity: 'alert', 'third-party': 'external' };
export const FLAG_WORD = { music: 'Music heard', 'music-faint': 'Faint music', dated: 'Dated: deal or date',
  'verify-claim': 'Check a claim', 'guest-creator': 'Guest creator', gameplay: 'Game footage', profanity: 'Language',
  'third-party': 'Other brand', visual: 'Needs the screen' };

export const CUT_REASONS = [
  { k: 'not-elgato', icon: 'notelgato', t: 'Not about Elgato' },
  { k: 'boring', icon: 'boring', t: 'Boring' },
  { k: 'bad-bounds', icon: 'bounds', t: 'Bad start or end' },
  { k: 'dated', icon: 'dated', t: 'Dated' },
  { k: 'have-it', icon: 'have', t: 'Already have it' },
];
export const MAYBE_NEEDS = [
  { k: 'trim', icon: 'bounds', t: 'Trim start or end' },
  { k: 'dead-air', icon: 'pause', t: 'Remove dead air' },
  { k: 'rights', icon: 'shield', t: 'Bleep or rights check' },
  { k: 'combine', icon: 'nested', t: 'Combine with a nearby clip' },
  { k: 'claim', icon: 'question', t: 'Check a claim' },
];
