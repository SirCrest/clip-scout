import struct

from clipscout import media


def box(typ, payload=b''):
    return struct.pack('>I4s', 8 + len(payload), typ) + payload


def test_same_sound_catches_a_shifted_timeline():
    import numpy as np
    rng = np.random.default_rng(1)
    a = rng.normal(0, 3000, 64000).astype(np.float32)
    assert media.same_sound(a, a.copy()) == (True, 0.0)
    nudged = a + rng.normal(0, 20, a.size).astype(np.float32)  # decoder rounding: same timeline
    ok, diff = media.same_sound(a, nudged)
    assert ok and diff < 0.02
    shifted = np.concatenate([np.zeros(100, np.float32), a[:-100]])  # 6 ms later
    assert media.same_sound(a, shifted)[0] is False


def test_fragmented_mp4_is_detected(tmp_path):
    frag = tmp_path / 'frag.mp4'
    frag.write_bytes(box(b'ftyp', b'isom') + box(b'moov', b'x' * 20) + box(b'emsg') + box(b'moof', b'y') + box(b'mdat', b'z' * 50))
    plain = tmp_path / 'plain.mp4'
    plain.write_bytes(box(b'ftyp', b'isom') + box(b'moov', b'x' * 200) + box(b'mdat', b'z' * 500))
    assert media.is_fragmented(frag)
    assert not media.is_fragmented(plain)
    assert not media.is_fragmented(tmp_path / 'missing.mp4')
