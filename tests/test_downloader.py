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
    with pytest.raises(DownloadError) as exc:
        validate_video_file(dummy)
    assert "ffprobe" not in exc.value.message          # the page shows this message: no tool names


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


def test_ssrf_rejects_cgnat():
    with pytest.raises(DownloadError, match="Security violation"):
        validate_url_security("http://100.64.0.1/video.mp4")


@pytest.mark.anyio
async def test_stream_download_size_limit_with_content_length(tmp_path):
    from app.downloader import stream_download_to_file
    import httpx

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            headers={"Content-Length": str(3 * 1024 * 1024 * 1024)},
            content=b"",
        )

    transport = httpx.MockTransport(handler)
    target = tmp_path / "out.mp4"

    with pytest.raises(DownloadError) as exc:
        await stream_download_to_file(
            "https://example.com/big.mp4",
            target,
            max_bytes=2 * 1024 * 1024 * 1024,
            transport=transport,
        )
    assert exc.value.status_code == 413
    assert "exceeds limit" in exc.value.message


@pytest.mark.anyio
async def test_stream_download_size_limit_without_content_length(tmp_path):
    from app.downloader import stream_download_to_file
    import httpx

    async def stream_chunks():
        yield b"A" * 1500
        yield b"B" * 1500

    def handler(request: httpx.Request):
        # Stream chunks without Content-Length
        return httpx.Response(200, content=stream_chunks())

    transport = httpx.MockTransport(handler)
    target = tmp_path / "stream_big.mp4"

    with pytest.raises(DownloadError) as exc:
        await stream_download_to_file(
            "https://example.com/stream.mp4",
            target,
            max_bytes=2000,
            transport=transport,
        )
    assert exc.value.status_code == 413
    assert "File size exceeded maximum limit" in exc.value.message
    assert not target.exists()


@pytest.mark.anyio
async def test_stream_download_rejects_redirect_to_private_ip(tmp_path):
    from app.downloader import stream_download_to_file
    import httpx

    def handler(request: httpx.Request):
        return httpx.Response(302, headers={"Location": "http://192.168.1.100/internal.mp4"})

    transport = httpx.MockTransport(handler)
    target = tmp_path / "redirect.mp4"

    with pytest.raises(DownloadError) as exc:
        await stream_download_to_file(
            "https://example.com/redir.mp4",
            target,
            transport=transport,
        )
    assert "Security violation" in exc.value.message
    assert not target.exists()


@pytest.mark.anyio
async def test_stream_download_404_and_403(tmp_path):
    from app.downloader import stream_download_to_file
    import httpx

    def handler_404(request: httpx.Request):
        return httpx.Response(404, text="Not Found")

    transport_404 = httpx.MockTransport(handler_404)
    target = tmp_path / "notfound.mp4"

    with pytest.raises(DownloadError) as exc_404:
        await stream_download_to_file("https://example.com/404.mp4", target, transport=transport_404)
    assert "404 Not Found" in exc_404.value.message

    def handler_403(request: httpx.Request):
        return httpx.Response(403, text="Forbidden")

    transport_403 = httpx.MockTransport(handler_403)
    with pytest.raises(DownloadError) as exc_403:
        await stream_download_to_file("https://example.com/403.mp4", target, transport=transport_403)
    assert "403 Forbidden" in exc_403.value.message


@pytest.mark.anyio
async def test_stream_download_overall_timeout(tmp_path):
    import asyncio
    from app.downloader import stream_download_to_file
    import httpx

    async def slow_stream():
        yield b"chunk1"
        await asyncio.sleep(0.1)
        yield b"chunk2"

    def handler(request: httpx.Request):
        return httpx.Response(200, content=slow_stream())

    transport = httpx.MockTransport(handler)
    target = tmp_path / "timeout.mp4"

    with pytest.raises(DownloadError) as exc:
        await stream_download_to_file(
            "https://example.com/slow.mp4",
            target,
            timeout=0.03,  # Deadline expires before stream finishes
            transport=transport,
        )
    assert exc.value.status_code == 504
    assert "Download timed out" in exc.value.message
    assert not target.exists()


@pytest.mark.anyio
async def test_stream_download_gdrive_large_file_form_confirmation(tmp_path, monkeypatch):
    from app import downloader
    import httpx

    file_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
    form_html = f"""
    <html>
      <form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
        <input type="hidden" name="id" value="{file_id}">
        <input type="hidden" name="export" value="download">
        <input type="hidden" name="confirm" value="t">
        <input type="hidden" name="uuid" value="fake-uuid-12345">
      </form>
    </html>
    """

    # Mock video validation so dummy content is accepted
    monkeypatch.setattr(downloader, "validate_video_file", lambda p: None)

    requests_seen = []

    def handler(request: httpx.Request):
        requests_seen.append(str(request.url))
        if "drive.google.com" in str(request.url):
            return httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, text=form_html)
        elif "drive.usercontent.google.com" in str(request.url):
            # Assert confirm and uuid were forwarded in query
            assert "confirm=t" in str(request.url)
            assert "fake-uuid-12345" in str(request.url)
            return httpx.Response(200, headers={"Content-Type": "video/mp4"}, content=b"VIDEO_PAYLOAD_OK")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    target = tmp_path / "gdrive_large.mp4"

    bytes_written = await downloader.stream_download_to_file(
        f"https://drive.google.com/file/d/{file_id}/view?usp=sharing",
        target,
        transport=transport,
    )

    assert bytes_written == len(b"VIDEO_PAYLOAD_OK")
    assert target.read_bytes() == b"VIDEO_PAYLOAD_OK"
    assert len(requests_seen) == 2


@pytest.mark.anyio
async def test_stream_download_reports_progress(tmp_path, monkeypatch):
    """The upload page shows each link's download: bytes so far, the size from Content-Length, then the check."""
    import threading
    from app import downloader
    import httpx

    check_threads = []
    monkeypatch.setattr(downloader, "validate_video_file", lambda p: check_threads.append(threading.get_ident()))
    seen = []

    payload = b"V" * (300 * 1024)                       # 3 pieces of 128 KB (the last one shorter)
    sized = httpx.MockTransport(lambda request: httpx.Response(200, headers={"Content-Type": "video/mp4"},
                                                               content=payload))
    await downloader.stream_download_to_file("https://example.com/cam.mp4", tmp_path / "cam.mp4",
                                             progress_callback=lambda *a: seen.append(a), transport=sized)
    assert seen[0] == ("downloading", 0, len(payload))
    done = [d for stage, d, _ in seen if stage == "downloading"]
    assert len(done) >= 4 and done == sorted(done) and done[-1] == len(payload)
    assert seen[-1] == ("checking", len(payload), len(payload))
    assert check_threads and check_threads[0] != threading.get_ident()   # ffprobe does not block the server

    async def chunks():                                 # no Content-Length: bytes only, no total
        yield b"A" * 1000
        yield b"B" * 1000

    seen.clear()
    unsized = httpx.MockTransport(lambda request: httpx.Response(200, content=chunks()))
    await downloader.stream_download_to_file("https://example.com/cam2.mp4", tmp_path / "cam2.mp4",
                                             progress_callback=lambda *a: seen.append(a), transport=unsized)
    assert all(total is None for _, _, total in seen)
    assert seen[-1] == ("checking", 2000, None)


@pytest.mark.anyio
async def test_gdrive_folder_404_does_not_mutate_id():
    from app.downloader import parse_gdrive_folder_items, DownloadError
    import httpx

    requested_urls = []

    def handler(request: httpx.Request):
        requested_urls.append(str(request.url))
        return httpx.Response(404, text="Folder not found")

    transport = httpx.MockTransport(handler)
    folder_url = "https://drive.google.com/drive/folders/1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6pj"

    with pytest.raises(DownloadError) as exc:
        await parse_gdrive_folder_items(folder_url, transport=transport)

    assert "404 (Not Found)" in exc.value.message
    # Ensure no request altered 'j' to 'i'
    for u in requested_urls:
        assert not u.endswith("pi")

