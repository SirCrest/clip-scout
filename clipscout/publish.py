"""Publishing kept clips to the Elgato Clips YouTube channel.

Flow: the titles task writes draft copy -> a person edits and approves it (approve) -> optionally schedule ->
upload (option B: the API uploads the rendered file) or sync (option A: someone drags files into YouTube Studio,
and sync matches them by original filename and fills in the approved copy). Every write first checks that the
signed-in channel is Elgato Clips, and nothing is uploaded twice.

State lives in library/publish.json, keyed "<stream id>/<clip id>":
  {status: draft|approved|uploaded|scheduled|public|failed, titles: [A, B, C], description, tags, playlist,
   category_id, video_id, url, publish_at (UTC ISO), uploaded_at, warnings, note, error, ...}
Daily API use is counted in library/publish-quota.json.

Platform facts this relies on, checked against Google's docs on 2026-09-28:
- Quota (developers.google.com/youtube/v3/determine_quota_cost): "Projects that enable the YouTube Data API have a
  default quota allocation of 100 search.list calls, 100 videos.insert calls, and 10,000 units per day combined for
  all other endpoints." videos.insert costs 1 call in its own bucket; videos.update 50, playlistItems.insert 50,
  captions.insert 400, thumbnails.set 50; videos.list, channels.list, playlists.list, playlistItems.list 1.
  More quota needs Google's audit (youtube/v3/guides/quota_and_compliance_audits). The docs don't say when the day
  resets; we count days in Pacific time, as the Cloud console does (unverified in the API docs).
- Private lock (youtube/v3/docs/videos/insert): "All videos uploaded via the videos.insert endpoint from unverified
  API projects created after 28 July 2020 will be restricted to private viewing mode." until the project is
  audited. The docs tie this to videos.insert only; whether videos.update can make a Studio-uploaded video public
  from an unaudited project is not documented (the one-video test decides option A vs. waiting for the audit).
- Fields (youtube/v3/docs/videos): title max 100 characters, description max 5000 bytes, neither may contain < or >;
  tags max 500 characters, commas count and a tag with a space counts as quoted; categoryId must be sent when
  updating snippet; publishAt "can only be set if the video's privacy status is private and the video has never
  been published" (ISO 8601); fileDetails.fileName is only visible to the video's owner.
- Sign-in (identity/protocols/oauth2, youtube/v3/guides/auth/installed-apps): desktop apps use a loopback redirect
  (http://127.0.0.1:port), the copy/paste OOB flow "is no longer supported"; an External + "Testing" consent screen
  gets refresh tokens "expiring in 7 days"; at most 100 refresh tokens per account per client, older ones are
  silently revoked.
"""
import csv
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import library as lib

CHANNEL_TITLE = 'Elgato Clips'
CHANNEL_ID = 'UCJulpl_UqH3L6NTmxU9k24Q'  # @ElgatoClips, from the public channel page
CATEGORY_ID = '22'  # People & Blogs: what every Elgato Clips video checked uses (elgato/youtube.md)
SCOPES = ['https://www.googleapis.com/auth/youtube', 'https://www.googleapis.com/auth/youtube.upload']
SECRETS = lib.ROOT / 'secrets'
CLIENT_FILE = SECRETS / 'google-client.json'
TOKEN_FILE = SECRETS / 'youtube-token.json'
COST = {'videos.update': 50, 'playlistItems.insert': 50, 'videos.list': 1, 'channels.list': 1,
        'playlists.list': 1, 'playlistItems.list': 1}
DAILY_UNITS, DAILY_UPLOADS, RESERVE_UNITS = 10_000, 100, 200
QUOTA_TZ = ZoneInfo('America/Los_Angeles')
DEFAULT_TZ = 'America/Los_Angeles'
LOCKED = ('approved', 'failed', 'uploaded', 'scheduled', 'public')  # a draft never replaces these
SENT = ('uploaded', 'scheduled', 'public')
UPLOADABLE = ('approved', 'failed')  # failed = approved copy whose upload broke; it can be retried
CHUNK = 32 * 1024 * 1024
RETRY_STATUS = (500, 502, 503, 504)


class PublishError(Exception):
    """A problem the user can fix; the message says how."""


# ---------------------------------------------------------------- state

def _path():
    return lib.LIBRARY / 'publish.json'


def load():
    return lib.read_json(_path(), {}) or {}


def _change(fn):
    with lib.locked(_path()):
        data = load()
        result = fn(data)
        lib.write_json(_path(), data)
    return result


def _blank():
    return {'status': 'draft', 'titles': [], 'description': '', 'tags': [], 'playlist': None,
            'category_id': CATEGORY_ID, 'video_id': None, 'url': None, 'publish_at': None, 'uploaded_at': None,
            'warnings': [], 'note': None, 'error': None}


def save_drafts(drafts):
    """Store drafts from the titles task. Approved or published copy is kept; the draft is filed as a suggestion."""
    def fn(data):
        for key, draft in drafts.items():
            entry = data.get(key)
            if entry and entry.get('status') in LOCKED:
                entry['suggestion'] = {**draft, 'at': lib.now()}
                continue
            data[key] = {**_blank(), **(entry or {}), **draft, 'status': 'draft', 'error': None,
                         'drafted_at': lib.now()}
    _change(fn)


def _settings():
    return lib.read_json(lib.LIBRARY / 'settings.json', {}) or {}


def _save_publish_settings(**values):
    path = lib.LIBRARY / 'settings.json'
    with lib.locked(path):
        data = lib.read_json(path, {}) or {}
        data.setdefault('publish', {}).update(values)
        lib.write_json(path, data)


def state():
    """Everything the Publish screen shows."""
    s = _settings().get('publish', {})
    return {'clips': load(), 'client_secrets': CLIENT_FILE.exists(), 'signed_in': TOKEN_FILE.exists(),
            'channel': {'id': s.get('channel_id'), 'title': s.get('channel_title')} if s.get('channel_id') else None,
            'audited': bool(s.get('audited')), 'quota': quota(), 'playlist_names': _playlist_names(),
            'category_id': CATEGORY_ID}


def _playlist_names():
    from .titles import playlists
    return playlists()


def check_copy(entry):
    """Problems that would make YouTube reject the copy (limits from the videos resource docs)."""
    from .titles import tags_length
    errors = []
    titles = entry.get('titles') or []
    if not titles or not titles[0].strip():
        errors.append('title A is empty')
    for n, t in zip('ABC', titles):
        if len(t) > 100:
            errors.append(f'title {n} is {len(t)} characters (max 100)')
        if '<' in t or '>' in t:
            errors.append(f'title {n} contains < or >')
    desc = entry.get('description') or ''
    if len(desc.encode('utf-8')) > 5000:
        errors.append(f'description is {len(desc.encode("utf-8"))} bytes (max 5,000)')
    if '<' in desc or '>' in desc:
        errors.append('description contains < or >')
    if tags_length(entry.get('tags') or []) > 500:
        errors.append('tags are over 500 characters')
    if any(',' in t for t in entry.get('tags') or []):
        errors.append('a tag contains a comma')
    return errors


def approve(key, fields):
    """Store the user's edited copy and mark it approved. fields may set titles, description, tags, playlist,
    category_id and note."""
    allowed = ('titles', 'description', 'tags', 'playlist', 'category_id', 'note')
    unknown = set(fields) - set(allowed)
    if unknown:
        return {'ok': False, 'error': f'unknown fields: {", ".join(sorted(unknown))}'}

    def fn(data):
        entry = {**_blank(), **data.get(key, {})}
        if entry['status'] in SENT:
            return {'ok': False, 'error': 'already on YouTube; change it in YouTube Studio'}
        entry.update({k: fields[k] for k in allowed if k in fields})
        if isinstance(entry.get('titles'), str):
            entry['titles'] = [entry['titles']]
        problems = check_copy(entry)
        if problems:
            return {'ok': False, 'error': '; '.join(problems)}
        entry.update(status='approved', approved_at=lib.now(), error=None)
        data[key] = entry
        return {'ok': True, 'entry': entry}
    return _change(fn)


def schedule(keys, start, per_day=1, at_time='17:00', tz=None, now=None):
    """Give each clip (in the order given) a publish time: per_day slots a day from `start` (YYYY-MM-DD), at
    `at_time` ("HH:MM", or a list of them; one time with per_day > 1 means slots two hours apart) in `tz`. Slots
    less than 15 minutes away are skipped. Nothing is sent: upload applies publish_at to approved clips."""
    zone = ZoneInfo(tz or DEFAULT_TZ)
    times = at_time if isinstance(at_time, (list, tuple)) else [at_time]
    per_day = max(int(per_day or 1), 1)
    if len(times) == 1 and per_day > 1:
        h, m = map(int, times[0].split(':'))
        times = [f'{(h + 2 * i) % 24:02d}:{m:02d}' for i in range(per_day)]
    times = sorted(times[:per_day])
    now = now or datetime.now(timezone.utc)
    earliest = now + timedelta(minutes=15)

    def slots():
        day = date.fromisoformat(start)
        while True:
            for t in times:
                h, m = map(int, t.split(':'))
                local = datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
                if local.astimezone(timezone.utc) >= earliest:
                    yield local
            day += timedelta(days=1)

    def fn(data):
        planned, skipped, gen = [], [], slots()
        for key in dict.fromkeys(keys):
            entry = data.get(key)
            if not entry or entry.get('status') in SENT:
                skipped.append({'key': key, 'reason': 'already on YouTube' if entry else 'no copy yet'})
                continue
            local = next(gen)
            entry['publish_at'] = local.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            entry['publish_at_local'] = local.isoformat(timespec='minutes')
            planned.append({'key': key, 'publish_at': entry['publish_at'], 'local': entry['publish_at_local']})
        return {'ok': True, 'planned': planned, 'skipped': skipped, 'tz': str(zone)}
    return _change(fn)


def unschedule(keys):
    def fn(data):
        for key in keys:
            if key in data and data[key].get('status') not in SENT:
                data[key]['publish_at'] = data[key]['publish_at_local'] = None
        return {'ok': True}
    return _change(fn)


# ---------------------------------------------------------------- quota

def _quota_path():
    return lib.LIBRARY / 'publish-quota.json'


def _today():
    return datetime.now(QUOTA_TZ).date().isoformat()


def quota():
    q = lib.read_json(_quota_path(), {}) or {}
    if q.get('day') != _today():
        q = {'day': _today(), 'units': 0, 'uploads': 0}
    return {**q, 'units_left': DAILY_UNITS - q['units'], 'uploads_left': DAILY_UPLOADS - q['uploads']}


def _spend(units=0, uploads=0):
    with lib.locked(_quota_path()):
        q = quota()
        if q['units'] + units > DAILY_UNITS - RESERVE_UNITS or q['uploads'] + uploads > DAILY_UPLOADS:
            raise QuotaExhausted(f"today's YouTube API quota is used up ({q['units']} units, {q['uploads']} "
                                 f"uploads); the rest can go tomorrow")
        lib.write_json(_quota_path(), {'day': q['day'], 'units': q['units'] + units,
                                       'uploads': q['uploads'] + uploads})


def _can_spend(units=0, uploads=0):
    q = quota()
    return q['units'] + units <= DAILY_UNITS - RESERVE_UNITS and q['uploads'] + uploads <= DAILY_UPLOADS


class QuotaExhausted(PublishError):
    pass


# ---------------------------------------------------------------- Google sign-in and API

def _need_libs():
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
    except ImportError:
        raise PublishError(f'the publish extra is missing: run {lib.uv("sync --inexact --extra publish")}')


def _credentials():
    _need_libs()
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    if not TOKEN_FILE.exists():
        raise PublishError('not signed in to YouTube yet: use Sign in with Google')
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if not creds.refresh_token:
            raise PublishError('the YouTube sign-in has no refresh token; sign in again')
        try:
            creds.refresh(Request())
        except RefreshError:
            raise PublishError('the YouTube sign-in expired; sign in again (a Cloud project in "Testing" mode '
                               'makes sign-ins expire after 7 days)')
        _write_token(creds)
    return creds


def _write_token(creds):
    SECRETS.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding='utf-8')


def _service():
    from googleapiclient.discovery import build
    return build('youtube', 'v3', credentials=_credentials(), cache_discovery=False)


def _execute(request, method):
    """Run one API request, counting its quota and retrying server errors."""
    from googleapiclient.errors import HttpError
    _spend(units=COST.get(method, 1))
    for attempt in range(5):
        try:
            return request.execute()
        except HttpError as e:
            if getattr(e, 'status_code', None) in RETRY_STATUS or getattr(e.resp, 'status', None) in RETRY_STATUS:
                time.sleep(2 ** attempt)
                continue
            raise
    return request.execute()


def signin():
    """Open Google's sign-in in the browser (loopback redirect), save the token, then check the channel."""
    try:
        _need_libs()
        from google_auth_oauthlib.flow import InstalledAppFlow
        if not CLIENT_FILE.exists():
            raise PublishError(f'put the Google Cloud OAuth client file (Desktop app) at {CLIENT_FILE}')
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        creds = flow.run_local_server(host='127.0.0.1', port=0, open_browser=True, prompt='select_account consent',
                                      success_message='Signed in. You can close this tab and go back to Clip Scout.')
        _write_token(creds)
    except PublishError as e:
        return {'ok': False, 'error': str(e)}
    result = channel()
    if not result['ok']:
        TOKEN_FILE.unlink(missing_ok=True)  # never keep a sign-in that points at the wrong channel
    return result


def _check_channel(yt):
    items = _execute(yt.channels().list(part='snippet', mine=True), 'channels.list').get('items', [])
    if len(items) != 1:
        raise PublishError(f'the signed-in account has {len(items)} YouTube channels selected; sign in again and '
                           f'pick {CHANNEL_TITLE}')
    ch = items[0]
    title = ch['snippet']['title']
    if ch['id'] != CHANNEL_ID or title != CHANNEL_TITLE:
        raise PublishError(f'signed in to "{title}" ({ch["id"]}), not {CHANNEL_TITLE}; sign in again and pick the '
                           f'{CHANNEL_TITLE} channel. Nothing was changed.')
    saved = _settings().get('publish', {}).get('channel_id')
    if saved and saved != ch['id']:
        raise PublishError('this sign-in is for a different channel than the one saved; nothing was changed')
    if saved != ch['id']:
        _save_publish_settings(channel_id=ch['id'], channel_title=title)
    return {'id': ch['id'], 'title': title}


def channel():
    try:
        return {'ok': True, 'channel': _check_channel(_service())}
    except PublishError as e:
        return {'ok': False, 'error': str(e)}


# ---------------------------------------------------------------- upload (option B) and sync (option A)

def _renders():
    return lib.read_json(lib.LIBRARY / 'renders.json', {}) or {}


def _body(entry, include_status=True):
    snippet = {'title': entry['titles'][0], 'description': entry.get('description') or '',
               'tags': entry.get('tags') or [], 'categoryId': entry.get('category_id') or CATEGORY_ID,
               'defaultLanguage': 'en', 'defaultAudioLanguage': 'en'}
    body = {'snippet': snippet}
    if include_status:
        status = {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': False}
        if _future(entry.get('publish_at')):
            status['publishAt'] = entry['publish_at']
        body['status'] = status
    return body


def _future(stamp):
    if not stamp:
        return False
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')) > datetime.now(timezone.utc) + timedelta(minutes=5)


def _record(key, **values):
    def fn(data):
        data.setdefault(key, _blank()).update(values)
    _change(fn)


class _Playlists:
    """The channel's playlists by title, read once per run."""

    def __init__(self, yt):
        self.yt, self.by_title = yt, None

    def find(self, title):
        if self.by_title is None:
            self.by_title, token = {}, None
            while True:
                resp = _execute(self.yt.playlists().list(part='snippet', mine=True, maxResults=50, pageToken=token),
                                'playlists.list')
                for p in resp.get('items', []):
                    self.by_title[p['snippet']['title'].casefold()] = p['id']
                token = resp.get('nextPageToken')
                if not token:
                    break
        return self.by_title.get((title or '').casefold())


def _add_to_playlist(yt, playlists, key, entry, video_id, missing):
    name = entry.get('playlist')
    if not name:
        return
    pid = playlists.find(name)
    if not pid:
        missing.add(name)
        return
    if not _can_spend(units=COST['playlistItems.insert']):
        return
    _execute(yt.playlistItems().insert(part='snippet', body={'snippet': {
        'playlistId': pid, 'resourceId': {'kind': 'youtube#video', 'videoId': video_id}}}), 'playlistItems.insert')
    _record(key, playlist_added=True)


def _links(video_id):
    return {'url': f'https://youtu.be/{video_id}', 'studio_url': f'https://studio.youtube.com/video/{video_id}/edit'}


def upload(keys, progress=print):
    """Upload approved, rendered clips as private videos (with publishAt when scheduled). Returns a summary."""
    summary = {'ok': True, 'uploaded': [], 'skipped': [], 'missing_playlists': [], 'stopped': None}
    try:
        yt = _service()
        _check_channel(yt)
    except PublishError as e:
        return {**summary, 'ok': False, 'error': str(e)}
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    data, renders, playlists, missing = load(), _renders(), _Playlists(yt), set()
    for key in dict.fromkeys(keys):
        entry = data.get(key)
        render = renders.get(key)
        reason = None
        if not entry or entry.get('status') not in UPLOADABLE:
            reason = 'copy not approved' if not entry or entry.get('status') not in SENT else 'already on YouTube'
        elif entry.get('video_id'):
            reason = 'already on YouTube'
        elif not render or not (lib.LIBRARY / render['path']).exists():
            reason = 'not rendered yet'
        elif entry.get('publish_at') and not _future(entry['publish_at']):
            reason = 'its publish time has passed; schedule it again'
        if reason:
            summary['skipped'].append({'key': key, 'reason': reason})
            continue
        if entry.get('upload_started_at'):  # an earlier run may have finished uploading before it crashed
            found = _find_uploaded(yt, Path(render['path']).name)
            if found:
                _record(key, video_id=found['id'], status=_status_of(found), **_links(found['id']),
                        uploaded_at=lib.now(), error=None)
                summary['uploaded'].append({'key': key, 'video_id': found['id'], 'recovered': True})
                continue
        if not _can_spend(units=COST['playlistItems.insert'], uploads=1):
            summary['stopped'] = "today's YouTube quota is used up; the rest can go tomorrow"
            break
        path = lib.LIBRARY / render['path']
        title = entry['titles'][0]
        _record(key, upload_started_at=lib.now())
        try:
            _spend(uploads=1)
            media = MediaFileUpload(str(path), mimetype='video/mp4', chunksize=CHUNK, resumable=True)
            request = yt.videos().insert(part='snippet,status', body=_body(entry), media_body=media)
            response, failures = None, 0
            while response is None:
                try:
                    status, response = request.next_chunk()
                    failures = 0
                    if status:
                        progress(f'Uploading {title}: {int(status.progress() * 100)}%')
                except HttpError as e:
                    if getattr(e.resp, 'status', None) not in RETRY_STATUS or failures >= 5:
                        raise
                    failures += 1
                    time.sleep(2 ** failures)
                except (ConnectionError, TimeoutError, OSError):
                    if failures >= 5:
                        raise
                    failures += 1
                    time.sleep(2 ** failures)
        except QuotaExhausted as e:
            summary['stopped'] = str(e)
            break
        except Exception as e:
            _record(key, status='failed', error=f'{type(e).__name__}: {e}')
            summary['skipped'].append({'key': key, 'reason': f'upload failed: {e}'})
            continue
        video_id = response['id']
        scheduled = 'publishAt' in _body(entry)['status']
        _record(key, video_id=video_id, status='scheduled' if scheduled else 'uploaded', uploaded_at=lib.now(),
                file=render['path'], error=None, **_links(video_id))
        progress(f'Uploaded {title}')
        try:
            _add_to_playlist(yt, playlists, key, entry, video_id, missing)
        except PublishError as e:
            summary['stopped'] = str(e)
        summary['uploaded'].append({'key': key, 'video_id': video_id, 'scheduled': scheduled})
        if summary['stopped']:
            break
    summary['missing_playlists'] = sorted(missing)
    if summary['uploaded'] and not _settings().get('publish', {}).get('audited'):
        summary['note'] = ('Until Google audits the Cloud project, videos uploaded through the API stay private, '
                           'and schedules may not apply. Check them in YouTube Studio.')
    return summary


def _status_of(video):
    s = video.get('status', {})
    if s.get('privacyStatus') == 'public':
        return 'public'
    return 'scheduled' if s.get('publishAt') else 'uploaded'


def _recent_uploads(yt, pages=4):
    """The channel's most recent uploads (videos with fileDetails, snippet, status), newest first."""
    items = _execute(yt.channels().list(part='contentDetails', mine=True), 'channels.list').get('items', [])
    if not items:
        return []
    uploads = items[0]['contentDetails']['relatedPlaylists']['uploads']
    ids, token = [], None
    for _ in range(pages):
        resp = _execute(yt.playlistItems().list(part='contentDetails', playlistId=uploads, maxResults=50,
                                                pageToken=token), 'playlistItems.list')
        ids += [i['contentDetails']['videoId'] for i in resp.get('items', [])]
        token = resp.get('nextPageToken')
        if not token:
            break
    videos = []
    for i in range(0, len(ids), 50):
        resp = _execute(yt.videos().list(part='fileDetails,snippet,status', id=','.join(ids[i:i + 50])),
                        'videos.list')
        videos += resp.get('items', [])
    return videos


def _find_uploaded(yt, filename):
    for v in _recent_uploads(yt, pages=1):
        if (v.get('fileDetails', {}).get('fileName') or '').casefold() == filename.casefold():
            return v
    return None


def sync():
    """Option A: match videos uploaded in Studio to rendered clips by original filename, fill in approved copy on
    ones that are still private and unpublished, and refresh the status of everything already linked."""
    summary = {'ok': True, 'filled': [], 'linked': [], 'refreshed': [], 'unmatched': [], 'duplicates': [],
               'missing_playlists': [], 'stopped': None}
    try:
        yt = _service()
        _check_channel(yt)
        videos = _recent_uploads(yt)
    except PublishError as e:
        return {**summary, 'ok': False, 'error': str(e)}
    by_file = {Path(r['path']).name.casefold(): key for key, r in _renders().items() if r.get('path')}
    data, playlists, missing, seen = load(), _Playlists(yt), set(), {}
    by_video = {e['video_id']: k for k, e in data.items() if e.get('video_id')}
    for v in videos:
        vid = v['id']
        if vid in by_video:
            key = by_video[vid]
            new = _status_of(v)
            if data[key].get('status') != new:
                _record(key, status=new)
                summary['refreshed'].append({'key': key, 'status': new})
            continue
        name = (v.get('fileDetails', {}).get('fileName') or '').casefold()
        key = by_file.get(name)
        if not key:
            summary['unmatched'].append({'video_id': vid, 'file': v.get('fileDetails', {}).get('fileName')})
            continue
        if key in seen:
            summary['duplicates'].append({'key': key, 'video_ids': [seen[key], vid]})
            continue
        seen[key] = vid
        entry = {**_blank(), **data.get(key, {})}
        if entry.get('video_id'):
            continue
        status = v.get('status', {})
        fresh = status.get('privacyStatus') == 'private' and not status.get('publishAt')
        if entry['status'] == 'approved' and fresh:
            if not _can_spend(units=COST['videos.update'] + COST['playlistItems.insert']):
                summary['stopped'] = "today's YouTube quota is used up; run sync again tomorrow"
                break
            try:
                _execute(yt.videos().update(part='snippet,status', body={'id': vid, **_body(entry)}), 'videos.update')
                _add_to_playlist(yt, playlists, key, entry, vid, missing)
            except PublishError as e:
                summary['stopped'] = str(e)
                break
            scheduled = 'publishAt' in _body(entry)['status']
            _record(key, video_id=vid, status='scheduled' if scheduled else 'uploaded', uploaded_at=lib.now(),
                    synced_at=lib.now(), error=None, **_links(vid))
            summary['filled'].append({'key': key, 'video_id': vid})
        else:
            warning = ('uploaded in Studio before its copy was approved' if entry['status'] != 'approved'
                       else 'already published or scheduled in Studio; copy left as it is')
            _record(key, video_id=vid, status=_status_of(v), synced_at=lib.now(),
                    warnings=sorted(set(entry.get('warnings') or []) | {warning}), **_links(vid))
            summary['linked'].append({'key': key, 'video_id': vid, 'warning': warning})
    summary['missing_playlists'] = sorted(missing)
    return summary


# ---------------------------------------------------------------- sheet and CLI

def sheet():
    """library/publish-sheet.csv: everything needed to publish by hand (opens in Excel)."""
    path = lib.LIBRARY / 'publish-sheet.csv'
    renders = _renders()
    cols = ['key', 'status', 'file', 'title_a', 'title_b', 'title_c', 'description', 'tags', 'playlist',
            'publish_at', 'video_url', 'studio_url', 'warnings', 'note']
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(cols)
        for key, e in sorted(load().items()):
            titles = (e.get('titles') or []) + ['', '', '']
            w.writerow([key, e.get('status'), (renders.get(key) or {}).get('path', ''), *titles[:3],
                        e.get('description', ''), ', '.join(e.get('tags') or []), e.get('playlist') or '',
                        e.get('publish_at_local') or e.get('publish_at') or '', e.get('url') or '',
                        e.get('studio_url') or '', '; '.join(e.get('warnings') or []), e.get('note') or ''])
    return {'ok': True, 'path': str(path)}


def kept_youtube_keys():
    """Kept clips headed for YouTube (staff side, or not judged)."""
    from . import decisions
    out = []
    for key, v in decisions.load()['decisions'].items():
        if v.get('d') != 'keep':
            continue
        sid, cid = key.split('/', 1)
        try:
            clip = next((c for c in lib.get_stream(sid).clips() if c['id'] == cid), None)
        except KeyError:
            continue
        if clip and (clip.get('judge') or {}).get('side') != 'community':
            out.append(key)
    return out


def cli(action, keys):
    if action == 'metadata':
        from .titles import open_tasks_for
        ids = open_tasks_for(keys or kept_youtube_keys())
        print('\n'.join(ids) or 'Nothing to write: every kept YouTube clip already has copy.')
        if ids:
            print(f'Run {lib.uv("run scout work")} (or open the tasks with your agent) to write them.')
        return 0
    if action == 'upload':
        if not keys:
            print('Name the clips to upload (keys like tw2805139766/t016377), or "all" for every approved clip.')
            return 1
        if keys == ['all']:
            keys = [k for k, e in load().items() if e.get('status') in UPLOADABLE and not e.get('video_id')]
        result = upload(keys)
    elif action in ('signin', 'channel', 'sync', 'sheet'):
        result = globals()[action]()
    else:
        print(f'unknown action {action}')
        return 1
    for k, v in result.items():
        print(f'{k}: {v}')
    return 0 if result.get('ok') else 1
