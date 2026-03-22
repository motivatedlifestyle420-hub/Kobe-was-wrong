# Monolith NVR Stack

Self-hosted AI camera system built with **Frigate**, **go2rtc**, and **Mosquitto**.

Runs on the MONOLITH machine and provides:

* AI object detection (Frigate)
* RTSP restreaming and camera relay (go2rtc)
* Event messaging bus (MQTT / Mosquitto)
* Web dashboards for monitoring and playback

This repository contains the configuration and infrastructure needed to run the stack.

---

## Architecture

Cameras → go2rtc → Frigate → MQTT → Dashboard / Automation

Components:

Frigate
AI object detection and recording engine.

go2rtc
Handles camera streams and restreams them for Frigate and dashboards.

Mosquitto
MQTT broker used for events and automation triggers.

Dashboard
Browser-based camera wall.

---

## Services

| Service    | Purpose                   | Port |
| ---------- | ------------------------- | ---- |
| Frigate    | AI detection + recordings | 5000 |
| go2rtc     | Stream relay              | 1984 |
| Mosquitto  | MQTT broker               | 1883 |
| RTSP relay | Camera streams            | 8554 |

---

## System Requirements

Recommended hardware:

CPU
AMD Ryzen 5700X or equivalent

RAM
16GB recommended

Storage
SSD recommended for video recording

Network
Gigabit LAN

GPU acceleration optional.

---

## Installation

Clone the repository.

```
git clone https://github.com/<username>/<repo>.git
cd <repo>
```

Start the stack.

```
docker compose up -d
```

Check containers.

```
docker compose ps
```

---

## Access Interfaces

Frigate UI

```
http://localhost:5000
```

go2rtc stream manager

```
http://localhost:1984
```

MQTT broker

```
localhost:1883
```

---

## Repository Structure

```
config/
  frigate.yml

dashboard/
  index.html

data/
  recordings
  clips

docker-compose.yml
README.md
```

---

## MQTT Topics

Frigate publishes events to MQTT.

Examples:

```
frigate/events
frigate/<camera>/motion
frigate/<camera>/detect
```

These can be consumed by automation systems.

---

## Maintenance

View logs:

```
docker logs frigate
docker logs go2rtc
docker logs mosquitto
```

Restart stack:

```
docker compose restart
```

Stop stack:

```
docker compose down
```

---

## Security Notes

Do not expose the MQTT broker publicly.
Bind Mosquitto to localhost or restrict via firewall.

Credentials should be stored using environment variables, not hardcoded in configuration.

---

## Future Improvements

Hardware acceleration (GPU / Coral TPU)
Event notification system
Camera wall dashboard
Zone-based detection filters
Automated backup of recordings

---

## License

Private internal project.
