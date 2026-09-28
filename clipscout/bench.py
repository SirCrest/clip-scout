"""`scout bench`: score the judge against clips Elgato staff approved for posting.

elgato/benchmark/approved.json lists the 97 staff-approved clips with the library clips that cover them;
split.json halves the ones matched to a single clip into `anchor` (shown to the judge as [APPROVED EXAMPLE]) and
`test` (held out). A good judge puts the test half in `top` and never parks an approved clip as `off` or `dupe`;
long approved deep dives that no single clip covers should be covered by one of its merge suggestions.
"""
import collections

from . import library as lib

BENCH = lib.ELGATO / 'benchmark'


def judged_results():
    """{clip key: judge result} and {clip key: clip} across the library."""
    judged, clips = {}, {}
    for s in lib.all_streams():
        for cid, j in (s.load('judge.json') or {}).items():
            judged[f'{s.id}/{cid}'] = j
        for c in s.clips():
            clips[c['key']] = c
    return judged, clips


def score(judged, clips, split, approved):
    """The numbers `run` prints, as a dict (also used by tests and model comparisons)."""
    out = {'judged': len(judged), 'clips': len(clips)}
    for half in ('anchor', 'test'):
        bins = collections.Counter(judged.get(a['key'], {}).get('bin', 'missing') for a in split[half])
        out[half] = {'n': len(split[half]), 'bins': dict(bins), 'top': bins.get('top', 0)}
    everyone = split['anchor'] + split['test']
    out['parked_approved'] = [a for a in everyone if judged.get(a['key'], {}).get('bin') in ('off', 'dupe')]
    out['test_misses'] = [(a, judged.get(a['key'], {})) for a in split['test']
                          if judged.get(a['key'], {}).get('bin') != 'top']
    runs = []
    for key, j in judged.items():
        if j.get('merge'):
            sid = key.split('/')[0]
            members = [clips.get(f'{sid}/{m}') for m in j['merge']]
            if all(members):
                runs.append((sid, min(c['hook_at'] for c in members), max(c['source_out'] for c in members)))
    out['merges'] = len(runs)
    long_ = [r for r in approved if (r.get('match') or 0) >= 0.3
             and not (r['candidates'] and r['candidates'][0]['cover'] >= 0.5)]
    covered = []
    for r in long_:
        lo, hi = r['span']
        best = max((max(0, min(hi, b) - max(lo, a)) / (hi - lo) for sid, a, b in runs if sid == r['stream']),
                   default=0)
        covered.append((r, best))
    out['long'] = covered
    out['long_recovered'] = sum(best >= 0.7 for _, best in covered)
    return out


def run(verbose=False):
    split = lib.read_json(BENCH / 'split.json')
    approved = lib.read_json(BENCH / 'approved.json', [])
    if not split:
        print(f'No benchmark in {BENCH}.')
        return
    judged, clips = judged_results()
    r = score(judged, clips, split, approved)
    print(f"{r['judged']} of {r['clips']} clips judged")
    sides = collections.Counter((j.get('side'), j.get('bin')) for j in judged.values())
    for side in ('staff', 'community'):
        n = sum(v for (s, _), v in sides.items() if s == side)
        print(f'  {side:9} {n:5}: ' + ', '.join(f'{b} {sides[(side, b)]}' for b in ('top', 'effort', 'off', 'dupe')))
    t, a = r['test'], r['anchor']
    print(f"held-out approved clips in top: {t['top']} of {t['n']}   (anchor half: {a['top']} of {a['n']})")
    print(f"approved clips parked as off/dupe: {len(r['parked_approved'])}")
    print(f"long approved deep dives covered by a merge (>=70%): {r['long_recovered']} of {len(r['long'])}"
          f"   ({r['merges']} merge suggestions)")
    for m, j in r['test_misses']:
        print(f"  test miss: {m['approved'][:58]:58} -> {j.get('bin')} {j.get('stars')}* {j.get('reason')}")
    for m in r['parked_approved']:
        print(f"  parked approved: {m['approved'][:58]:58} -> {judged[m['key']].get('bin')}")
    if verbose:
        for m, best in r['long']:
            print(f"  long approved {m['duration']:5.0f}s {m['approved'][:55]:55} merge cover {best:.2f}")
        per = collections.defaultdict(lambda: [0, 0, 0])
        for key, j in judged.items():
            sid = key.split('/')[0]
            per[sid][0] += 1
            per[sid][1] += j.get('bin') == 'top'
        for m in approved:
            if (m.get('match') or 0) >= 0.3:
                per[m['stream']][2] += 1
        print('reviewed streams: clips / top / approved')
        titles = {s.id: s.title for s in lib.all_streams()}
        for sid, (n, top, ap) in sorted(per.items(), key=lambda x: -x[1][2]):
            if ap:
                print(f'  {n:4} / {top:3} / {ap:3}  {titles.get(sid, sid)[:60]}')
    return r
