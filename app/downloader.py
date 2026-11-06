import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# Maximum file size: 2 GB (matches MAX_VIDEO_BYTES in main.py)
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_TIMEOUT = 600.0  # 10 minutes max for large video downloads
CONNECT_TIMEOUT = 15.0

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


class DownloadError(Exception):
    """Custom exception for clear user-facing download errors."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_url_security(url: str) -> None:
    """Security check (SSRF protection).
    
    Accepts only http and https. Rejects non-global IPs (private, loopback, link-local,
    reserved, multicast, and CGNAT 100.64.0.0/10).
    """
    if not url or not isinstance(url, str):
        raise DownloadError("The provided URL is empty or invalid.")

    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception:
        raise DownloadError("Invalid URL format.")

    if parsed.scheme not in ("http", "https"):
        raise DownloadError("Only http:// and https:// URLs are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise DownloadError("URL does not contain a valid hostname.")

    lower_host = hostname.lower()
    if lower_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise DownloadError("Security violation: links pointing to localhost are rejected.")

    # Resolve hostname to IP addresses and check for private/internal networks
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise DownloadError(f"Could not resolve host '{hostname}'. Please check the URL.")
    except Exception as e:
        raise DownloadError(f"Security validation failed: {e}")

    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if not ip.is_global:
                raise DownloadError(
                    f"Security violation: link resolves to a non-global or internal IP address ({ip_str})."
                )
        except ValueError:
            pass


def is_google_drive_url(url: str) -> bool:
    """Check if the URL belongs to Google Drive."""
    return "drive.google.com" in url.lower()


def extract_gdrive_file_id(url: str) -> Optional[str]:
    """Extract file ID from various Google Drive file link formats."""
    # Matches /file/d/{id}/...
    m = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]{25,})", url)
    if m:
        return m.group(1)
    # Matches ?id={id} or &id={id}
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        candidate = qs["id"][0]
        if re.match(r"^[a-zA-Z0-9_-]{20,}$", candidate):
            return candidate
    return None


def extract_gdrive_folder_id(url: str) -> Optional[str]:
    """Extract folder ID from Google Drive folder link."""
    m = re.search(r"drive\.google\.com/(?:drive(?:/u/\d+)?/folders/|open\?id=)([a-zA-Z0-9_-]{25,})", url)
    if m:
        return m.group(1)
    return None


async def parse_gdrive_folder_items(
    url: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> List[Dict[str, str]]:
    """Parse public Google Drive folder and list video files inside it."""
    folder_id = extract_gdrive_folder_id(url)
    if not folder_id:
        raise DownloadError("Invalid Google Drive folder URL.")

    validate_url_security(url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    found_files: Dict[str, str] = {}

    # Attempt 1: Fetch Google Drive folder embedded list view
    list_view_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(CONNECT_TIMEOUT, read=25.0),
            follow_redirects=True,
            transport=transport,
        ) as client:
            resp = await client.get(list_view_url, headers=headers)
            if resp.status_code == 200 and "ServiceLogin" not in resp.text:
                # Extract file links and names from table
                file_links = re.findall(
                    r'href="https://drive\.google\.com/file/d/([a-zA-Z0-9_-]{25,})/view"[^>]*>([^<]+)</a>',
                    resp.text,
                    re.IGNORECASE
                )
                for fid, fname in file_links:
                    clean_name = fname.strip()
                    if clean_name.lower().endswith(tuple(VIDEO_EXTENSIONS)) or "video" in clean_name.lower() or "." not in clean_name:
                        found_files[fid] = clean_name
    except Exception:
        pass

    # Attempt 2: Standard folder view
    folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(CONNECT_TIMEOUT, read=30.0),
            follow_redirects=True,
            transport=transport,
        ) as client:
            resp = await client.get(folder_url, headers=headers)
    except Exception as e:
        raise DownloadError(f"Failed to connect to Google Drive: {e}")

    if resp.status_code == 404:
        raise DownloadError(
            "Google Drive folder returned 404 (Not Found). "
            "Please check the folder link or make sure General Access is set to 'Anyone with the link'."
        )
    if "accounts.google.com" in str(resp.url):
        raise DownloadError(
            "This Google Drive folder is Private. "
            "Please open Google Drive, click 'Share' on the folder, and change General Access to 'Anyone with the link'."
        )

    text = resp.text

    # Extract files listed inside Google Drive folder initial data
    # Strategy 1: Normalized JSON unescaping hex (\x22 -> ", \x5b -> [, \x5d -> ])
    normalized = text.replace(r"\x22", '"').replace(r"\x5b", "[").replace(r"\x5d", "]")
    matches = re.findall(
        r'\["([a-zA-Z0-9_-]{25,})",\s*(?:\["[^"]+"\]|\w+|null),\s*"([^"]+\.(?:mp4|mov|mkv|avi|webm))"',
        normalized,
        re.IGNORECASE,
    )
    for fid, fname in matches:
        if fid != folder_id and fid not in found_files:
            found_files[fid] = fname

    # Strategy 2: Direct escaped hex matching
    if not found_files:
        raw_matches = re.findall(
            r'\\x5b\\x22([a-zA-Z0-9_-]{25,})\\x22,[^,]+,\\x22([^"\\]+\.(?:mp4|mov|mkv|avi|webm))\\x22',
            text,
            re.IGNORECASE,
        )
        for fid, fname in raw_matches:
            if fid != folder_id and fid not in found_files:
                found_files[fid] = fname

    # Strategy 3: Standard unescaped fallback
    if not found_files:
        std_matches = re.findall(
            r'\["([a-zA-Z0-9_-]{25,})",\s*"([^"]+\.(?:mp4|mov|mkv|avi|webm))"',
            text,
            re.IGNORECASE,
        )
        for fid, fname in std_matches:
            if fid != folder_id and fid not in found_files:
                found_files[fid] = fname

    if not found_files:
        raise DownloadError(
            "No video files found inside this Google Drive folder, or the folder is not shared publicly ('Anyone with the link')."
        )

    results = []
    for fid, name in found_files.items():
        results.append({
            "id": fid,
            "name": name,
            "url": f"https://drive.google.com/file/d/{fid}/view?usp=sharing",
            "type": "gdrive_file"
        })

    return results


async def inspect_link(url: str) -> Dict[str, any]:
    """Inspect a link to determine if it is a single video or a Google Drive folder."""
    validate_url_security(url)
    
    # Check if Google Drive Folder
    folder_id = extract_gdrive_folder_id(url)
    if folder_id and ("/folders/" in url or "open?id=" in url):
        items = await parse_gdrive_folder_items(url)
        return {
            "type": "folder",
            "folder_id": folder_id,
            "count": len(items),
            "items": items,
        }

    # Check if Google Drive File
    file_id = extract_gdrive_file_id(url)
    if file_id:
        return {
            "type": "file",
            "file_id": file_id,
            "url": url,
            "name": f"Drive_Video_{file_id[:8]}.mp4",
        }

    # Direct URL
    parsed = urlparse(url)
    path_name = Path(parsed.path).name or "direct_video.mp4"
    return {
        "type": "file",
        "url": url,
        "name": path_name,
    }


async def stream_download_to_file(
    url: str,
    target_path: Path,
    max_bytes: int = MAX_VIDEO_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    progress_callback=None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> int:
    """Stream download a video file directly to disk with an overall timeout.
    
    Supports Google Drive file share links and direct HTTP/HTTPS links.
    Handles Google Drive large-file virus-scan confirmation forms (drive.usercontent.google.com).
    Re-validates SSRF on every redirect.
    Enforces a strict overall deadline across all redirects and data streaming.
    """
    validate_url_security(url)

    start_time = time.monotonic()
    deadline = start_time + timeout

    # Resolve direct download URL for Google Drive files
    gdrive_file_id = extract_gdrive_file_id(url)
    if gdrive_file_id:
        download_url = f"https://drive.google.com/uc?export=download&id={gdrive_file_id}"
    else:
        download_url = url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    client_timeout = httpx.Timeout(min(timeout, 60.0), connect=CONNECT_TIMEOUT)
    total_bytes = 0

    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(
            timeout=client_timeout,
            follow_redirects=False,
            headers=headers,
            transport=transport,
        ) as client:
            curr_url = download_url
            redirect_count = 0
            cookies = {}

            while redirect_count < 10:
                if time.monotonic() > deadline:
                    raise DownloadError(
                        f"Download timed out: transfer took longer than {int(timeout)} seconds.",
                        status_code=504
                    )

                validate_url_security(curr_url)
                
                req = client.build_request("GET", curr_url, cookies=cookies)
                resp = await client.send(req, stream=True)

                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if not location:
                        raise DownloadError("Download failed: Redirect response without valid Location header.")
                    
                    for k, v in resp.cookies.items():
                        cookies[k] = v

                    await resp.aclose()
                    curr_url = str(httpx.URL(curr_url).join(location))
                    redirect_count += 1
                    continue

                if resp.status_code == 404:
                    await resp.aclose()
                    raise DownloadError(
                        "The file was not found (404 Not Found). "
                        "If using Google Drive, make sure the file is set to 'Anyone with the link'."
                    )
                if resp.status_code == 403:
                    await resp.aclose()
                    raise DownloadError(
                        "Access forbidden (403 Forbidden). "
                        "Please verify that the file sharing permissions allow anyone with the link to view/download."
                    )
                if resp.status_code >= 400:
                    await resp.aclose()
                    raise DownloadError(f"HTTP request failed with status code {resp.status_code}.")

                content_type = resp.headers.get("Content-Type", "").lower()
                if "text/html" in content_type and gdrive_file_id:
                    html_bytes = await resp.aread()
                    html_text = html_bytes.decode("utf-8", errors="ignore")

                    if "accounts.google.com" in str(resp.url) or "ServiceLogin" in html_text:
                        raise DownloadError(
                            "This Google Drive file is Private. "
                            "Please set the file sharing to 'Anyone with the link' in Google Drive."
                        )

                    next_download_url = None

                    # 1. Drive large file confirmation form (posts/gets to drive.usercontent.google.com/download)
                    form_action_match = re.search(r'<form[^>]+action="([^"]+)"', html_text, re.IGNORECASE)
                    if form_action_match:
                        action_url = form_action_match.group(1).replace("&amp;", "&")
                        inputs = dict(re.findall(
                            r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"',
                            html_text,
                            re.IGNORECASE,
                        ))
                        rev_inputs = dict(re.findall(
                            r'<input[^>]+value="([^"]*)"[^>]+name="([^"]+)"',
                            html_text,
                            re.IGNORECASE,
                        ))
                        for k, v in rev_inputs.items():
                            inputs.setdefault(v, k)

                        action_full = urljoin(str(resp.url), action_url)
                        query_sep = "&" if "?" in action_full else "?"
                        next_download_url = action_full + query_sep + urlencode(inputs)

                    # 2. Check for download link href containing confirm token
                    if not next_download_url:
                        link_match = re.search(r'<a[^>]+href="([^"]*confirm=[^"]*)"', html_text, re.IGNORECASE)
                        if link_match:
                            raw_href = link_match.group(1).replace("&amp;", "&")
                            next_download_url = urljoin(str(resp.url), raw_href)

                    # 3. Check for confirm token in regex or cookies
                    if not next_download_url:
                        confirm_match = re.search(r'confirm=([0-9A-Za-z_-]+)', html_text)
                        confirm_token = confirm_match.group(1) if confirm_match else None
                        if not confirm_token:
                            for c_name, c_val in resp.cookies.items():
                                if c_name.startswith("download_warning"):
                                    confirm_token = c_val
                                    break
                        if confirm_token:
                            next_download_url = f"https://drive.google.com/uc?export=download&confirm={confirm_token}&id={gdrive_file_id}"

                    if next_download_url:
                        curr_url = next_download_url
                        for k, v in resp.cookies.items():
                            cookies[k] = v
                        redirect_count += 1
                        continue
                    else:
                        raise DownloadError(
                            "Could not download file from Google Drive. Ensure the file is shared as 'Anyone with the link'."
                        )

                content_length = resp.headers.get("Content-Length")
                if content_length:
                    try:
                        cl_int = int(content_length)
                        if cl_int > max_bytes:
                            await resp.aclose()
                            raise DownloadError(
                                f"File size exceeds limit ({cl_int // (1024*1024)} MB > {max_bytes // (1024*1024)} MB).",
                                status_code=413
                            )
                    except ValueError:
                        pass

                try:
                    with open(target_path, "wb") as f:
                        aiter = resp.aiter_bytes(chunk_size=128 * 1024).__aiter__()
                        while True:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise DownloadError(
                                    f"Download timed out: transfer took longer than {int(timeout)} seconds.",
                                    status_code=504
                                )
                            try:
                                chunk = await asyncio.wait_for(aiter.__anext__(), timeout=min(remaining, 60.0))
                            except StopAsyncIteration:
                                break
                            except asyncio.TimeoutError:
                                raise DownloadError(
                                    f"Download timed out: transfer took longer than {int(timeout)} seconds.",
                                    status_code=504
                                )

                            if not chunk:
                                continue
                            total_bytes += len(chunk)
                            if total_bytes > max_bytes:
                                raise DownloadError(
                                    f"File size exceeded maximum limit ({max_bytes // (1024*1024)} MB).",
                                    status_code=413
                                )
                            f.write(chunk)
                            if progress_callback:
                                progress_callback(total_bytes)
                finally:
                    await resp.aclose()

                break

        if total_bytes == 0:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise DownloadError("Download failed: The downloaded file is empty.")

        validate_video_file(target_path)
        return total_bytes

    except Exception:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise


def validate_video_file(path: Path) -> None:
    """Validate that the file is a playable video using ffprobe."""
    from ai_director.ingest.probe import probe
    try:
        info = probe(path)
        if not info or info.get("duration", 0) <= 0:
            if path.exists():
                path.unlink(missing_ok=True)
            raise DownloadError("Downloaded file does not contain a valid video stream or duration is 0.")
    except DownloadError:
        raise
    except Exception as e:
        if path.exists():
            path.unlink(missing_ok=True)
        logger.error(f"ffprobe validation failed: {e}")
        raise DownloadError("Downloaded file is not a valid video file (ffprobe could not decode video stream).")
