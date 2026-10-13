# YouTube Live Proxy (Railway)

Aplikasi streaming proxy YouTube Live untuk VLC, TiviMate, OTT Navigator, dan IPTV Player lainnya.
Bebas IP-Lock (Anti 403 Forbidden).

---

## Fitur Unggulan:
1. **MPEG-TS Live Proxy**: Memutar stream YouTube live tanpa terblokir BotGuard / geoblock cookies.
2. **Channel Live & Upcoming Extractor (Baru!)**:
   - Mengekstrak siaran yang **sedang live** maupun siaran **yang akan datang (upcoming/scheduled)** dari tab `/streams` channel manapun (seperti `@BWF`, `@KompasTV`, dll).
   - Mendeteksi multi-court / multi-stream live yang sedang tayang serentak.
   - Deteksi otomatis link live pada avatar ring channel YouTube.
   - Endpoint **JSON** untuk integrasi bot/frontend/web app.
   - Endpoint **M3U Playlist** langsung siap pakai di TiviMate, OTT Navigator, atau VLC.

---

## Cara Pakai:

### 1. Ekstrak Live & Upcoming dari Channel (Format JSON)
Gunakan handle channel (`@BWF`), ID channel (`UChh-akEbUM8_6ghGVnJd6cQ`), atau URL:
```text
GET https://URL-RAILWAY-ANDA/channel/@BWF/streams
```
**Contoh Output JSON**:
```json
{
  "channel_name": "BWF TV",
  "target": "@BWF",
  "url": "https://www.youtube.com/@BWF/streams",
  "total": 9,
  "live": [
    {
      "video_id": "rejKxRNOAfc",
      "title": "VICTOR Denmark Open 2026 | Day 1 | Court 3 | Round of 32",
      "status": "live",
      "url": "https://www.youtube.com/watch?v=rejKxRNOAfc",
      "proxy_stream": "https://URL-RAILWAY-ANDA/live/rejKxRNOAfc",
      "thumbnail": "https://i.ytimg.com/vi/rejKxRNOAfc/hqdefault.jpg",
      "badges": ["LIVE"]
    }
  ],
  "upcoming": [
    {
      "video_id": "EeI8Aox-o3s",
      "title": "AirBadminton European Championships 2026 Day 2 Session 2 Court 2",
      "status": "upcoming",
      "scheduled_start": "Scheduled for 10/15/26, 8:30 AM",
      "proxy_stream": "https://URL-RAILWAY-ANDA/live/EeI8Aox-o3s"
    }
  ],
  "completed": []
}
```

### 2. Playlist Otomatis IPTV (.m3u) dari Channel
Cukup masukkan link ini ke IPTV Player (TiviMate / OTT Navigator / VLC):
- **Hanya Live Aktif**:
  `https://URL-RAILWAY-ANDA/channel/@BWF/streams.m3u`
- **Live Aktif + Jadwal Akan Datang (Upcoming)**:
  `https://URL-RAILWAY-ANDA/channel/@BWF/streams.m3u?upcoming=true`
- **Pilih Kualitas (Hemat Kuota)**:
  `https://URL-RAILWAY-ANDA/channel/@BWF/streams.m3u?quality=720p`

---

## Cara Nonton Langsung di VLC & IPTV:

### 1. Di VLC Media Player (Ctrl + N)
- Pakai Channel Handle:
  `https://URL-RAILWAY-ANDA/live/@KompasTV`
- Pakai Video ID:
  `https://URL-RAILWAY-ANDA/live/rejKxRNOAfc`
- Dengan Kualitas Hemat Kuota (opsional):
  `https://URL-RAILWAY-ANDA/live/@KompasTV?quality=720p`

### 2. Format Playlist IPTV (.m3u) Manual
```m3u
#EXTM3U

#EXTINF:-1 tvg-id="" tvg-name="Kompas TV" group-title="Nasional",Kompas TV
https://URL-RAILWAY-ANDA/live/@KompasTV

#EXTINF:-1 tvg-id="" tvg-name="Metro TV" group-title="Nasional",Metro TV
https://URL-RAILWAY-ANDA/live/@metrotvnews
```

---

## Cara Deploy ke Railway (Sangat Mudah):

### Opsi A: Lewat GitHub (Rekomendasi)
1. Buat repository baru di GitHub (misal: `yt-railway-proxy`).
2. Masukkan file-file dari folder ini (`Dockerfile`, `Procfile`, `requirements.txt`, `main.py`, dan `cookies.txt`).
   > *Tips Keamanan*: Jika repository GitHub Anda **Public**, jangan commit file `cookies.txt`. Sebagai gantinya, buka dashboard Railway -> pilih Service -> tab **Variables** -> Tambahkan variable `YOUTUBE_COOKIES` dan paste isi dari file `cookies.txt` ke sana.
3. Buka dashboard [railway.com](https://railway.com/).
4. Klik **+ New Project** -> **Deploy from GitHub repo**.
5. Pilih repo yang tadi Anda buat.
6. Masuk ke tab **Settings** di service yang baru dibuat -> Scroll ke bagian **Networking** -> Klik **Generate Domain**.
7. Anda akan mendapatkan URL HTTPS (contoh: `https://yt-railway-proxy-production.up.railway.app`).

### Opsi B: Lewat Railway CLI (Tanpa Buka Browser)
Di folder `youtube/railway/`:
```bash
npm install -g @railway/cli
railway login
railway init
railway up
railway domain
```

