import os
import sys
import logging
import json
import re
import http.cookiejar
from fastapi import FastAPI, HTTPException, Request
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
        "  - Channel Handle : /live/@KompasTV\n"
        "  - Video ID       : /live/<VIDEO_ID>\n"
        "  - Quality param  : /live/@KompasTV?quality=720p (options: best, 720p, 480p, 360p, worst)\n"
        "  - Debug info     : /debug/<VIDEO_ID>\n"
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
