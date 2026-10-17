# tests/test_pipeline.py — pipeline.py with small FAKE stages (fast, no AI models)
import json
import shutil

import pytest

import ai_director.pipeline as pl
from ai_director.common.paths import MOCK

FAKE_STAGES = {   # module name -> its code (each one gets the session folder as sys.argv[1])
    "write_a": "print('stage A: سلام ✓')\nopen(SESSION + '/a.json', 'w').write('{}')",
    "write_b": "open(SESSION + '/b.json', 'w').write('{}')",
    "crash":   "print('something went wrong here')\nraise SystemExit(1)",
    "lazy":    "print('I forgot my done file')",
}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A package 'fakestages' with the fake stages, visible to this process AND to the stage processes."""
    pkg = tmp_path / "code" / "fakestages"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    for name, body in FAKE_STAGES.items():
        (pkg / f"{name}.py").write_text("import sys\nSESSION = sys.argv[1]\n" + body + "\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "code"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "code"))
    session = tmp_path / "s99"
    session.mkdir()
    return session


def use(monkeypatch, *stages):
    monkeypatch.setattr(pl, "STAGES", list(stages))


def test_runs_in_order_then_skips_everything(fake, monkeypatch):
    use(monkeypatch, ("A", "fakestages.write_a", "a.json", True), ("B", "fakestages.write_b", "b.json", True))
    seen = []
    report = pl.run_pipeline(fake, lambda stage, pct: seen.append((stage, pct)))
    assert seen == [("A", 0), ("B", 50), ("Done", 100)]
    assert [(n, s) for n, s, _ in report] == [("A", "done"), ("B", "done")]
    assert "سلام ✓" in (fake / "logs" / "1_a.log").read_text(encoding="utf-8")       # Arabic + ✓ survive
    again = pl.run_pipeline(fake, lambda *a: None)
    assert [s for _, s, _ in again] == ["already done", "already done"]                # second run: nothing to do
    assert len((fake / "logs" / "pipeline.log").read_text(encoding="utf-8").splitlines()) == 2
    assert set(json.loads((fake / "logs" / "times.json").read_text(encoding="utf-8"))) == {"A", "B"}   # for eval.run


def test_continues_where_it_stopped(fake, monkeypatch):
    use(monkeypatch, ("A", "fakestages.write_a", "a.json", True), ("B", "fakestages.write_b", "b.json", True))
    (fake / "a.json").write_text("{}")                                                 # A finished last time
    assert [s for _, s, _ in pl.run_pipeline(fake, lambda *a: None)] == ["already done", "done"]


def test_a_failing_stage_stops_the_pipeline(fake, monkeypatch):
    use(monkeypatch, ("Bad", "fakestages.crash", "x.json", True), ("B", "fakestages.write_b", "b.json", True))
    with pytest.raises(RuntimeError, match="something went wrong here"):                # the log's end is shown
        pl.run_pipeline(fake, lambda *a: None)
    assert not (fake / "b.json").exists()                                              # B never ran


def test_a_stage_must_write_its_done_file(fake, monkeypatch):
    use(monkeypatch, ("Lazy", "fakestages.lazy", "x.json", True))
    with pytest.raises(RuntimeError, match="without writing x.json"):
        pl.run_pipeline(fake, lambda *a: None)


def test_a_failing_optional_stage_is_only_a_warning(fake, monkeypatch):
    use(monkeypatch, ("Brain", "fakestages.crash", "x.json", False), ("B", "fakestages.write_b", "b.json", True))
    report = pl.run_pipeline(fake, lambda *a: None)
    assert [s for _, s, _ in report] == ["FAILED (optional, see 1_brain.log)", "done"]   # B still ran


def test_missing_modules(fake, monkeypatch):
    use(monkeypatch, ("Later", "fakestages.not_built", "z.json", False), ("B", "fakestages.write_b", "b.json", True))
    assert [s for _, s, _ in pl.run_pipeline(fake, lambda *a: None)] == ["skipped (not built yet)", "done"]
    use(monkeypatch, ("Needed", "nopackage.run", "z.json", True))
    with pytest.raises(RuntimeError, match="not in the repo"):
        pl.run_pipeline(fake, lambda *a: None)


def test_the_real_stage_list_on_the_mock(tmp_path):
    s = tmp_path / "s00"
    shutil.copytree(MOCK, s)                       # a copy: never write into samples/mock_s00
    assert [n for n, *_ in pl.STAGES] == ["Ingest + Sync", "Audio + Captions", "Perception", "AI Brain",
                                          "Switching", "Render", "Highlights", "Evaluation"]
    report = pl.run_pipeline(s, lambda *a: None)   # the mock has every done file -> nothing runs
    assert {st for _, st, _ in report} == {"already done"}
