import json
import os
from datetime import datetime
import shutil
import sys
import tempfile
import types
from pathlib import Path
import pytest

# The web app keeps its data in a temp folder during the tests: the real data/ (app.db, s01-s03) is never touched.
TEST_DATA = Path(tempfile.mkdtemp(prefix="framepilot_web_"))
os.environ["FRAMEPILOT_DATA"] = str(TEST_DATA)

from fastapi.testclient import TestClient

_TEMP = tempfile.gettempdir()
from app.main import app                     # noqa: E402  (the server keeps upload temp files in data/tmp_uploads ...)
from app import db, worker                   # noqa: E402
tempfile.tempdir = _TEMP                     # ... the other tests keep the normal temp folder

SESSIONS = db.SESSIONS_DIR


@pytest.fixture(scope="module")
def client():
    assert db.DATA == TEST_DATA
    db.init()
    with TestClient(app) as c:
        yield c
    shutil.rmtree(TEST_DATA, ignore_errors=True)


def make_session(sid, program=True, name="Imported test"):
    """A session folder made outside the app (like s01-s03)."""
    folder = SESSIONS / sid
    (folder / "raw").mkdir(parents=True)
    for i in (1, 2, 3):
        (folder / "raw" / f"cam{i}.mp4").write_bytes(b"x")
    (folder / "upload.json").write_text(json.dumps({"name": name, "language": "ar", "wide_cam": 1}), encoding="utf-8")
    if program:
        (folder / "program.mp4").write_bytes(b"x")
        (folder / "logs").mkdir()
        (folder / "logs" / "times.json").write_text(json.dumps({"Ingest + Sync": 12.5}), encoding="utf-8")
    return folder


def test_home_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "FramePilot" in res.text or "فريم بايلوت" in res.text

def test_new_project_page(client):
    res = client.get("/new")
    assert res.status_code == 200
    assert "upload" in res.text.lower() or "رفع" in res.text

def test_session_s00_results_page(client):
    res = client.get("/results/s00")
    assert res.status_code == 200
    assert "Timeline" in res.text or "المخطط" in res.text
    assert "cdn.jsdelivr" not in res.text                      # the chart library is served locally
    assert client.get("/static/vendor/chart.umd.min.js").status_code == 200

def test_api_session_data(client):
    res = client.get("/api/sessions/s00")
    assert res.status_code == 200
    data = res.json()
    assert "project" in data
    assert "timeline" in data
    assert "speakers" in data
    assert "highlights" in data
    assert data["timeline"] is not None
    assert data["speaker_map"]                                  # for the speaker chips' camera colour
    assert [v["id"] for v in data["versions"]] == ["v1"] and data["versions"][0]["has_program"]


def test_job_page_and_status_for_mock_project(client):
    job = db.get_latest_job("s00")
    assert job is not None
    assert client.get(f"/jobs/{job['id']}").status_code == 200
    res = client.get(f"/api/jobs/{job['id']}")
    assert res.status_code == 200
    assert res.json()["session_id"] == "s00"


def test_session_video_supports_range_requests(client):
    res = client.get(
        "/files/s00/program.mp4",
        headers={"Range": "bytes=0-31"},
    )
    assert res.status_code == 206
    assert len(res.content) == 32
    assert res.headers["content-range"].startswith("bytes 0-31/")


def test_transcript_download(client):
    res = client.get("/api/sessions/s00/transcript.txt")
    assert res.status_code == 200
    assert "FramePilot - Session Transcript" in res.text
    assert "Host (host):" in res.text                           # names from speakers.json, not SPEAKER_00

def test_label_page(client):
    res = client.get("/label/s00")
    assert res.status_code == 200
    assert "Labelling" in res.text or "تدريب" in res.text

def test_save_labels_endpoint(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.check_sid", lambda sid: tmp_path)
    payload = {
        "changes": [[0.0, 1], [3.5, 2], [7.0, 3]],
        "highlights": [[2.0, 5.0, "key_debate"], [6.0, 8.0, "laugh, then a joke"]],
        "duration": 10.0
    }
    res = client.post("/api/labels/s00", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["saved"] == 100  # 10.0 * 10 rows

    labels_csv = tmp_path / "labels.csv"
    assert labels_csv.exists()
    content = labels_csv.read_text(encoding="utf-8").splitlines()
    assert content[0] == "t,cam"
    assert len(content) == 101
    assert content[36] == "3.5,2"
    rows = (tmp_path / "highlight_labels.csv").read_text(encoding="utf-8").splitlines()
    assert rows[2] == '6.0,8.0,"laugh, then a joke"'            # a comma in the reason is quoted


def test_patch_speakers(client, monkeypatch, tmp_path):
    """Names typed on the results page -> speakers.json with name_source "user" (= name cards); upload.json is not
    changed (its speaker_names would also put the name in front of every caption line)."""
    monkeypatch.setattr("app.main.check_sid", lambda sid: tmp_path)
    upload_file = tmp_path / "upload.json"
    upload_text = json.dumps({"name": "x", "language": "ar", "wide_cam": 1, "speaker_names": {}})
    upload_file.write_text(upload_text, encoding="utf-8")
    speakers_file = tmp_path / "speakers.json"
    speakers_file.write_text(
        json.dumps([
            {"speaker": "SPEAKER_00", "name": "Speaker 0"},
            {"speaker": "SPEAKER_01", "name": "Speaker 1", "name_source": "user"},
            {"speaker": "SPEAKER_02", "name": ""},
        ]),
        encoding="utf-8",
    )
    payload = {
        "speakers": {
            "SPEAKER_00": "Dr.   Ahmed",
            "SPEAKER_01": "",                    # emptied: the name and its card are removed
            "SPEAKER_02": "SPEAKER_02",          # not renamed: never saved as a name
            "SPEAKER_07": "Nobody",              # not in speakers.json
        }
    }
    res = client.patch("/api/sessions/s00/speakers", json=payload)
    assert res.status_code == 200
    assert res.json()["saved"] == 2
    assert upload_file.read_text(encoding="utf-8") == upload_text
    got = json.loads(speakers_file.read_text(encoding="utf-8"))
    assert [(x["name"], x.get("name_source")) for x in got] == [("Dr. Ahmed", "user"), ("", ""), ("", None)]


def test_agent_chat_endpoint(client, monkeypatch):
    monkeypatch.setattr("app.main.db.gpu_busy", lambda: False)
    monkeypatch.setattr("app.main.db.get_messages", lambda sid: [])
    monkeypatch.setattr("app.main.db.add_message", lambda *args, **kwargs: None)
    agent_module = types.ModuleType("ai_director.agent.agent")
    agent_module.chat = lambda session_dir, message, history: {
        "reply": "Created from the real agent",
        "steps": [],
        "clips": []
    }
    monkeypatch.setitem(sys.modules, "ai_director.agent.agent", agent_module)
    payload = {"message": "اعمل ريل دقيقة على الضيف"}
    res = client.post("/api/agent/s00", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data
    assert "steps" in data
    assert "clips" in data


def test_agent_clips_are_kept_in_the_chat_history(client, monkeypatch):
    monkeypatch.setattr("app.main.db.gpu_busy", lambda: False)
    clip = {"id": "c9", "start": 10.0, "end": 90.0, "format": "9:16", "file": "clips/c9.mp4", "captions": "en"}
    agent_module = types.ModuleType("ai_director.agent.agent")
    agent_module.chat = lambda session_dir, message, history: {"reply": "Done", "steps": [], "clips": [clip]}
    monkeypatch.setitem(sys.modules, "ai_director.agent.agent", agent_module)
    assert client.post("/api/agent/s00", json={"message": "a reel"}).status_code == 200
    last = client.get("/api/agent/s00/messages").json()[-1]
    assert last["role"] == "assistant" and last["clips"] == [clip]


def test_agent_failure_does_not_claim_clip_was_created(client, monkeypatch):
    monkeypatch.setattr("app.main.db.gpu_busy", lambda: False)
    monkeypatch.setattr("app.main.db.get_messages", lambda sid: [])
    monkeypatch.setattr("app.main.db.add_message", lambda *args, **kwargs: None)
    agent_module = types.ModuleType("ai_director.agent.agent")

    def unavailable(*args, **kwargs):
        raise RuntimeError("Ollama is offline")

    agent_module.chat = unavailable
    monkeypatch.setitem(sys.modules, "ai_director.agent.agent", agent_module)
    res = client.post("/api/agent/s00", json={"message": "Make a clip"})
    assert res.status_code == 503
    assert "No clip was created" in res.json()["detail"]


@pytest.mark.parametrize("form", [
    {"consent": "false"},
    {"wide_cam": "4"},
    {"language": "fr"},
])
def test_upload_rejects_invalid_project_options(client, form):
    data = {"name": "Test project", "consent": "true", **form}
    files = [
        ("files", ("cam1.mp4", b"video", "video/mp4")),
        ("files", ("cam2.mp4", b"video", "video/mp4")),
    ]
    res = client.post("/api/projects", data=data, files=files)
    assert res.status_code == 400


def test_upload_is_staged_and_writes_contract(client):
    files = [
        ("files", ("client-name.mov", b"camera one", "video/quicktime")),
        ("files", ("another-name.mp4", b"camera two", "video/mp4")),
    ]
    res = client.post(
        "/api/projects",
        data={"name": "Upload test", "language": "en", "wide_cam": "2", "consent": "true"},
        files=files,
    )
    assert res.status_code == 200
    payload = res.json()
    session_dir = SESSIONS / payload["session_id"]
    upload = json.loads((session_dir / "upload.json").read_text(encoding="utf-8"))
    assert upload == {
        "name": "Upload test",
        "language": "en",
        "wide_cam": 2,
        "num_speakers": None,
        "speaker_names": {},
        "people": [],
    }
    assert (session_dir / "raw" / "cam1.mp4").read_bytes() == b"camera one"
    assert (session_dir / "raw" / "cam2.mp4").read_bytes() == b"camera two"
    assert client.delete(f"/api/projects/{payload['session_id']}").status_code == 200
    assert not session_dir.exists()
    trashed = list(db.TRASH_DIR.glob(f"{payload['session_id']}_*"))     # moved to data/trash, not erased
    assert len(trashed) == 1 and (trashed[0] / "raw" / "cam1.mp4").read_bytes() == b"camera one"


def test_upload_size_failure_leaves_no_partial_session(client, monkeypatch):
    sid = db.new_session_id()
    monkeypatch.setattr("app.main.MAX_VIDEO_BYTES", 4)
    monkeypatch.setattr(db, "new_session_id", lambda: sid)
    files = [
        ("files", ("cam1.mp4", b"video", "video/mp4")),
        ("files", ("cam2.mp4", b"video", "video/mp4")),
    ]
    res = client.post(
        "/api/projects",
        data={"name": "Oversize test", "consent": "true"},
        files=files,
    )
    assert res.status_code == 413
    assert not (SESSIONS / sid).exists()
    assert not (SESSIONS / f".{sid}.uploading").exists()


def test_retry_only_accepts_failed_jobs(client):
    sid = db.new_session_id()
    job_id = db.create_job(sid)
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409
    db.update_job(job_id, status="error", error="test failure")
    res = client.post(f"/api/jobs/{job_id}/retry")
    assert res.status_code == 200
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409
    with db.conn() as connection:
        connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


def test_security_check_sid(client):
    res = client.get("/results/../etc/passwd")
    assert res.status_code in [400, 404]

    res2 = client.get("/results/invalid_id")
    assert res2.status_code in [400, 404]


def test_sessions_made_outside_the_app_are_listed_and_protected(client):
    make_session("s51", program=True, name="Podcast run by hand")
    make_session("s52", program=False, name="Not run yet")
    db.import_sessions()
    page = client.get("/").text
    assert "Podcast run by hand" in page and "Not run yet" in page
    assert db.get_project("s51")["source"] == "imported"
    assert db.get_latest_job("s51")["report"] == [["Ingest + Sync", "done", 12.5]]
    assert db.get_latest_job("s52") is None                     # shown as "not processed"
    res = client.delete("/api/projects/s51")
    assert res.status_code == 403
    assert (SESSIONS / "s51" / "program.mp4").exists()          # never deleted by the app
    assert "deleteThisProject" not in client.get("/results/s51").text


def run_with_pipeline(monkeypatch, fake_run):
    """Run one queued job through the worker with a stand-in for ai_director.pipeline."""
    sid = db.new_session_id()
    (SESSIONS / sid / "raw").mkdir(parents=True)
    db.create_project(sid, "worker test")
    job_id = db.create_job(sid)
    module = types.ModuleType("ai_director.pipeline")
    module.run_pipeline = fake_run
    monkeypatch.setitem(sys.modules, "ai_director.pipeline", module)
    monkeypatch.delenv("FAKE_PIPELINE", raising=False)
    job = db.next_job()
    assert job["id"] == job_id
    worker.process_job(job)
    return sid, db.get_job(job_id)


def test_worker_failure_mentioning_cuda_stays_failed(client, monkeypatch):
    def failing(session_dir, on_progress):
        raise RuntimeError("Perception failed after 12 s (full output: logs/3_perception.log):\nUsing CUDA device 0\nValueError")
    sid, job = run_with_pipeline(monkeypatch, failing)
    assert job["status"] == "error"                             # was "done" with a simulated report before
    assert job["error"].startswith("Perception failed")
    assert "Using CUDA" in (SESSIONS / sid / "logs" / "error.log").read_text(encoding="utf-8")


def test_worker_success_saves_the_report(client, monkeypatch):
    def ok(session_dir, on_progress):
        on_progress("Ingest + Sync", 0)
        return [("Ingest + Sync", "done", 3.0), ("AI Brain", "FAILED (optional, see 4_ai.log)", 1.0)]
    sid, job = run_with_pipeline(monkeypatch, ok)
    assert job["status"] == "done"
    assert job["report"] == [["Ingest + Sync", "done", 3.0], ["AI Brain", "FAILED (optional, see 4_ai.log)", 1.0]]


def test_worker_start_resets_a_job_cut_off_while_running(client):
    sid = db.new_session_id()
    job_id = db.create_job(sid)
    db.update_job(job_id, status="running", stage="Perception")
    assert db.gpu_busy()                                        # the agent would answer "GPU busy" forever
    assert db.reset_running_jobs() >= 1
    job = db.get_job(job_id)
    assert job["status"] == "error" and job["stage"] == "Perception"
    assert not db.gpu_busy()
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 200
    with db.conn() as connection:
        connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))




def tiny_png():
    import subprocess
    out = TEST_DATA / "logo_src.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=32x32:d=0.1", "-frames:v",
                    "1", out], check=True)
    return out.read_bytes()


def test_upload_with_people_and_brand(client):
    files = [("files", ("cam1.mp4", b"camera one", "video/mp4")), ("files", ("cam2.mp4", b"camera two", "video/mp4")),
             ("logo", ("logo.png", tiny_png(), "image/png"))]
    people = [{"name": "  Mona   Adel ", "role": "host"}, {"name": "Islam", "role": "guest"}, {"name": "", "role": ""}]
    brand = {"logo_corner": "bottom-left", "captions": {"text_color": "#FFE066", "box": False}}
    res = client.post("/api/projects", files=files, data={
        "name": "Brand test", "consent": "true", "people_json": json.dumps(people), "brand_json": json.dumps(brand)})
    assert res.status_code == 200, res.text
    session_dir = SESSIONS / res.json()["session_id"]
    upload = json.loads((session_dir / "upload.json").read_text(encoding="utf-8"))
    assert upload["people"] == [{"name": "Mona Adel", "role": "host"}, {"name": "Islam", "role": "guest"}]
    assert upload["num_speakers"] == 2                                     # from the people typed
    b = json.loads((session_dir / "brand.json").read_text(encoding="utf-8"))
    assert b["logo"] == "brand/logo.png" and (session_dir / "brand/logo.png").exists()
    assert b["logo_corner"] == "bottom-left" and b["captions"]["text_color"] == "#FFE066" and not b["captions"]["box"]
    assert client.delete(f"/api/projects/{res.json()['session_id']}").status_code == 200


@pytest.mark.parametrize("extra, problem", [
    ({"people_json": json.dumps([{"name": "X", "role": "boss"}])}, "role"),
    ({"brand_json": json.dumps({"captions": {"text_color": "orange"}})}, "colour"),
])
def test_upload_rejects_bad_people_or_brand(client, extra, problem):
    files = [("files", ("cam1.mp4", b"a", "video/mp4")), ("files", ("cam2.mp4", b"b", "video/mp4"))]
    before = sorted(p.name for p in SESSIONS.iterdir())
    res = client.post("/api/projects", files=files, data={"name": "Bad", "consent": "true", **extra})
    assert res.status_code == 400 and problem in res.text
    assert sorted(p.name for p in SESSIONS.iterdir()) == before           # nothing left behind


def test_brand_logo_must_be_a_picture(client):
    res = client.post("/api/sessions/s00/brand", data={"settings": "{}"},
                      files=[("logo", ("logo.png", b"not a picture", "image/png"))])
    assert res.status_code == 400 and "picture" in res.text
    assert not (SESSIONS / "s00/brand/logo.png").exists()


def test_versions_api(client):
    s = SESSIONS / "s00"
    v2 = s / "versions/v2"
    v2.mkdir(parents=True)
    for name in ("cuts.json", "program_nocaps.mp4", "program.mp4"):
        shutil.copy(s / name, v2 / name)
    (s / "versions.json").write_text(json.dumps([
        {"id": "v1", "made_by": "pipeline", "note": "the AI edit", "created": "", "cuts": "cuts.json",
         "nocaps": "program_nocaps.mp4", "program": "program.mp4"},
        {"id": "v2", "made_by": "agent", "note": "show Guest more", "created": "2026-10-12T10:00:00",
         "cuts": "versions/v2/cuts.json", "nocaps": "versions/v2/program_nocaps.mp4",
         "program": "versions/v2/program.mp4"}]), encoding="utf-8")
    assert [v["id"] for v in client.get("/api/sessions/s00").json()["versions"]] == ["v1", "v2"]
    zipped = client.get("/api/sessions/s00/export/v2")
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"
    assert client.delete("/api/sessions/s00/versions/v1").status_code == 400
    res = client.delete("/api/sessions/s00/versions/v2")
    assert res.status_code == 200 and [v["id"] for v in res.json()["versions"]] == ["v1"]
    assert not v2.exists() and list(db.TRASH_DIR.glob("s00_v2_*"))       # moved to data/trash


def test_update_video_job(client):
    """"Update video": a 'finish' job; the worker makes a NEW version (here with a name card), with and without
    captions; the original v1 is not touched."""
    s = SESSIONS / "s00"
    sp = json.loads((s / "speakers.json").read_text(encoding="utf-8"))
    sp[0].update(name="Mona", name_source="user")
    (s / "speakers.json").write_text(json.dumps(sp, ensure_ascii=False), encoding="utf-8")
    before = (s / "program.mp4").stat().st_mtime
    res = client.post("/api/sessions/s00/update", json={"version": "latest"})
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    assert client.post("/api/sessions/s00/update", json={"version": "v1"}).status_code == 409   # one at a time
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "finish" and job["stages"][0].startswith("Captions") and job["eta_seconds"] > 0
    worker.process_job(db.next_job())
    job = db.get_job(job_id)
    assert job["status"] == "done", job["error"]
    assert job["report"][0][1] == "done: v2 (1 name cards)"
    assert (s / "program.mp4").stat().st_mtime == before                    # the original is kept
    versions = client.get("/api/sessions/s00").json()["versions"]
    assert [v["id"] for v in versions] == ["v1", "v2"]
    v2 = versions[1]
    assert v2["made_by"] == "update" and v2["has_program"] and v2["has_clean"] and v2["cuts"] == "cuts.json"
    assert client.post("/api/sessions/s00/update", json={"version": "v9"}).status_code == 400


def test_publish_job(client, monkeypatch):
    import ai_director.highlights.article as article
    import ai_director.highlights.publish as publish
    monkeypatch.setattr(publish, "make_publish", lambda s: {"chapters": [1, 2, 3], "posts": [1]})
    monkeypatch.setattr(article, "make_article", lambda s: {"article_ar": "مقال قصير", "article_en": "A short one"})
    res = client.post("/api/sessions/s00/publish")
    assert res.status_code == 200
    worker.process_job(db.next_job())
    job = db.get_job(res.json()["job_id"])
    assert job["status"] == "done" and job["report"][0][1] == "done (3 chapters, 1 posts)"
    assert job["report"][1][1] == "done (2 + 3 words)"

def test_caption_editor_api(client):
    assert client.get("/captions/s00").status_code == 200
    data = client.get("/api/sessions/s00/transcript").json()
    row = data["rows"][3]
    assert data["language"] == "ar" and data["saves"] == 0 and not data["has_original"]
    res = client.patch("/api/sessions/s00/transcript", json={"rows": [{"id": row["id"], "text": "كلام متعدل"}]})
    assert res.status_code == 200 and res.json() == {"saved": 1, "saves": 1}
    assert "كلام متعدل" in (SESSIONS / "s00/captions.vtt").read_text(encoding="utf-8")
    assert client.post("/api/sessions/s00/transcript/undo").status_code == 200
    assert client.get("/api/sessions/s00/transcript").json()["rows"][3]["text"] == row["text"]
    assert client.post("/api/sessions/s00/transcript/undo").status_code == 400          # nothing left to undo
    assert client.post("/api/sessions/s00/transcript/restore").status_code == 200


def test_time_estimate(client):
    from app import eta
    sid = db.new_session_id()
    (SESSIONS / sid / "raw").mkdir(parents=True)
    db.create_project(sid, "eta test", duration=600.0)
    job_id = db.create_job(sid)
    queued = client.get(f"/api/jobs/{job_id}").json()
    r = eta.rates()
    assert queued["eta_seconds"] == queued["eta_total"] == round(600 * sum(r.values()))   # ~1.9 s of work per s
    assert 1000 < queued["eta_seconds"] < 1300
    db.update_job(job_id, status="running", stage="Render", stage_started_at=datetime.now().isoformat())
    running = client.get(f"/api/jobs/{job_id}").json()
    assert abs(running["eta_seconds"] - 600 * (r["Render"] + r["Highlights"] + r["Evaluation"])) < 3
    db.update_job(job_id, status="error")
    assert "eta_seconds" not in client.get(f"/api/jobs/{job_id}").json()



def test_session_data_has_stats_and_languages(client):
    data = client.get("/api/sessions/s00").json()
    assert {p["speaker"] for p in data["stats"]["people"]} == {"SPEAKER_00", "SPEAKER_01"}
    v1 = data["versions"][0]
    assert v1["languages"]["en"] == {"file": "program_en.mp4", "ready": False} and v1["descriptions"] is None
    assert "searchForm" in client.get("/results/s00").text and "downloadLang" in client.get("/results/s00").text


def test_video_with_english_captions_only(client):
    s = SESSIONS / "s00"
    assert client.post("/api/sessions/s00/language", json={"version": "v1", "langs": "fr"}).status_code == 400
    res = client.post("/api/sessions/s00/language", json={"version": "v1", "langs": "en"})
    assert res.status_code == 200 and res.json()["ready"] is False
    job = client.get(f"/api/jobs/{res.json()['job_id']}").json()
    assert job["kind"] == "language" and job["eta_seconds"] > 0
    worker.process_job(db.next_job())
    assert db.get_job(job["id"])["status"] == "done"
    assert (s / "program_en.mp4").exists() and not (s / "program_en_making.mp4").exists()
    again = client.post("/api/sessions/s00/language", json={"version": "v1", "langs": "en"}).json()
    assert again == {"ready": True, "file": "program_en.mp4"}
    assert client.get("/api/sessions/s00").json()["versions"][0]["languages"]["en"]["ready"]


def test_captions_timed_for_the_version(client):
    s = SESSIONS / "s00"
    plain = client.get("/api/sessions/s00/captions/v1?lang=ar").text
    assert plain.startswith("1\n") and client.get("/api/sessions/s00/captions/v1?lang=xx").status_code == 400
    from ai_director.director.versions import add_version, list_versions
    old = list_versions(s)
    add_version(s, {**old[0], "intro": 2.0})
    shifted = client.get("/api/sessions/s00/captions/v1?lang=ar").text
    first = lambda t: t.splitlines()[1].split(" --> ")[0]                       # noqa: E731
    sec = lambda x: int(x[:2]) * 3600 + int(x[3:5]) * 60 + float(x[6:].replace(",", "."))      # noqa: E731
    assert abs(sec(first(shifted)) - sec(first(plain)) - 2.0) < 0.002
    vtt = client.get("/api/sessions/s00/captions/v1?lang=ar%2Ben&fmt=vtt").text
    assert vtt.startswith("WEBVTT")
    add_version(s, old[0])                                                      # back as it was


def test_why_and_search_endpoints(client):
    why = client.get("/api/sessions/s00/why/v1").json()
    cuts = json.loads((SESSIONS / "s00/cuts.json").read_text(encoding="utf-8"))
    assert len(why) == len(cuts) and why[0]["code"] == "wide_open" and why[0]["ar"]
    assert client.get("/api/sessions/s00/why/v9").status_code == 400
    rows = json.loads((SESSIONS / "s00/transcript.json").read_text(encoding="utf-8"))
    res = client.get("/api/sessions/s00/search", params={"q": rows[2]["text"].split()[0]}).json()
    assert res["mode"] == "words" and res["results"]
    assert client.get("/api/sessions/s00/search", params={"q": "  "}).status_code == 400
    assert client.get("/api/sessions/s00/search", params={"q": "x", "mode": "magic"}).status_code == 400


def test_podcast_and_article_downloads(client):
    res = client.get("/api/sessions/s00/podcast/v1")
    assert res.status_code == 200 and res.headers["content-type"] == "audio/mpeg" and len(res.content) > 10000
    p = SESSIONS / "s00/publish.json"
    old = p.read_text(encoding="utf-8") if p.exists() else None
    p.write_text(json.dumps({"article_en": "# Title"}), encoding="utf-8")
    assert client.get("/api/sessions/s00/article.md?lang=en").text == "# Title"
    assert client.get("/api/sessions/s00/article.md?lang=ar").status_code == 404
    if old is None:
        p.unlink()
    else:
        p.write_text(old, encoding="utf-8")


def test_trailer_and_thumbnail_jobs(client, monkeypatch):
    import ai_director.director.thumbnail as thumbnail
    import ai_director.highlights.trailer as trailer
    monkeypatch.setattr(trailer, "default_ask", lambda prompt: trailer.Answer(
        moments=[trailer._Moment(first=1, last=1), trailer._Moment(first=6, last=6)], title_ar="حلقة", title_en="Show"))
    monkeypatch.setattr(thumbnail.Faces, "__init__", lambda self: setattr(self, "ok", False))
    res = client.post("/api/sessions/s00/trailer")
    assert res.status_code == 200
    assert client.post("/api/sessions/s00/thumbnails").status_code == 409             # one job at a time
    worker.process_job(db.next_job())
    assert db.get_job(res.json()["job_id"])["status"] == "done"
    res = client.post("/api/sessions/s00/thumbnails")
    assert res.status_code == 200
    worker.process_job(db.next_job())
    job = db.get_job(res.json()["job_id"])
    assert job["status"] == "done", job["error"]
    data = client.get("/api/sessions/s00").json()
    assert data["trailer"]["title_en"] == "Show" and (SESSIONS / "s00" / data["trailer"]["files"]["9:16"]).exists()
    assert data["thumbnails"] and (SESSIONS / "s00" / data["thumbnails"][0]["files"]["ar"]).exists()


def test_brand_clean_voice_and_music(client):
    import subprocess
    music = TEST_DATA / "music_src.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=2", music], check=True)
    res = client.post("/api/sessions/s00/brand", data={"settings": json.dumps({"clean_voice": True})},
                      files=[("music", ("song.mp3", music.read_bytes(), "audio/mpeg"))])
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["clean_voice"] is True and b["music"] == "brand/music.mp3"
    bad = client.post("/api/sessions/s00/brand", data={"settings": "{}"},
                      files=[("music", ("song.mp3", b"not sound", "audio/mpeg"))])
    assert bad.status_code == 400 and "music" in bad.text
    res = client.post("/api/sessions/s00/brand", data={"settings": json.dumps({"clean_voice": False}),
                                                       "remove": "music"})
    assert res.json()["music"] is None and not res.json()["clean_voice"]

