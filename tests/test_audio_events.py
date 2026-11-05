import pytest

from ai_director.audio import events


def test_ensure_panns_files_replaces_incomplete_checkpoint(tmp_path, monkeypatch):
    checkpoint = "Cnn14_mAP=0.431.pth"
    monkeypatch.setattr(events, "PANNS_DIR", tmp_path)
    monkeypatch.setattr(events, "PANNS_FILES", {checkpoint: "https://example.test/model"})
    monkeypatch.setattr(events, "PANNS_MIN_SIZE", {checkpoint: 8})
    (tmp_path / checkpoint).write_bytes(b"partial")

    def download(url, target):
        target.write_bytes(b"complete")

    monkeypatch.setattr(events.urllib.request, "urlretrieve", download)
    events.ensure_panns_files()

    assert (tmp_path / checkpoint).read_bytes() == b"complete"
    assert not (tmp_path / f"{checkpoint}.download").exists()


def test_ensure_panns_files_rejects_incomplete_download(tmp_path, monkeypatch):
    checkpoint = "Cnn14_mAP=0.431.pth"
    monkeypatch.setattr(events, "PANNS_DIR", tmp_path)
    monkeypatch.setattr(events, "PANNS_FILES", {checkpoint: "https://example.test/model"})
    monkeypatch.setattr(events, "PANNS_MIN_SIZE", {checkpoint: 8})

    def download(url, target):
        target.write_bytes(b"short")

    monkeypatch.setattr(events.urllib.request, "urlretrieve", download)
    with pytest.raises(RuntimeError, match="Incomplete PANNs download"):
        events.ensure_panns_files()

    assert not (tmp_path / checkpoint).exists()
    assert not (tmp_path / f"{checkpoint}.download").exists()
