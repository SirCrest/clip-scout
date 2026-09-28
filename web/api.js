// Talks to the local Clip Scout server. Every write carries the X-Clip-Scout header the server requires.

const H = { 'Content-Type': 'application/json', 'X-Clip-Scout': '1' };

async function check(res) {
  if (res.ok) return res.json();
  let msg = res.statusText;
  try { const j = await res.json(); msg = j.detail || j.error || msg; } catch {}
  throw new Error(msg);
}

export const get = (path) => fetch(path).then(check);
export const post = (path, body = {}) =>
  fetch(path, { method: 'POST', headers: H, body: JSON.stringify(body) }).then(check);

export const api = {
  overview: () => get('/api/overview'),
  clips: () => get('/api/clips'),
  clip: (key) => get(`/api/clip/${key}`),
  decisions: () => get('/api/decisions'),
  decide: (key, d, why = null) => post('/api/decide', { key, d, why }),
  reason: (key, why) => post('/api/reason', { key, why }),
  seen: (keys) => post('/api/seen', { keys }),
  post: (key, text) => post('/api/post', { key, text }),
  merge: (keys) => post('/api/merge', { keys }),
  settings: () => get('/api/settings'),
  saveSettings: (s) => post('/api/settings', s),
  tasks: () => get('/api/tasks'),
  retryTask: (id) => post(`/api/task/${id}/retry`),
  retryStream: (sid, stage) => post(`/api/stream/${sid}/retry`, { stage }),
  ingest: (source) => post('/api/ingest', /^https?:/i.test(source) ? { url: source } : { path: source }),
  edit: (key) => get(`/api/edit/${key}`),
  saveEdit: (key, changes) => post(`/api/edit/${key}`, changes),
  render: (key) => post(`/api/render/${key}`),
  reveal: (key) => post('/api/reveal', { key }),
  publish: () => get('/api/publish'),
  publishAction: (action, body = {}) => post(`/api/publish/${action}`, body),
};

// Streams a dropped file to the server with progress (fetch can't report upload progress; XHR can).
export function upload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('PUT', `/api/upload?name=${encodeURIComponent(file.name)}`);
    x.setRequestHeader('X-Clip-Scout', '1');
    x.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    x.onload = () => (x.status < 300 ? resolve(JSON.parse(x.responseText)) : reject(new Error(x.responseText)));
    x.onerror = () => reject(new Error('upload failed'));
    x.send(file);
  });
}

// The server pushes the overview whenever it changes.
export function events(onOverview) {
  let es, retry;
  const open = () => {
    es = new EventSource('/api/events');
    es.onmessage = (e) => onOverview(JSON.parse(e.data));
    es.onerror = () => { es.close(); retry = setTimeout(open, 2000); };
  };
  open();
  return () => { clearTimeout(retry); es?.close(); };
}
