import json

import pytest
import src.verify as verify_mod
from src.verify import verify_clip, verify_clips


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def generate_content(self, model, contents):
        self.calls.append((model, contents))
        return FakeResponse(self._text)


class FakeClient:
    def __init__(self, text):
        self.models = FakeModels(text)


def _stub_client(monkeypatch, text, video_bytes=b"fake mp4 bytes", tmp_path=None):
    fake = FakeClient(text)
    monkeypatch.setattr(verify_mod, "_client", lambda: fake)
    path = (tmp_path or pytest.importorskip("pathlib").Path(".")) / "clip.mp4"
    path.write_bytes(video_bytes)
    return fake, str(path)


def test_verify_clip_parses_json_verdict(monkeypatch, tmp_path):
    text = '{"is_rally": true, "confidence": 0.9, "reason": "sustained rally"}'
    fake, path = _stub_client(monkeypatch, text, tmp_path=tmp_path)

    verdict = verify_clip(path)

    assert verdict == {"is_rally": True, "confidence": 0.9, "reason": "sustained rally"}
    assert len(fake.models.calls) == 1
    model, contents = fake.models.calls[0]
    assert model == verify_mod.DEFAULT_MODEL
    assert len(contents) == 2  # video part + prompt


def test_verify_clip_rejects_non_json_response(monkeypatch, tmp_path):
    fake, path = _stub_client(monkeypatch, "not json", tmp_path=tmp_path)

    with pytest.raises(json.JSONDecodeError):
        verify_clip(path)


def test_verify_clips_verifies_each_path_in_order(monkeypatch, tmp_path):
    text = '{"is_rally": false, "confidence": 0.6, "reason": "warmup"}'
    fake, path1 = _stub_client(monkeypatch, text, tmp_path=tmp_path)
    path2 = tmp_path / "clip2.mp4"
    path2.write_bytes(b"more fake bytes")

    results = verify_clips([path1, str(path2)])

    assert set(results) == {path1, str(path2)}
    assert all(v["is_rally"] is False for v in results.values())
    assert len(fake.models.calls) == 2


def test_verify_clip_raises_without_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake")

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        verify_clip(str(path))
