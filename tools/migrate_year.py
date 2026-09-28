"""One-off: move the 2025-09 to 2026-09 year set into the Clip Scout library.

For every VOD in the year manifest (plus the Spanish VOD that sat beside them): create the stream folder, move
the VOD in as source.mp4 (a rename on the same volume), and copy its transcript, sentences, corrections, picks,
keyframes, music scores, judge results and thumbnails into the library format, re-keyed from the year set's file
paths and cNNN ids to clip ids. Pre-cut clip files under clips/ are left untouched.

Usage: uv run python tools/migrate_year.py [--dry-run] [--undo] [--thumbs]
Every move is logged in library/migration-log.json; --undo moves the VODs back. --thumbs replaces the year set's
224 px thumbnails with 480 px ones from the source (resumable: skips thumbnails already at full width).
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipscout import elgato  # noqa: E402
from clipscout import library as lib  # noqa: E402
from clipscout.plan import PICK_KEYS, music_flags, source_url  # noqa: E402

OLD = Path(r'M:\Work\TwitchVOD')
YEAR = OLD / '_tooling' / 'year'
SET = OLD / 'clips' / '2025-09 to 2026-09 Twitch year'
VODS = OLD / 'vods'
LOG = lib.LIBRARY / 'migration-log.json'
BENCH = lib.ELGATO / 'benchmark'
NOTE = 'migrated from the 2025-09 to 2026-09 year set'
SPANISH = {'id': 'v2717966435', 'title': '[ES] Wave Next En Espanol', 'duration': None,
           'local': '2026-03-09 [ES] Wave Next En Espanol [v2717966435].mp4', 'language': 'es'}


def read(path, default=None):
    return lib.read_json(path, default)


def vod_file(v):
    if v.get('local') and (VODS / v['local']).exists():
        return VODS / v['local']
    hits = list(VODS.glob(f"*[[]{v['id']}[]].mp4"))
    return hits[0] if hits else None


def probe_duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True).stdout.strip()
    return round(float(out), 3) if out else None


def existing_stream(sid):
    try:
        return lib.get_stream(sid)
    except KeyError:
        return None


def load_log():
    return read(LOG, {'moves': []})


def log_move(src, dst):
    log = load_log()
    log['moves'].append({'from': str(src), 'to': str(dst), 'at': lib.now()})
    lib.write_json(LOG, log)


def convert_clips(stream, entries, index_by_file, judged, music):
    """Year index entries -> (clips.json, judge.json, music.json, {year file: clip id})."""
    entries = sorted(entries, key=lambda e: (e['hook_at'], e['source_out']))
    taken, ids = set(), {}
    for e in entries:
        ids[e['file']] = lib.clip_id(e['hook_at'], taken)
        taken.add(ids[e['file']])
    clips, judge, music_out = [], {}, {}
    for e in entries:
        cid = ids[e['file']]
        ci = index_by_file.get(e['file'], {})
        k = e['source_in']
        clip = {'id': cid, 'key': f'{stream.id}/{cid}'}
        clip.update({f: e[f] for f in PICK_KEYS if f in e})
        clip.update({'flags': list(e.get('flags', [])), 'hook_at': e['hook_at'], 'source_out': e['source_out'],
                     'duration': round(e['source_out'] - e['hook_at'], 2), 'key_in': k,
                     'preroll_s': round(e['hook_at'] - k, 2), 'preroll_words': e.get('preroll_words', ''),
                     'topic': elgato.topic(e.get('product', '')), 'source_url': source_url(stream, k),
                     'year_file': e['file']})
        for f in ('parked', 'dup_size', 'dup_best', 'rank'):
            if f in ci:
                clip[f] = ci[f]
        if ci.get('dup_group'):
            g = ci['dup_group']
            clip['dup_group'] = f'{stream.id}/{ids[g]}' if g in ids else g
        if e['file'] in music:
            m = music[e['file']]
            music_out[cid] = {'share': m['share'], 'peak': m['peak']}
            music_flags(clip, m)
        j = judged.get(e['file'])
        if j:
            merge = [ids[f] for f in j.get('merge') or [] if f in ids] or None
            judge[cid] = {'side': j.get('side'), 'bin': j.get('bin'), 'stars': j.get('stars'),
                          'reason': j.get('reason'), 'dupe_of': ids.get(j.get('dupe_of')) if j.get('dupe_of') else None,
                          'merge': merge, 'post': j.get('post')}
            clip['judge'] = judge[cid]
        clips.append(clip)
    return clips, judge, music_out, ids


def plan(manifest):
    """Every stream to migrate: (manifest entry, VOD path or None when already moved)."""
    return [(v, vod_file(v)) for v in manifest + [SPANISH]]


def migrate_data(v, src, index_by_file, judged, dry):
    vid = v['id']
    sid = lib.stream_id('twitch', vid)
    stream = existing_stream(sid)
    if stream:
        date = stream.date
    elif src:
        date = src.name[:10]
    else:
        raise RuntimeError(f'{vid}: no VOD file and no stream folder')
    entries = read(YEAR / 'index' / f'{vid}.json', [])
    thumbs_found = sum((SET / '_thumbs' / e['file']).with_suffix('.jpg').exists() for e in entries)
    judged_n = sum(e['file'] in judged for e in entries)
    info = {'sid': sid, 'date': date, 'clips': len(entries), 'judged': judged_n, 'thumbs': thumbs_found,
            'bytes': src.stat().st_size if src else 0, 'title': v['title']}
    if dry:
        return info, None
    spanish = v.get('language') == 'es'
    if not stream:
        stream = lib.create_stream(sid, v['title'], date,
                                   {'kind': 'twitch', 'url': f'https://www.twitch.tv/videos/{vid[1:]}', 'id': vid[1:]},
                                   media='source.mp4',
                                   duration=v.get('duration') or (probe_duration(src) if src else None))
    if spanish:
        stream.update(lambda m: m.update(language='es'))
    folder = stream.folder
    if not spanish:
        t = read(YEAR / 'transcripts' / f'{vid}.json')
        t['model'] = 'faster-whisper large-v3-turbo'
        lib.write_json(folder / 'transcript.json', t, indent=None)
        for name, target in (('sentences', 'sentences.txt'), ('corrections', 'corrections.json'),
                             ('picks', 'picks.json'), ('keyframes', 'keyframes.json')):
            ext = '.txt' if name == 'sentences' else '.json'
            if (YEAR / name / f'{vid}{ext}').exists():
                shutil.copy2(YEAR / name / f'{vid}{ext}', folder / target)
        music = read(YEAR / 'music' / f'{vid}.json', {})
        clips, judge, music_out, ids = convert_clips(stream, entries, index_by_file, judged, music)
        stream.save('clips.json', clips)
        stream.save('judge.json', judge)
        stream.save('music.json', music_out)
        (folder / 'thumbs').mkdir(exist_ok=True)
        for e in entries:
            thumb = (SET / '_thumbs' / e['file']).with_suffix('.jpg')
            if thumb.exists():
                shutil.copy2(thumb, folder / 'thumbs' / f"{ids[e['file']]}.jpg")
    else:
        ids = {}

    def stages(meta):
        meta['stages'] = {'fetch': {'state': 'done', 'at': lib.now(), 'note': NOTE}}
        for name in lib.STAGES[1:]:
            meta['stages'][name] = ({'state': 'skipped', 'at': lib.now(),
                                     'note': 'Spanish stream: Clip Scout picks English only'} if spanish
                                    else {'state': 'done', 'at': lib.now(), 'note': NOTE})
    stream.update(stages)
    return info, ids


def move(src, dst):
    """Rename src to dst; False when the file is open elsewhere (Windows sharing violation)."""
    try:
        src.rename(dst)
    except PermissionError:
        return False
    log_move(src, dst)
    return True


def benchmark(file_to_key):
    matches = read(YEAR / 'judge' / 'calibration-matches.json', [])
    split = read(YEAR / 'judge' / 'split.json', {})
    approved = []
    for r in matches:
        approved.append({
            'approved': r['file'], 'duration': r.get('duration'), 'stream': lib.stream_id('twitch', r['vod']),
            'date': r.get('date'), 'span': r.get('span'), 'match': r.get('match'),
            'candidates': [{'key': file_to_key.get(y['file']), 'cover': y['cover'], 'purity': y['purity']}
                           for y in r.get('year') or []]})
    out = {half: [{'approved': a['approved'], 'key': file_to_key.get(a['clip'])} for a in split.get(half, [])]
           for half in ('anchor', 'test')}
    missing = [a for half in out.values() for a in half if not a['key']]
    BENCH.mkdir(parents=True, exist_ok=True)
    lib.write_json(BENCH / 'approved.json', approved)
    lib.write_json(BENCH / 'split.json', out)
    return len(approved), {h: len(v) for h, v in out.items()}, missing


def undo():
    log = load_log()
    n = 0
    for m in reversed(log['moves']):
        if m.get('undone'):
            continue
        src, dst = Path(m['from']), Path(m['to'])
        if dst.exists() and not src.exists():
            dst.rename(src)
            m['undone'] = lib.now()
            n += 1
    lib.write_json(LOG, log)
    print(f'{n} VODs moved back')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--undo' in sys.argv:
        return undo()
    if '--thumbs' in sys.argv:
        from clipscout.plan import thumbnails
        for s in lib.all_streams():
            if s.clips():
                made, failed = thumbnails(s, s.clips(), workers=4)
                print(f'{s.id}: {made} thumbnails made, {failed} failed', flush=True)
        return
    dry = '--dry-run' in sys.argv
    manifest = read(YEAR / 'manifest.json')
    index = read(SET / 'clip-index.json')
    index_by_file = {c['file']: c for c in index}
    judged = read(YEAR / 'judge' / 'judged.json', {})
    todo = plan(manifest)
    totals = {'streams': 0, 'clips': 0, 'judged': 0, 'thumbs': 0, 'bytes': 0, 'no_vod': []}
    file_to_key, pending = {}, []
    for v, src in todo:
        info, ids = migrate_data(v, src, index_by_file, judged, dry)
        totals['streams'] += 1
        for k in ('clips', 'judged', 'thumbs', 'bytes'):
            totals[k] += info[k]
        if not src:
            totals['no_vod'].append(info['sid'])
        for f, cid in (ids or {}).items():
            file_to_key[f] = f"{info['sid']}/{cid}"
        print(f"{'plan' if dry else 'done'} {info['sid']:14} {info['date']} {info['clips']:4} clips "
              f"{info['judged']:4} judged {info['thumbs']:4} thumbs {info['bytes'] / 2**30:6.2f} GB  {info['title'][:50]}")
        if not dry and src:
            dst = lib.get_stream(info['sid']).folder / 'source.mp4'
            if not dst.exists() and not move(src, dst):
                pending.append((src, dst))
    for attempt in range(3):
        if not pending:
            break
        print(f'{len(pending)} VODs busy; retrying in 20 s')
        time.sleep(20)
        pending = [(s, d) for s, d in pending if not move(s, d)]
    print(f"\n{totals['streams']} streams, {totals['clips']} clips ({len(index)} in clip-index), "
          f"{totals['judged']} judged ({len(judged)} in judged.json), {totals['thumbs']} thumbnails, "
          f"{totals['bytes'] / 2**30:.1f} GB of VODs to move")
    if totals['no_vod']:
        print('already moved or missing VOD:', ', '.join(totals['no_vod']))
    if dry:
        return
    n, halves, missing = benchmark(file_to_key)
    print(f'benchmark: {n} approved clips, split {halves}, {len(missing)} unmapped')
    lib.write_json(lib.LIBRARY / 'decisions.json',
                   read(lib.LIBRARY / 'decisions.json') or
                   {'version': 3, 'decisions': {}, 'seen': {}, 'merges': [], 'posts': {}})
    old = read(SET / 'decisions.json', {})
    if old:
        print(f'NOTE: {SET / "decisions.json"} has {len(old)} entries; they were not converted')
    if pending:
        print('never moved (open elsewhere):', *[str(s) for s, _ in pending], sep='\n  ')


if __name__ == '__main__':
    main()
