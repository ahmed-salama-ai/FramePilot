import pytest
from pathlib import Path
from app.downloader import (
    validate_url_security,
    extract_gdrive_file_id,
    extract_gdrive_folder_id,
    is_google_drive_url,
    DownloadError,
)


def test_ssrf_rejects_localhost():
    with pytest.raises(DownloadError, match="localhost"):
        validate_url_security("http://localhost/video.mp4")

    with pytest.raises(DownloadError, match="localhost"):
        validate_url_security("http://127.0.0.1:8000/video.mp4")

    with pytest.raises(DownloadError, match="localhost"):
        validate_url_security("http://[::1]:8000/video.mp4")


def test_ssrf_rejects_private_ips():
    with pytest.raises(DownloadError, match="Security violation"):
        validate_url_security("http://192.168.1.1/video.mp4")

    with pytest.raises(DownloadError, match="Security violation"):
        validate_url_security("http://10.0.0.5/video.mp4")

    with pytest.raises(DownloadError, match="Security violation"):
        validate_url_security("http://172.16.0.1/video.mp4")


def test_ssrf_rejects_non_http():
    with pytest.raises(DownloadError, match="Only http:// and https://"):
        validate_url_security("ftp://example.com/video.mp4")

    with pytest.raises(DownloadError, match="Only http:// and https://"):
        validate_url_security("file:///C:/video.mp4")


def test_extract_gdrive_file_id():
    url1 = "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view?usp=sharing"
    assert extract_gdrive_file_id(url1) == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"

    url2 = "https://drive.google.com/open?id=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"
    assert extract_gdrive_file_id(url2) == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"

    url_direct = "https://example.com/test.mp4"
    assert extract_gdrive_file_id(url_direct) is None


def test_extract_gdrive_folder_id():
    folder_url = "https://drive.google.com/drive/folders/1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7"
    assert extract_gdrive_folder_id(folder_url) == "1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7"

    folder_url_u = "https://drive.google.com/drive/u/0/folders/1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7"
    assert extract_gdrive_folder_id(folder_url_u) == "1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7"


def test_is_google_drive_url():
    assert is_google_drive_url("https://drive.google.com/file/d/xyz") is True
    assert is_google_drive_url("https://example.com/video.mp4") is False


def test_validate_video_file_fails_on_dummy(tmp_path):
    from app.downloader import validate_video_file
    dummy = tmp_path / "fake.mp4"
    dummy.write_text("this is not a real video")
    with pytest.raises(DownloadError):
        validate_video_file(dummy)


def test_validate_video_file_succeeds_on_real_video(tmp_path):
    import subprocess
    from app.downloader import validate_video_file
    real_video = tmp_path / "valid.mp4"
    # Create a 1-second real video using ffmpeg
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libx264", str(real_video)
    ], check=True)

    # Should not raise
    validate_video_file(real_video)

