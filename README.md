# YouTube Live Proxy (Railway)

Aplikasi streaming proxy YouTube Live untuk VLC, TiviMate, OTT Navigator, dan IPTV Player lainnya.
Bebas IP-Lock (Anti 403 Forbidden).

---

## Cara Deploy ke Railway (Sangat Mudah):

### Opsi A: Lewat GitHub (Rekomendasi)
1. Buat repository baru di GitHub (misal: `yt-railway-proxy`).
2. Masukkan file-file dari folder ini (`Dockerfile`, `Procfile`, `requirements.txt`, `main.py`).
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

---

## Cara Pakai di VLC & IPTV:

### 1. Di VLC Media Player (Ctrl + N)
- Pakai Channel Handle:
  `https://URL-RAILWAY-ANDA/live/@KompasTV`
- Pakai Video ID:
  `https://URL-RAILWAY-ANDA/live/K0-6reET2BY`
- Dengan Kualitas Hemat Kuota (opsional):
  `https://URL-RAILWAY-ANDA/live/@KompasTV?quality=720p`

### 2. Format Playlist IPTV (.m3u)
```m3u
#EXTM3U

#EXTINF:-1 tvg-id="" tvg-name="Kompas TV" group-title="Nasional",Kompas TV
https://URL-RAILWAY-ANDA/live/@KompasTV

#EXTINF:-1 tvg-id="" tvg-name="Metro TV" group-title="Nasional",Metro TV
https://URL-RAILWAY-ANDA/live/@metrotvnews
```
