"""'Make one clip': combine consecutive clips of one continuous discussion into a single clip.

The merged clip runs from the first part's hook to the last part's end and is stored in clips.json with
`merged_from`; its parts then sit inside it (the app shows them nested in its card). Editing tightens it like any
other clip.
"""
from . import library as lib


def make_clip(stream, ids):
    with lib.locked(stream.path('clips.json')):
        clips = stream.clips()
        parts = sorted((c for c in clips if c['id'] in set(ids)), key=lambda c: c['hook_at'])
        if len(parts) < 2:
            raise ValueError('pick at least two clips of the same stream to combine')
        part_ids = [p['id'] for p in parts]
        for c in clips:
            if c.get('merged_from') == part_ids:
                return c
        first, last = parts[0], parts[-1]
        cid = lib.clip_id(first['hook_at'], {c['id'] for c in clips})
        judge = {**(first.get('judge') or {}), 'bin': 'top', 'merge': None, 'dupe_of': None,
                 'stars': max((p.get('judge') or {}).get('stars') or 0 for p in parts) or None,
                 'reason': f'One continuous discussion: {len(parts)} clips combined.'}
        merged = {**first, 'id': cid, 'key': f'{stream.id}/{cid}', 'merged_from': part_ids,
                  'last': last.get('last', first.get('last')), 'source_out': last['source_out'],
                  'duration': round(last['source_out'] - first['hook_at'], 2),
                  'flags': sorted({f for p in parts for f in p.get('flags', [])}),
                  'summary': first.get('summary', ''), 'judge': judge}
        clips.append(merged)
        clips.sort(key=lambda c: c['hook_at'])
        stream.save('clips.json', clips)
    return merged
