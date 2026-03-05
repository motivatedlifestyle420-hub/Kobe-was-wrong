# Tapo NVR Stack – Security Operations Command Center

A fully local, cloud-free NVR system supporting **8 RTSP cameras** with AI detection, low-latency WebRTC browser streams, event timeline, alerts, and 24/7 recording.

The 4 Tapo C425 battery cameras (no RTSP) remain managed separately in the Tapo app.

```
8× Tapo RTSP cams
      │  (RTSP per-cam)
      ▼
   go2rtc       ← RTSP relay → WebRTC / HLS (sub-second latency)
      │
      ▼
   Frigate      ← AI detection (person / car / pet) + NVR + events
      │
      ├── Mosquitto (MQTT, auth required)  ← event bus → push notifications
      │
      └── Dashboard                        ← command-center UI (port 8080)

4× C425 battery cameras → Tapo app (motion events only, no RTSP)
```

---

## System layout

| Component | Count | Notes |
|---|---|---|
| RTSP cameras (Frigate) | 8 | cam1–cam8 in config |
| Battery cameras (Tapo app) | 4 | C425, cloud motion events only |
| **Total cameras** | **12** | |

**Resource estimate for 8 cameras (CPU detector):**
- CPU: ~15–25%
- RAM: ~2–3 GB
- Storage: ~150–250 GB/week (motion recording)

---

## What you get

| Feature | Implementation |
|---|---|
| Live 8-cam grid in browser | go2rtc WebRTC iframes (sub-second latency) |
| AI detection – person / car / pet | Frigate + YOLOv8n (CPU default; Coral/GPU optional) |
| Event timeline + clips + snapshots | Frigate built-in review UI + REST API |
| Push notifications | Frigate → Mosquitto → Home Assistant / ntfy / Node-RED |
| 24/7 recording (motion-only segments) | Frigate continuous + motion retention |
| Camera offline alerts | Frigate publishes `offline` state to MQTT |
| Health monitoring dashboard | Custom dashboard polls Frigate `/api/stats` |
| 100% local – no cloud | All services run in Docker on your LAN |

---

## Prerequisites

- Docker + Docker Compose v2
- A machine on the same LAN as your cameras (**works on Linux, macOS, and Windows Docker Desktop**)
- 8 Tapo cameras with RTSP enabled (see below)

### Enable RTSP on Tapo cameras

1. Open the **Tapo** app → select your camera
2. **Settings → Advanced Settings → Camera Account** → set a username & password
3. Note each camera's **IP address** (set a DHCP reservation so it never changes)
4. RTSP stream URLs (standard Tapo firmware, port 554):
   - Main (1080p/4K): `rtsp://<user>:<pass>@<camera_ip>:554/stream1`
   - Sub  (360p):     `rtsp://<user>:<pass>@<camera_ip>:554/stream2`

---

## Quick Start

```bash
# 1. Clone & enter the directory
git clone <repo-url> && cd <repo-name>

# 2. Create .env from the example and fill in credentials
cp .env.example .env
#    Set: CAM_USER, CAM_PASS, MQTT_USER, MQTT_PASSWORD

# 3. Edit camera IPs in go2rtc config (replace 192.168.0.41–.48)
nano config/go2rtc.yaml

# 4. Create required runtime directories and empty passwd file
mkdir -p data/mosquitto data/mosquitto_log data/frigate media
touch config/mosquitto_passwd

# 5. Launch everything
docker compose up -d

# 6. Open the command-center dashboard
open http://localhost:8080
```

---

## Service URLs

| Service | URL | Notes |
|---|---|---|
| **Dashboard** | http://localhost:8080 | 8-camera command-center |
| **Frigate UI** | http://localhost:5000 | AI events, clips, recording review |
| **go2rtc UI** | http://localhost:1984 | Stream health, WebRTC test players |
| **MQTT broker** | 127.0.0.1:1883 | Localhost only; auth required |

---

## Folder layout

```
.
├── config/
│   ├── go2rtc.yaml          ← camera IPs (edit before first run)
│   ├── frigate.yml          ← NVR + detection config
│   ├── mosquitto.conf       ← MQTT broker config
│   └── mosquitto_passwd     ← hashed passwd (written by container at startup)
├── dashboard/               ← static 8-cam command center
├── data/
│   ├── frigate/             ← Frigate SQLite DB (gitignored)
│   ├── mosquitto/           ← MQTT persistence (gitignored)
│   └── mosquitto_log/       ← MQTT logs (gitignored)
├── media/                   ← recordings + snapshots (gitignored)
├── .env                     ← credentials (gitignored)
└── docker-compose.yml
```

---

## Networking notes

All four services (`mosquitto`, `go2rtc`, `frigate`, `dashboard`) share the same Docker bridge network:

- **go2rtc uses bridge networking (NOT host)** — Frigate resolves streams via Docker DNS: `rtsp://go2rtc:8554/cam1_main`
- **MQTT ports are bound to `127.0.0.1`** — broker is unreachable from the LAN; Docker-internal services connect via `mosquitto:1883`
- Works identically on **Linux**, **macOS**, and **Windows Docker Desktop**

---

## Verification checklist

Run these in order after `docker compose up -d`.

### Step 1 – All containers are up

```bash
docker compose ps
# Expected: mosquitto, go2rtc, frigate, tapo_dashboard all "running"
```

### Step 2 – go2rtc is serving streams

```bash
curl http://localhost:1984/api/streams
# Expected: JSON listing cam1_main, cam1_sub … cam8_main, cam8_sub
```

Open http://localhost:1984 → click a stream → live WebRTC player should appear.

### Step 3 – Frigate can reach go2rtc

```bash
docker compose logs frigate | grep -i "error\|failed\|refused"
# Expected: no connection errors
```

Open http://localhost:5000 → **System** tab → all cameras show green FPS counter.

### Step 4 – MQTT auth is enforced

```bash
# Must FAIL (anonymous rejected):
mosquitto_sub -h 127.0.0.1 -t "frigate/#" -v
# Expected: "Connection Refused: not authorised"

# Must SUCCEED:
mosquitto_sub -h 127.0.0.1 -u "$MQTT_USER" -P "$MQTT_PASSWORD" -t "frigate/#" -v
# Expected: Frigate heartbeat messages every ~30 s
```

### Step 5 – Detections are flowing

Walk in front of a camera, then:

```bash
mosquitto_sub -h 127.0.0.1 -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t "frigate/events" -C 1
# Expected: JSON event with label "person"
```

Open http://localhost:5000 → **Events** tab → clip should appear.

---

## Adding / removing cameras

1. Add streams in `config/go2rtc.yaml`:
   ```yaml
   cam9_main: rtsp://${CAM_USER}:${CAM_PASS}@192.168.0.49:554/stream1
   cam9_sub:  rtsp://${CAM_USER}:${CAM_PASS}@192.168.0.49:554/stream2
   ```

2. Add a camera block in `config/frigate.yml`:
   ```yaml
   cam9:
     ffmpeg:
       inputs:
         - path: rtsp://go2rtc:8554/cam9_sub
           input_args: preset-rtsp-restream
           roles: [detect]
         - path: rtsp://go2rtc:8554/cam9_main
           input_args: preset-rtsp-restream
           roles: [record]
     detect: { width: 640, height: 360, fps: 5 }
   ```

3. Add the camera to `dashboard/index.html`:
   ```js
   { id: "cam9_main", frigateId: "cam9", label: "Camera 9" },
   ```

4. Restart:
   ```bash
   docker compose restart go2rtc frigate
   ```

---

## Hardware acceleration (recommended)

### Google Coral USB

Uncomment in `docker-compose.yml`:
```yaml
devices: [/dev/bus/usb:/dev/bus/usb]
```
Replace detector in `config/frigate.yml`:
```yaml
detectors:
  coral:
    type: edgetpu
    device: usb
```

### NVIDIA GPU

Uncomment in `docker-compose.yml`:
```yaml
runtime: nvidia
devices: [/dev/nvidia0:/dev/nvidia0]
```
Replace detector in `config/frigate.yml`:
```yaml
detectors:
  tensorrt:
    type: tensorrt
    device: 0
```

---

## Push notifications

### ntfy (simplest)

Use Frigate's built-in webhook (Frigate 0.13+):
**Settings → Notifications → Webhook → `https://ntfy.sh/<your-topic>`**

### Home Assistant

1. Add the [Frigate integration](https://github.com/blakeblackshear/frigate-hass-integration)
2. Add the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) → `127.0.0.1:1883` with credentials from `.env`
3. Create automations: `frigate/events` → mobile app push notification

---

## Storage layout

```
media/
  recordings/<camera>/<YYYY-MM>/<DD>/<HH>/<MM.SS.mp4>   ← motion segments
  clips/<camera>-<timestamp>-<label>.mp4                 ← event clips
  snapshots/<camera>-<timestamp>-<label>.jpg             ← best-frame snapshots
```

Default retention: **7 days** continuous · **14 days** snapshots.  
Adjust in `config/frigate.yml` → `record.retain` / `snapshots.retain`.

---

## Useful commands

```bash
# Status
docker compose ps

# Logs
docker compose logs -f
docker compose logs -f frigate

# Stream health
curl http://localhost:1984/api/streams

# Frigate stats
curl http://localhost:5000/api/stats | python3 -m json.tool

# Subscribe MQTT (with auth)
mosquitto_sub -h 127.0.0.1 -u "$MQTT_USER" -P "$MQTT_PASSWORD" -t "frigate/#" -v

# Stop
docker compose down

# Stop + wipe data (⚠ deletes all recordings)
docker compose down && rm -rf data/ media/
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Black camera tiles | Check go2rtc logs; verify IPs in `config/go2rtc.yaml`; confirm RTSP is enabled on camera |
| No detections | Check Frigate logs; confirm detect is enabled; lower `min_score` if needed |
| "Offline" camera badge | Camera lost network; set a DHCP reservation for each camera IP |
| High CPU usage | Enable Coral USB or GPU detector; reduce `fps` to 3 per camera |
| Disk full | Lower retention in `frigate.yml`; use `mode: motion` for continuous recording |
| MQTT "not authorised" | Confirm `MQTT_USER`/`MQTT_PASSWORD` in `.env`; restart mosquitto |
| go2rtc streams not connecting | Confirm camera IP and port 554; check `docker compose logs go2rtc` |
| `ERROR: MQTT_USER not set` | `.env` file is missing or empty; run `cp .env.example .env` and fill in |

---

## Architecture diagram

```
┌──────────────────────────────────────────────────────────────────┐
│               Docker bridge network                              │
│                                                                  │
│  8× Tapo RTSP ──────► go2rtc ─────RTSP─────► Frigate           │
│  (LAN 192.168.0.4x)  :1984/:8554/:8555    :5000/:8971           │
│                           │                    │                 │
│                       WebRTC iframe        MQTT events           │
│                           ▼                    ▼                 │
│                       Dashboard            Mosquitto             │
│                       (port 8080)       (127.0.0.1:1883)        │
│                                             │                    │
│                                         HA / ntfy               │
│                                         (push alerts)           │
└──────────────────────────────────────────────────────────────────┘

4× C425 battery ──► Tapo App (motion events, separate from Frigate)
```
