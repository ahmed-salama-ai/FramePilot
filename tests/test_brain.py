# tests/test_brain.py — AI Brain without a GPU and without a real model (a fake model answers)
import json
import shutil
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, TypeAdapter

from ai_director.brain.modes import read_rows, smooth_modes
from ai_director.common import schemas as S
from ai_director.common.io import read_jsonl
from ai_director.common.paths import MOCK


def row(t, mode, event="talking"):
    return {"t": t, "scene": "two people talk", "event": event, "energy": 0.4, "mode": mode, "highlight": False}


def test_smooth_modes(tmp_path):
    rows = [row(0.0, "conversation"), row(5.0, "wide_energy"),                  # one noisy answer: no change
            row(10.0, "conversation"), row(15.0, "demo"), row(20.0, "demo"),   # twice in a row: switch
            row(25.0, "conversation", event="laughter")]                       # laughter: reaction at once
    text = "".join(json.dumps(r) + "\n" for r in reversed(rows)) + '{"t": 30.0, "sce'   # + a broken last line
    (tmp_path / "scene.partial.jsonl").write_text(text, encoding="utf-8")
    smooth_modes(tmp_path)
    out = read_jsonl(tmp_path / "scene.jsonl")
    assert [r["mode"] for r in out] == ["conversation", "conversation", "conversation", "conversation", "demo",
                                        "reaction"]
    assert [r["raw_mode"] for r in out][:2] == ["conversation", "wide_energy"]   # what the model really said
    TypeAdapter(list[S.SceneLine]).validate_python(out)                         # follows the contract


def test_read_rows_skips_a_broken_line(tmp_path):
    p = tmp_path / "scene.partial.jsonl"
    p.write_text(json.dumps(row(0.0, "demo")) + "\n{broken", encoding="utf-8")
    assert [r["t"] for r in read_rows(p)] == [0.0]


def test_grid_has_all_cameras(tmp_path):
    cv2 = pytest.importorskip("cv2")
    from ai_director.brain.grid import grid_at
    caps = {c: cv2.VideoCapture(str(MOCK / f"video/cam{c}_640.mp4")) for c in (1, 2, 3)}
    img = cv2.imread(grid_at(caps, 12.0, tmp_path / "grid.jpg"))
    assert img.shape == (378, 672, 3)                                           # 2 x 2 tiles of 336 x 189
    assert img[200:, 350:].max() < 10                                           # the 4th tile is black (3 cameras;
                                                                                # its edge may get JPEG noise)


class Answer(BaseModel):                                                        # a tiny schema for the client test
    mode: str
    energy: float


def test_chat_json_arguments_and_retry(monkeypatch):
    ollama = pytest.importorskip("ollama")
    from ai_director.brain import llm_client
    calls, answers = [], ["not json", '{"mode": "demo", "energy": 0.5}']

    def fake_chat(**kw):
        calls.append(kw)
        return SimpleNamespace(message=SimpleNamespace(content=answers[len(calls) - 1]))
    monkeypatch.setattr(ollama, "chat", fake_chat)
    a = llm_client.chat_json("qwen3-vl:4b", "hi", Answer, images=["a.jpg"], think=False)
    assert a.mode == "demo" and len(calls) == 2                                 # bad JSON -> asked once more
    assert calls[0]["keep_alive"] == "2m" and calls[0]["think"] is False        # real arguments, not options
    assert calls[0]["options"] == {"temperature": 0.2}
    assert calls[0]["messages"][0]["images"] == ["a.jpg"]
    calls.clear()
    answers[:] = ['{"mode": "demo", "energy": 0.5}']
    llm_client.chat_json("moondream", "hi", Answer)                             # think=None -> not sent at all
    assert "think" not in calls[0]


def test_said_uses_the_english_translation():
    pytest.importorskip("ollama")
    pytest.importorskip("cv2")
    from ai_director.brain.scene import said
    tr = [{"start": 1.0, "text": "أهلا بيكم", "translation": "Welcome"},
          {"start": 4.0, "text": "شكرا", "translation": ""}]                     # no translation -> the Arabic
    assert said(tr, 5.0, english=True, window=10) == "Welcome شكرا"
    assert said(tr, 5.0, english=False, window=10) == "أهلا بيكم شكرا"
    assert said(tr, 30.0, english=True, window=10) == "(silence)"


def test_run_with_a_fake_model(tmp_path, monkeypatch):
    pytest.importorskip("ollama")
    pytest.importorskip("cv2")
    import ai_director.brain.scene as scene
    s = tmp_path / "s00"
    shutil.copytree(MOCK, s)                                                    # never write into the mock
    (s / "scene.jsonl").unlink()
    prompts = []

    def fake_chat_json(model, prompt, schema, images=None, think=None):
        prompts.append(prompt)
        if len(prompts) == 3:
            schema.model_validate({})                                           # raises ValidationError
        return schema(**{k: v for k, v in row(0.0, "conversation").items() if k != "t"})
    monkeypatch.setattr(scene, "chat_json", fake_chat_json)
    monkeypatch.setattr(scene, "unload", lambda model: None)
    scene.run(s)
    out = read_jsonl(s / "scene.jsonl")
    assert [r["t"] for r in out] == [5.0 * k for k in range(12)]                # 60 s, one line every 5 s
    assert out[2]["scene"] == "unknown"                                         # bad answer -> neutral line
    assert "Welcome to a new episode" in prompts[1]                             # English text (mock = Arabic)
    TypeAdapter(list[S.SceneLine]).validate_python(out)
    (s / "scene.jsonl").unlink()
    scene.run(s)                                                                # resume: nothing to ask again
    assert len(prompts) == 12 and (s / "scene.jsonl").exists()
