# Music Assistant Alexa Skill — Docker Setup Guide

> **Note:** This guide covers the standard Docker setup including Cloudflare Tunnel support for CGNAT/Starlink users. Echo Show 5 (Gen 3) audio playback is supported out of the box.

---

## What This Project Does

This skill enables **Music Assistant → Amazon Echo** streaming. When you press Play in the Music Assistant UI and select an Echo device as the player, the stream is pushed to the skill and played on your Echo.

### Key Features

| Feature | Status |
|---|---|
| Echo Dot / Echo Pop audio playback | ✅ Supported |
| Echo Show 5 (Gen 3) audio playback | ✅ Supported (Issue #57 fixed) |
| CGNAT / Starlink / Double-NAT support | ✅ Via Cloudflare Tunnel |
| URL rewriting (internal → public) | ✅ Built-in |
| Shared store (MA ↔ Alexa state) | ✅ Built-in |

---

## Prerequisites

- **Music Assistant** running and reachable on your local network
- **Docker & Docker Compose** installed
- **Cloudflare Tunnel** (for CGNAT users) OR a **public IP with port forwarding**
- **Alexa Developer Account** (for ASK CLI skill creation)
- **Amazon Echo** device

---

## Quick Start

### 1. Clone & Prepare

```bash
git clone https://github.com/alams154/music-assistant-alexa-skill-prototype.git
cd music-assistant-alexa-skill-prototype

# Create secrets directory and files
mkdir -p secrets
echo "admin" > secrets/app_username.txt
echo "YOUR_STRONG_PASSWORD" > secrets/app_password.txt  # Use https://www.random.org/passwords/ to generate one
```

### 2. Configure Docker Compose

**For CGNAT / Starlink / no public IP users:**

Copy `docker-compose.cloudflared.yml` to `docker-compose.yml` and edit the placeholders!

**For users with a public IP and port forwarding:**

The original `docker-compose.yml` from the repository works without modifications. You do not need Cloudflare Tunnel — configure your router to forward port 443 to the skill container and set `SKIP_URL_VALIDATION=false` (or omit it).

### 3. Start the Stack

```bash
docker compose up -d
```

### 4. Configure the Alexa Skill

1. Open `https://<YOUR_SKILL_DOMAIN>/setup` or `http://<YOUR_INTERNAL_IP>/setup`
2. Enter username and password if asked
3. Complete ASK CLI authentication (Amazon login + OTP)
4. The skill is created automatically
5. In the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask), verify the endpoint matches your `SKILL_HOSTNAME`

### 5. Configure Music Assistant

In Music Assistant:
- **Settings → Player Providers → Alexa**
- **API URL:** `http://<SKILL_LOCAL_IP>:5000` (your skill container's local IP)
- **Auth:** `admin` + your password
- **Amazon Account:** Connect your Amazon account

---

## Why `SKIP_URL_VALIDATION=true`?

When your server is behind **CGNAT** (Starlink, mobile ISP, etc.), the container cannot reach its own public URL via the internet (no hairpin NAT). The skill would fail URL validation with:

> *"Sorry, I can't reach the audio file."*

`SKIP_URL_VALIDATION=true` bypasses the internal HEAD/GET check. The URL is still rewritten to HTTPS and validated by Alexa's servers externally.

---

## Why `extra_hosts`?

The container must resolve your public domains (`mass-stream.yourdomain.com`) to your **local** Music Assistant instance. Without this, the container tries to reach the public internet and fails behind CGNAT.

---

## Echo Show 5 (Gen 3) — Known Behavior

| Feature | Status |
|---|---|
| Audio playback | ✅ Working |
| Blue listening bar after stop | ✅ Fixed |
| APL Cover + Title display | ⚠️ Partial — displays on first play, may show "Music Assistant: Now Playing" on subsequent tracks |
| APL timeline/scrubber | ⚠️ Shows 0:00 (expected for live streams) |

The Echo Show 5 Gen 3 uses APL (Alexa Presentation Language) for its display. Audio playback is stable; the rich metadata display is a secondary enhancement for a future update.

**Workaround:** Say *"Alexa, stop"* then *"Alexa, play Music Assistant"* to refresh the display.

---

## Troubleshooting

### "I can't reach the audio file"
- Check `MA_HOSTNAME` starts with `https://` (not `http://`)
- Verify `extra_hosts` points to the correct local IP
- Ensure `SKIP_URL_VALIDATION=true` for CGNAT

### "No metadata / empty title"
- Check `/status` endpoint — both `/ma/latest-url` and `/alexa/latest-url` should show data
- Verify Music Assistant's Alexa Provider is pushing to `http://<SKILL_LOCAL_IP>:5000`

### Echo Show shows blue bar after stop
- Ensure you're using the latest image: `docker compose pull && docker compose up -d`
- Restart the container: `docker restart ma_alexa_api`

### Skill not found / 404
- Run setup again: `https://<YOUR_SKILL_DOMAIN>/setup`
- Check `ask_data` volume has valid ASK credentials

---

## Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Amazon Echo │────▶│ Cloudflare      │────▶│  Skill Container│
│  (Alexa)     │     │  Tunnel         │     │  (Docker)       │
└─────────────┘     └─────────────────┘     │  Port 5000      │
                                            └────────┬────────┘
                                                     │
                                            ┌────────▼────────┐
                                            │  Music Assistant│
                                            │  (local:8095)   │
                                            └─────────────────┘
```

1. **MA** pushes stream URL + metadata to skill container (`/ma/push-url`)
2. **Skill** rewrites internal URL to public domain, stores in shared state
3. **Alexa** requests stream → Cloudflare Tunnel → Skill → returns public HTTPS URL
4. **Echo** plays the stream directly from `mass-stream.yourdomain.com`

---

## Contributing

If you have improvements for the APL display or other Echo Show models, PRs are welcome!

---

## License

Same as the original project — see repository LICENSE.
