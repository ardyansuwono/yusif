import os
import sys
import logging
import json
import re
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, PlainTextResponse, JSONResponse
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
        "Usage for VLC / IPTV Player:\n"
        "  - Channel Handle : /live/@KompasTV\n"
        "  - Video ID       : /live/<VIDEO_ID>\n"
        "  - Quality param  : /live/@KompasTV?quality=720p (options: best, 720p, 480p, 360p, worst)\n"
        "  - Debug info     : /debug/<VIDEO_ID>\n"
    )


@app.get("/debug/{target}")
def debug_info(target: str):
    """Endpoint untuk menganalisis respons YouTube dari IP Railway"""
    yt_url = resolve_youtube_url(target)
    result = {"target": target, "resolved_url": yt_url}

    # Cek IP Server Railway
    try:
        ip_resp = requests.get("https://api.ipify.org?format=json", timeout=5).json()
        result["server_ip"] = ip_resp.get("ip")
    except Exception as e:
        result["server_ip_err"] = str(e)

    # Cek scraping YouTube langsung
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        yt_resp = requests.get(yt_url, headers=headers, timeout=10)
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
