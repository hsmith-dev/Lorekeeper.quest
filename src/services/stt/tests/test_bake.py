"""The bake's real-audio decode check (bake_models.check_container_decode).

Needs the ffmpeg CLI with libopus/libmp3lame (to encode and decode), so it
runs in the image and skips where ffmpeg is absent (the backend CI interpreter).
"""

from __future__ import annotations

import pytest


def test_real_containers_decode_to_16k_float32():
    import shutil

    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg CLI here")
    import bake_models

    assert bake_models.check_container_decode() == []


def test_check_reports_a_bad_decoder(monkeypatch):
    import numpy as np

    import bake_models

    monkeypatch.setattr(bake_models, "encode_tone", lambda fmt, codec: b"clip")
    results = iter([np.zeros(16000, np.float32), np.zeros(8000, np.float32),
                    np.zeros(16000, np.float64), ValueError("nope"), np.zeros(16000, np.float32)])

    def decoder(data):
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    problems = bake_models.check_container_decode(decoder)
    assert [p.split(":")[0] for p in problems] == ["ogg/libopus", "mp3/libmp3lame", "wav/pcm_s16le"]
