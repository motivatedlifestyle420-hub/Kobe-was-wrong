# Tapo NVR Stack – Security Operations Command Center

A fully local, cloud-free NVR system for Tapo cameras with AI detection, low-latency WebRTC browser streams, event timeline, alerts, and 24/7 recording.

```
Tapo cams (RTSP)
      │
      ▼
   go2rtc          ← converts RTSP → WebRTC (low-latency browser streams)
      │
      ▼
   Frigate         ← AI detection (person / vehicle / pet) + NVR + events
      │
      ├── Mosquitto (MQTT)   ← event bus → push notifications
      │
      └── Dashboard          ← command-center UI (http://localhost:8080)
```

---

## What you get

| Feature | Implementation |
|---|---|
| Live multi-cam grid in browser | go2rtc WebRTC iframes (sub-second latency) |
| AI detection – person / car / pet | Frigate + YOLOv8n (CPU default; Coral/GPU optional) |
| Detection zones + motion masks | Per-camera zone polygons in `config/frigate.yml` |
| Event timeline + clips + snapshots | Frigate built-in review UI + REST API |
| Push notifications | Frigate → Mosquitto → Home Assistant / ntfy / Node-RED |
| 24/7 recording (per-camera toggle) | Frigate continuous + motion-only retention |
| Camera offline alerts | Frigate publishes `offline` state to MQTT |
| Health monitoring dashboard | Custom dashboard polls Frigate `/api/stats` |
| 100% local – no cloud | All services run in Docker on your LAN |

---

## Prerequisites

- Docker + Docker Compose v2
- A machine on the same LAN as your Tapo cameras (Linux recommended; works on Mac/Windows too)
- Tapo cameras with RTSP enabled (see below)

### Enable RTSP on Tapo cameras

1. Open the **Tapo** app → select your camera
2. **Settings → Advanced Settings → Camera Account** → set a username & password
3. Note each camera's **IP address** (set a DHCP reservation so it never changes)
4. RTSP stream URLs:
   - Main (1080p): `rtsp://<user>:<pass>@<camera_ip>/stream1`
   - Sub (360p):   `rtsp://<user>:<pass>@<camera_ip>/stream2`

---

## Quick Start

```bash
# 1. Clone & enter the directory
git clone <repo-url> && cd <repo-name>

# 2. Create your .env file from the example
cp .env.example .env
# Edit .env: set TZ, CAMERA_USER, CAMERA_PASSWORD, CAM1_IP … CAM4_IP

# 3. Edit camera IPs in go2rtc config
#    Replace {CAM1_IP}…{CAM4_IP} with your real IPs
nano config/go2rtc.yaml

# 4. (Optional) Tune zones/recording in Frigate config
nano config/frigate.yml

# 5. Launch everything
docker compose up -d

# 6. Open the command-center dashboard
open http://localhost:8080
```

---

## Service URLs

| Service | URL | Notes |
|---|---|---|
| **Dashboard** | http://localhost:8080 | Command-center landing page |
| **Frigate UI** | http://localhost:5000 | AI events, clips, recording review |
| **go2rtc UI** | http://localhost:1984 | Stream health, WebRTC test players |
| **MQTT broker** | localhost:1883 | Subscribe with any MQTT client |

---

## Adding / removing cameras

1. Add a new stream block in `config/go2rtc.yaml`:
   ```yaml
   side_gate:
     - rtsp://{CAMERA_USER}:{CAMERA_PASSWORD}@192.168.1.105/stream1#backchannel=0
   side_gate_sub:
     - rtsp://{CAMERA_USER}:{CAMERA_PASSWORD}@192.168.1.105/stream2#backchannel=0
   ```

2. Add a matching camera block in `config/frigate.yml`:
   ```yaml
   side_gate:
     enabled: true
     ffmpeg:
       inputs:
         - path: rtsp://go2rtc:8554/side_gate
           roles: [record]
         - path: rtsp://go2rtc:8554/side_gate_sub
           roles: [detect]
     detect:
       width: 640
       height: 360
       fps: 5
   ```

3. Add the camera to the `CAMERAS` array in `dashboard/index.html`.

4. Restart:
   ```bash
   docker compose restart go2rtc frigate
   ```

---

## Hardware acceleration (recommended)

### Google Coral USB

```bash
# Plug in the Coral, then uncomment in docker-compose.yml:
#   devices: [/dev/bus/usb:/dev/bus/usb]
# And in config/frigate.yml replace the detector block:
#   detectors:
#     coral:
#       type: edgetpu
#       device: usb
docker compose up -d frigate
```

### NVIDIA GPU

```bash
# Install nvidia-docker2, then uncomment in docker-compose.yml:
#   runtime: nvidia
#   devices: [/dev/nvidia0:/dev/nvidia0]
# And in config/frigate.yml replace the detector block:
#   detectors:
#     tensorrt:
#       type: tensorrt
#       device: 0
docker compose up -d frigate
```

---

## Push notifications

### ntfy (simplest – no account needed)

```bash
# Subscribe Frigate MQTT events → ntfy via Node-RED or a small bridge script.
# Or use Frigate's built-in notification webhook (Frigate 0.13+):
#   Settings → Notifications → Webhook → https://ntfy.sh/<your-topic>
```

### Home Assistant

1. Add the [Frigate integration](https://github.com/blakeblackshear/frigate-hass-integration)
2. Add the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) pointing at `localhost:1883`
3. Create automations: `frigate/events` → mobile app push notification

---

## Storage layout

Recordings and snapshots are stored in the Docker volume `frigate_media`, mounted at `/media/frigate` inside the container:

```
/media/frigate/
  recordings/<camera>/<YYYY-MM>/<DD>/<HH>/<MM.SS.mp4>   ← 24/7 segments
  clips/<camera>-<timestamp>-<label>.mp4                 ← event clips
  snapshots/<camera>-<timestamp>-<label>.jpg             ← best-frame snapshots
```

Default retention: **7 days** continuous · **30 days** event clips/snapshots.  
Adjust in `config/frigate.yml` → `record.retain` / `snapshots.retain`.

---

## Useful commands

```bash
# View logs for all services
docker compose logs -f

# View Frigate logs only
docker compose logs -f frigate

# Check stream health
curl http://localhost:1984/api/streams

# Check Frigate stats (FPS, storage, detector)
curl http://localhost:5000/api/stats | python3 -m json.tool

# Subscribe to all Frigate MQTT events
mosquitto_sub -h localhost -t "frigate/#" -v

# Stop everything
docker compose down

# Stop and remove volumes (⚠ deletes all recordings)
docker compose down -v
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Black camera tiles in dashboard | Check go2rtc logs; verify camera IP/credentials in `.env` and `config/go2rtc.yaml` |
| No detections | Check Frigate logs; confirm `detect.enabled: true` and zone coordinates are correct |
| "Offline" camera badge | Camera lost network – check LAN; set a DHCP reservation for the camera IP |
| High CPU usage | Enable Coral USB or GPU detector; reduce `fps` per camera in `frigate.yml` |
| Disk full | Lower retention days in `frigate.yml`; use `mode: motion` for continuous recording |

---

## Architecture diagram

```
┌─────────────────────────────────────────────────────────┐
│                      Docker host (LAN)                  │
│                                                         │
│  Tapo C310/C320/C510 ──RTSP──▶ go2rtc ──RTSP──▶ Frigate│
│                                    │              │     │
│                                    │WebRTC        │MQTT │
│                                    ▼              ▼     │
│                               Browser       Mosquitto   │
│                               (live feed)       │       │
│                                    ▲        HA / ntfy   │
│                                    │        (alerts)    │
│                               Dashboard                 │
│                               (port 8080)               │
└─────────────────────────────────────────────────────────┘
```
