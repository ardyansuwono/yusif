import os
import sys
import logging
import json
import re
import time
import http.cookiejar
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, PlainTextResponse, JSONResponse
from requests.cookies import RequestsCookieJar
import requests
import streamlink
import uvicorn

# Setup logging agar muncul di dashboard Railway
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("yt-proxy")

app = FastAPI(title="YouTube Live Proxy (Railway)")

# Inisialisasi session streamlink global
session = streamlink.Streamlink()
session.set_option("hls-live-edge", 3)
session.set_option("stream-timeout", 30)

cookie_jar = RequestsCookieJar()
cookie_status_msg = "Belum diinisialisasi"

def load_youtube_cookies():
    global cookie_jar, cookie_status_msg
    cookie_jar = RequestsCookieJar()

    # 1. Cek file cookies.txt
    cookie_candidates = [
        os.path.join(os.path.dirname(__file__), "cookies.txt"),
        os.path.join(os.getcwd(), "cookies.txt"),
        "cookies.txt",
    ]
    cookie_file = None
    for cand in cookie_candidates:
        if os.path.exists(cand):
            cookie_file = cand
            break

    if cookie_file:
        try:
            cj = http.cookiejar.MozillaCookieJar(cookie_file)
            cj.load(ignore_discard=True, ignore_expires=True)
            for c in cj:
                cookie_jar.set_cookie(c)
                session.http.cookies.set_cookie(c)
            cookie_status_msg = f"Berhasil memuat {len(cookie_jar)} cookies dari {os.path.basename(cookie_file)}"
            logger.info(cookie_status_msg)
            return True
        except Exception as e:
            cookie_status_msg = f"Error membaca file {cookie_file}: {e}"
            logger.error(cookie_status_msg)
            return False

    # 2. Cek env var YOUTUBE_COOKIES
    env_cookies = os.environ.get("YOUTUBE_COOKIES")
    if env_cookies:
        try:
            import tempfile
            with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
                tf.write(env_cookies)
                tf_name = tf.name
            try:
                cj = http.cookiejar.MozillaCookieJar(tf_name)
                cj.load(ignore_discard=True, ignore_expires=True)
                for c in cj:
                    cookie_jar.set_cookie(c)
                    session.http.cookies.set_cookie(c)
            finally:
                if os.path.exists(tf_name):
                    os.remove(tf_name)
            cookie_status_msg = f"Berhasil memuat {len(cookie_jar)} cookies dari env YOUTUBE_COOKIES"
            logger.info(cookie_status_msg)
            return True
        except Exception as e:
            cookie_status_msg = f"Error parse env YOUTUBE_COOKIES: {e}"
            logger.error(cookie_status_msg)
            return False

    cookie_status_msg = "Tidak ada cookies (cookies.txt atau YOUTUBE_COOKIES tidak ditemukan)"
    logger.warning(cookie_status_msg)
    return False

# Jalankan load cookies saat file diimpor/start
load_youtube_cookies()

# In-memory cache untuk channel streams (TTL default 60 detik)
channel_cache: Dict[str, tuple[dict, float]] = {}


def get_public_base_url(request: Request) -> str:
    """Mendapatkan base URL publik yang akurat bahkan di belakang reverse proxy Railway"""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}".rstrip("/")


def get_video_title_oembed(video_id: str) -> str:
    """Fallback cepat mengambil judul video YouTube menggunakan oEmbed publik tanpa geoblock"""
    try:
        r = requests.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
            timeout=5
        )
        if r.status_code == 200:
            return r.json().get("title", "")
    except Exception:
        pass
    return ""


def resolve_channel_target(target: str) -> tuple[str, str]:
    """Mengubah handle channel / ID / URL menjadi streams URL YouTube dan target bersih"""
    target = target.strip()
    if target.endswith(".m3u8") or target.endswith(".m3u"):
        target = target.rsplit(".", 1)[0]
    if target.endswith("/streams"):
        target = target[:-8]
    if target.endswith("/"):
        target = target[:-1]

    if target.startswith("http://") or target.startswith("https://"):
        clean_target = target.rstrip("/").split("/")[-1]
        return f"{target}/streams", clean_target
    elif target.startswith("@"):
        return f"https://www.youtube.com/{target}/streams", target
    elif target.startswith("UC") and len(target) == 24:
        return f"https://www.youtube.com/channel/{target}/streams", target
    else:
        return f"https://www.youtube.com/@{target}/streams", f"@{target}"


def extract_channel_streams(channel_target: str, base_url: str = "", use_cache: bool = True, cache_ttl: int = 60) -> dict:
    """
    Ekstrak semua live streams (sedang berlangsung & akan datang / upcoming) dari halaman channel YouTube.
    Mendukung UI modern YouTube (lockupViewModel) dan legacy (videoRenderer),
    serta mendeteksi avatar live ring YouTube.
    """
    url, clean_handle = resolve_channel_target(channel_target)
    cache_key = url.lower()

    if use_cache and cache_key in channel_cache:
        cached_data, expire_at = channel_cache[cache_key]
        if time.time() < expire_at:
            res = json.loads(json.dumps(cached_data))
            res["cached"] = True
            if base_url:
                for cat in ["live", "upcoming", "completed"]:
                    for item in res.get(cat, []):
                        item["proxy_stream"] = f"{base_url}/live/{item['video_id']}"
            return res

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, cookies=cookie_jar if len(cookie_jar) > 0 else None, timeout=12)
    except Exception as e:
        logger.error(f"Error fetching channel page {url}: {e}")
        return {"error": f"Gagal request ke YouTube: {str(e)}", "target": clean_handle, "url": url}

    if resp.status_code != 200:
        logger.warning(f"YouTube status {resp.status_code} for {url}")
        return {"error": f"YouTube merespons HTTP {resp.status_code}", "target": clean_handle, "url": url}

    m = re.search(r"ytInitialData\s*=\s*({.+?});", resp.text)
    if not m:
        logger.warning(f"ytInitialData not found for {url}")
        return {"error": "ytInitialData tidak ditemukan pada halaman", "target": clean_handle, "url": url}

    try:
        data = json.loads(m.group(1))
    except Exception as e:
        logger.error(f"Error parsing JSON YouTube for {url}: {e}")
        return {"error": f"Error parsing JSON YouTube: {str(e)}", "target": clean_handle, "url": url}

    channel_name = None
    meta_channel = data.get("metadata", {}).get("channelMetadataRenderer", {})
    if meta_channel:
        channel_name = meta_channel.get("title")

    avatar_live_id = None
    try:
        avatar_live_id = data["header"]["pageHeaderRenderer"]["content"]["pageHeaderViewModel"]["image"]["decoratedAvatarViewModel"]["rendererContext"]["commandContext"]["onTap"]["innertubeCommand"]["watchEndpoint"]["videoId"]
    except Exception:
        pass

    items = []
    seen_ids = set()

    tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    contents = []
    for t in tabs:
        tr = t.get("tabRenderer", {})
        if tr.get("title") in ["Live", "Streams"]:
            contents = tr.get("content", {}).get("richGridRenderer", {}).get("contents", [])
            break

    if not contents:
        for t in tabs:
            tr = t.get("tabRenderer", {})
            if tr.get("selected"):
                contents = tr.get("content", {}).get("richGridRenderer", {}).get("contents", [])
                break

    for item in contents:
        rich_item = item.get("richItemRenderer", {})
        lockup = rich_item.get("content", {}).get("lockupViewModel", {})
        if lockup:
            vid = lockup.get("contentId")
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)

            metadata = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
            title = metadata.get("title", {}).get("content", "")

            thumbnails = lockup.get("contentImage", {}).get("thumbnailViewModel", {}).get("image", {}).get("sources", [])
            thumb_url = thumbnails[-1].get("url") if thumbnails else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

            badges = []
            is_live = False
            is_upcoming = False
            overlays = lockup.get("contentImage", {}).get("thumbnailViewModel", {}).get("overlays", [])
            for ov in overlays:
                bottom = ov.get("thumbnailBottomOverlayViewModel", {})
                for b in bottom.get("badges", []):
                    badge_vm = b.get("thumbnailBadgeViewModel", {})
                    txt = badge_vm.get("text", "")
                    style = badge_vm.get("badgeStyle", "")
                    if txt:
                        badges.append(txt)
                    if "LIVE" in txt.upper() or style == "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE":
                        is_live = True
                    elif "UPCOMING" in txt.upper():
                        is_upcoming = True

                time_status = ov.get("thumbnailOverlayTimeStatusRenderer", {})
                if time_status:
                    txt = time_status.get("text", {}).get("runs", [{}])[0].get("text") or time_status.get("style", "")
                    if txt:
                        badges.append(txt)
                    if "LIVE" in txt.upper():
                        is_live = True
                    elif "UPCOMING" in txt.upper():
                        is_upcoming = True

            meta_parts = []
            scheduled_start = None
            watching = None
            for row in metadata.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", []):
                for p in row.get("metadataParts", []):
                    c = p.get("text", {}).get("content", "")
                    if c:
                        meta_parts.append(c)
                        if "watching" in c.lower():
                            watching = c
                            is_live = True
                        elif "scheduled" in c.lower() or "waiting" in c.lower():
                            scheduled_start = c
                            is_upcoming = True

            status = "live" if is_live else ("upcoming" if is_upcoming else "completed")
            items.append({
                "video_id": vid,
                "title": title,
                "status": status,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "proxy_stream": f"{base_url}/live/{vid}" if base_url else f"/live/{vid}",
                "thumbnail": thumb_url,
                "watching": watching,
                "scheduled_start": scheduled_start,
                "badges": badges,
                "meta": meta_parts,
            })
            continue

        vr = rich_item.get("content", {}).get("videoRenderer") or item.get("gridVideoRenderer")
        if vr:
            vid = vr.get("videoId")
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)

            title = vr.get("title", {}).get("runs", [{}])[0].get("text") or vr.get("title", {}).get("simpleText", "")
            thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
            thumb_url = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

            is_live = False
            is_upcoming = False
            badges = []
            for b in vr.get("badges", []):
                label = b.get("metadataBadgeRenderer", {}).get("label") or b.get("metadataBadgeRenderer", {}).get("style")
                if label:
                    badges.append(str(label))
                if "LIVE" in str(label).upper():
                    is_live = True

            if vr.get("upcomingEventData"):
                is_upcoming = True

            status = "live" if is_live else ("upcoming" if is_upcoming else "completed")
            items.append({
                "video_id": vid,
                "title": title,
                "status": status,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "proxy_stream": f"{base_url}/live/{vid}" if base_url else f"/live/{vid}",
                "thumbnail": thumb_url,
                "badges": badges,
            })

    # Cek avatar live: jika ada dan belum masuk list
    if avatar_live_id and avatar_live_id not in seen_ids:
        avatar_title = get_video_title_oembed(avatar_live_id) or f"{channel_name or clean_handle} Live Stream"
        items.insert(0, {
            "video_id": avatar_live_id,
            "title": avatar_title,
            "status": "live",
            "url": f"https://www.youtube.com/watch?v={avatar_live_id}",
            "proxy_stream": f"{base_url}/live/{avatar_live_id}" if base_url else f"/live/{avatar_live_id}",
            "thumbnail": f"https://i.ytimg.com/vi/{avatar_live_id}/hqdefault.jpg",
            "badges": ["LIVE"],
        })
        seen_ids.add(avatar_live_id)

    live_items = [it for it in items if it["status"] == "live"]
    upcoming_items = [it for it in items if it["status"] == "upcoming"]
    completed_items = [it for it in items if it["status"] == "completed"]

    result = {
        "channel_name": channel_name or clean_handle,
        "target": clean_handle,
        "url": url,
        "total": len(items),
        "live": live_items,
        "upcoming": upcoming_items,
        "completed": completed_items,
        "cached": False,
    }

    if use_cache:
        channel_cache[cache_key] = (result, time.time() + cache_ttl)

    return result


def generate_m3u_playlist(channel_data: dict, base_url: str, quality: str = "best", include_upcoming: bool = False) -> str:
    """Membuat konten playlist format M3U standar untuk IPTV Player"""
    lines = ["#EXTM3U"]
    ch_name = channel_data.get("channel_name") or channel_data.get("target") or "YouTube Live"

    # 1. Masukkan semua live yang sedang berlangsung
    for item in channel_data.get("live", []):
        vid = item["video_id"]
        title = item.get("title") or f"{ch_name} Live"
        thumb = item.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        stream_url = f"{base_url}/live/{vid}"
        if quality and quality != "best":
            stream_url += f"?quality={quality}"
        lines.append(f'#EXTINF:-1 tvg-id="{vid}" tvg-name="{title}" tvg-logo="{thumb}" group-title="{ch_name}",{title}')
        lines.append(stream_url)

    # 2. Masukkan jadwal siaran akan datang (jika diminta)
    if include_upcoming:
        for item in channel_data.get("upcoming", []):
            vid = item["video_id"]
            title = f"[Upcoming] {item.get('title')}"
            sched = item.get("scheduled_start")
            if sched:
                title += f" ({sched})"
            thumb = item.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            stream_url = f"{base_url}/live/{vid}"
            if quality and quality != "best":
                stream_url += f"?quality={quality}"
            lines.append(f'#EXTINF:-1 tvg-id="{vid}" tvg-name="{title}" tvg-logo="{thumb}" group-title="{ch_name} (Upcoming)",{title}')
            lines.append(stream_url)

    return "\n".join(lines) + "\n"

def resolve_youtube_url(target: str) -> str:
    target = target.strip()
    if target.endswith(".ts") or target.endswith(".m3u8"):
        target = target.rsplit(".", 1)[0]

    if target.startswith("@"):
        return f"https://www.youtube.com/{target}/live"
    elif target.startswith("UC") and len(target) == 24:
        return f"https://www.youtube.com/channel/{target}/live"
    elif target.startswith("http://") or target.startswith("https://"):
        return target
    else:
        return f"https://www.youtube.com/watch?v={target}"


def get_stream(target: str, quality: str = "best"):
    yt_url = resolve_youtube_url(target)
    logger.info(f"Resolving stream for target '{target}' -> URL: {yt_url}")
    try:
        streams = session.streams(yt_url)
        if not streams:
            logger.warning(f"No streams found for {yt_url}")
            raise HTTPException(
                status_code=404,
                detail=f"Live stream offline atau video tidak ditemukan untuk target: {target}"
            )

        stream = streams.get(quality) or streams.get("best")
        if not stream:
            stream = list(streams.values())[0]
        return stream
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching streams: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gagal mengambil info stream: {str(e)}")


def iter_stream(fd, chunk_size: int = 64 * 1024):
    """Generator untuk mengalirkan data video (MPEG-TS) kontinu ke client"""
    try:
        while True:
            chunk = fd.read(chunk_size)
            if not chunk:
                break
            yield chunk
    except GeneratorExit:
        pass
    except Exception as e:
        logger.warning(f"Client disconnected or stream read ended: {e}")
    finally:
        try:
            fd.close()
        except Exception:
            pass


@app.get("/", response_class=PlainTextResponse)
def index():
    return (
        "YouTube Live Proxy is running on Railway!\n\n"
        f"Cookie Status : {cookie_status_msg}\n"
        f"Active Cookies: {len(cookie_jar)}\n\n"
        "Usage for VLC / IPTV Player:\n"
        "  - Stream Live    : /live/@KompasTV  atau  /live/<VIDEO_ID>\n"
        "  - Quality param  : /live/@KompasTV?quality=720p (options: best, 720p, 480p, 360p, worst)\n\n"
        "Extract Live & Upcoming Channel Streams:\n"
        "  - JSON List      : /channel/@BWF/streams\n"
        "  - Playlist M3U   : /channel/@BWF/streams.m3u (hanya siaran live aktif)\n"
        "  - M3U with Upcom : /channel/@BWF/streams.m3u?upcoming=true\n"
        "  - Refresh Cache  : /channel/@BWF/streams?refresh=true\n\n"
        "Diagnostic & Admin:\n"
        "  - Debug target   : /debug/<VIDEO_ID>\n"
        "  - Reload cookies : /reload-cookies\n"
    )


@app.get("/reload-cookies")
def reload_cookies():
    """Reload cookies dari cookies.txt atau env tanpa restart container"""
    success = load_youtube_cookies()
    return {
        "success": success,
        "message": cookie_status_msg,
        "cookie_count": len(cookie_jar),
    }


@app.get("/debug/{target}")
def debug_info(target: str):
    """Endpoint untuk menganalisis respons YouTube dari IP Railway"""
    yt_url = resolve_youtube_url(target)
    result = {
        "target": target,
        "resolved_url": yt_url,
        "cookie_status": cookie_status_msg,
        "cookie_count": len(cookie_jar),
    }

    # Cek IP Server Railway
    try:
        ip_resp = requests.get("https://api.ipify.org?format=json", timeout=5).json()
        result["server_ip"] = ip_resp.get("ip")
    except Exception as e:
        result["server_ip_err"] = str(e)

    # Cek scraping YouTube langsung (dengan cookies jika ada)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        yt_resp = requests.get(yt_url, headers=headers, cookies=cookie_jar if len(cookie_jar) > 0 else None, timeout=10)
        result["yt_status"] = yt_resp.status_code

        # Cari playabilityStatus
        match = re.search(r'ytInitialPlayerResponse\s*=\s*({.+?});', yt_resp.text)
        if match:
            try:
                data = json.loads(match.group(1))
                result["playability"] = data.get("playabilityStatus")
            except Exception as e:
                result["json_parse_err"] = str(e)
        else:
            # Cari bot check / captcha
            if "captcha" in yt_resp.text.lower() or "robot" in yt_resp.text.lower():
                result["bot_detected"] = True
            result["ytInitialPlayerResponse_found"] = False
    except Exception as e:
        result["yt_fetch_err"] = str(e)

    # Cek streamlink
    try:
        streams = session.streams(yt_url)
        result["streamlink_available"] = list(streams.keys())
    except Exception as e:
        result["streamlink_err"] = str(e)

    return JSONResponse(result)


@app.get("/channel/{target:path}/streams.m3u")
def channel_streams_m3u(target: str, request: Request, quality: str = "best", upcoming: bool = False, refresh: bool = False):
    """
    Menghasilkan playlist M3U langsung untuk IPTV player (TiviMate, VLC, OTT Navigator)
    berisi semua video live yang sedang berlangsung (dan upcoming jika upcoming=true).
    """
    base_url = get_public_base_url(request)
    data = extract_channel_streams(target, base_url=base_url, use_cache=not refresh)

    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])

    m3u_text = generate_m3u_playlist(data, base_url=base_url, quality=quality, include_upcoming=upcoming)
    clean_target = data.get("target", "streams").replace("@", "")
    return Response(
        content=m3u_text,
        media_type="application/x-mpegurl",
        headers={
            "Content-Disposition": f'inline; filename="{clean_target}.m3u"',
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "max-age=60, public",
        },
    )


@app.get("/channel/{target:path}/streams")
def channel_streams_json(target: str, request: Request, refresh: bool = False):
    """
    Ekstrak daftar video live stream yang sedang berlangsung, upcoming,
    dan yang baru selesai dari channel YouTube dalam format JSON terstruktur.
    """
    base_url = get_public_base_url(request)
    data = extract_channel_streams(target, base_url=base_url, use_cache=not refresh)

    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])

    return JSONResponse(
        data,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "max-age=60, public",
        },
    )


@app.get("/live/{target}")
def live_stream(target: str, quality: str = "best"):
    clean_target = target.replace(".ts", "").replace(".m3u8", "")
    stream = get_stream(clean_target, quality)

    try:
        fd = stream.open()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal membuka stream: {str(e)}")

    return StreamingResponse(
        iter_stream(fd),
        media_type="video/mp2t",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Content-Disposition": f"inline; filename={clean_target}.ts",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
