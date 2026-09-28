import struct

from clipscout import media


def box(typ, payload=b''):
    return struct.pack('>I4s', 8 + len(payload), typ) + payload


def test_fragmented_mp4_is_detected(tmp_path):
    frag = tmp_path / 'frag.mp4'
    frag.write_bytes(box(b'ftyp', b'isom') + box(b'moov', b'x' * 20) + box(b'emsg') + box(b'moof', b'y') + box(b'mdat', b'z' * 50))
    plain = tmp_path / 'plain.mp4'
    plain.write_bytes(box(b'ftyp', b'isom') + box(b'moov', b'x' * 200) + box(b'mdat', b'z' * 500))
    assert media.is_fragmented(frag)
    assert not media.is_fragmented(plain)
    assert not media.is_fragmented(tmp_path / 'missing.mp4')
