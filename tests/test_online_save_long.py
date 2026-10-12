"""Numeric JSON keys must not make long or negative-lane games unreadable."""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from src.data.archive import GameArchive
from src.data.online_save import OnlineSaveStore


SAVE_ID = 'd' * 32


def long_engine():
    path = Path(__file__).parent / 'fixtures/hard20_eight_required_rewind_state.json.gz'
    return GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))


def test_encoding_survives_json_key_conversion():
    payload = {'lanes': {2: {}, 10: {}, -1: {}, -2: {}}, 'times': {2: 'a', 10: 'b'}}
    assert OnlineSaveStore._encode(payload) == OnlineSaveStore._encode(
        json.loads(json.dumps(payload)))


@pytest.mark.parametrize('legacy', [False, True])
def test_long_checkpoint_load_catalog_and_integrity(tmp_path, legacy):
    store = OnlineSaveStore(tmp_path)
    engine = long_engine()
    path = tmp_path / f'{SAVE_ID}.json'
    if legacy:
        # Reproduce the released writer exactly, independently of the fix.
        payload = {'version': 1, 'save_id': SAVE_ID, 'saved_at': '2026-10-12T00:00:00Z',
                   'game': GameArchive.capture(engine)}
        encode = lambda data: json.dumps(data, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':')).encode('utf-8')
        path.write_bytes(encode({'payload': payload, 'sha256': hashlib.sha256(encode(payload)).hexdigest()}))
    else:
        store.save(SAVE_ID, engine)
    before = path.read_bytes()
    restored, summary = store.load(SAVE_ID)
    assert summary['move_counter'] == 122
    assert len(restored.timeline_manager.timelines) == 9
    assert GameArchive.capture(restored) == GameArchive.capture(engine)
    assert store.catalog() == {'saves': [summary], 'unreadable': 0}
    assert path.read_bytes() == before
    tampered = json.loads(before)
    tampered['payload']['game']['current_turn_color'] = 'black'
    path.write_text(json.dumps(tampered, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='invalid checkpoint'):
        store.load(SAVE_ID)
    assert store.catalog() == {'saves': [], 'unreadable': 1}
