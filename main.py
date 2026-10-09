import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
import streamlink
import uvicorn

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
    try:
        streams = session.streams(yt_url)
        if not streams:
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
    except Exception:
        pass
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
    )


@app.get("/live/{target}")
def live_stream(target: str, quality: str = "best"):
    """
    Streaming MPEG-TS langsung ke client (VLC, TiviMate, OTT Navigator, STB Android, dll).
    Bebas dari masalah IP-Locking YouTube karena video chunk di-fetch oleh server Railway.
    """
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
    uvicorn.run("main:app", host="0.0.0.0", port=port)
