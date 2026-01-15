# Deployment Guide

## Building and Deploying Locally

### Quick Deploy

```bash
chmod +x build-and-deploy.sh
./build-and-deploy.sh
```

### Manual Steps

1. **Build the Docker image:**
   ```bash
   docker compose build
   ```

2. **Stop the existing container:**
   ```bash
   docker compose down
   ```

3. **Start the updated container:**
   ```bash
   docker compose up -d
   ```

4. **View logs:**
   ```bash
   docker compose logs -f music-assistant-skill
   ```

---

## Deployment to Your LXC Container

### Option 1: Copy Files and Build on LXC

1. **Copy the repository to your LXC container:**
   ```bash
   # From your local machine
   scp -r /path/to/music-assistant-alexa-skill-prototype root@<lxc-ip>:/root/
   ```

2. **SSH into your LXC container:**
   ```bash
   ssh root@<lxc-ip>
   cd /root/music-assistant-alexa-skill-prototype
   ```

3. **Copy your existing docker-compose.yml:**
   ```bash
   # Backup the example one
   mv docker-compose.yml docker-compose.example.yml

   # Copy your production config
   cp /root/docker-compose.yml .
   ```

4. **Create docker-compose.override.yml** (already in the repo):
   ```yaml
   services:
     music-assistant-skill:
       build:
         context: .
         dockerfile: Dockerfile
       image: music-assistant-skill:local
   ```

5. **Build and deploy:**
   ```bash
   chmod +x build-and-deploy.sh
   ./build-and-deploy.sh
   ```

### Option 2: Build Locally and Export/Import

1. **Build the image on your local machine:**
   ```bash
   cd /home/user/music-assistant-alexa-skill-prototype
   docker build -t music-assistant-skill:local .
   ```

2. **Export the image:**
   ```bash
   docker save music-assistant-skill:local | gzip > music-assistant-skill-local.tar.gz
   ```

3. **Copy to LXC container:**
   ```bash
   scp music-assistant-skill-local.tar.gz root@<lxc-ip>:/root/
   ```

4. **Import on LXC:**
   ```bash
   ssh root@<lxc-ip>
   docker load < /root/music-assistant-skill-local.tar.gz
   ```

5. **Update docker-compose.yml on LXC:**
   ```yaml
   services:
     music-assistant-skill:
       image: music-assistant-skill:local  # Changed from ghcr.io/alams154/...
       # ... rest of config stays the same
   ```

6. **Restart:**
   ```bash
   cd /root  # Or wherever your docker-compose.yml is
   docker compose down
   docker compose up -d
   ```

---

## Important Configuration Notes

### MA_HOSTNAME Setting

Your MA_HOSTNAME should point to your **HTTPS streaming endpoint**, not the Music Assistant UI:

**✅ Correct:**
```yaml
MA_HOSTNAME=https://ma-stream.jayekub.com
```
Where `ma-stream.jayekub.com`:
- Points to your Nginx Proxy Manager
- Has valid SSL certificate
- Forwards to `192.168.0.5:8098` (Music Assistant internal IP)

**❌ Incorrect:**
```yaml
MA_HOSTNAME=https://music-assistant.jayekub.com  # This is the MA UI, not streaming endpoint
```

### Music Assistant Configuration

In Music Assistant → Settings → Core Modules → Streamserver:
- **Published IP address:** `192.168.0.5` (your MA internal IP)
- **TCP Port:** `8098`

This makes MA generate URLs like: `http://192.168.0.5:8098/flow/...`

The bridge then rewrites them to: `https://ma-stream.jayekub.com/flow/...`

---

## Viewing Debug Logs

After deployment, test your Samsung Family Hub and watch the logs:

```bash
docker compose logs -f music-assistant-skill
```

Look for this sequence:
```
=== PLAY FUNCTION CALLED ===
Device supports APL: False
URL received: http://192.168.0.5:8098/...
=== NON-APL PLAYBACK PATH (Samsung Family Hub) ===
Original URL from Music Assistant: http://192.168.0.5:8098/...
MA_HOSTNAME environment variable (raw): 'https://ma-stream.jayekub.com'
MA_HOSTNAME after sanitization: https://ma-stream.jayekub.com
URL after rewriting: https://ma-stream.jayekub.com/...
URL successfully rewritten from IP to hostname
Validating URL accessibility: https://ma-stream.jayekub.com/...
HEAD request returned status: 200
Sending PlayDirective to Alexa device with final URL: https://ma-stream.jayekub.com/...
URL scheme: HTTPS
```

If playback fails, you'll see:
```
=== PLAYBACK FAILED ===
Error type: MEDIA_ERROR_INTERNAL_DEVICE_ERROR
Error message: ...
```

---

## Troubleshooting

### Issue: "URL was NOT rewritten!"

**Cause:** The URL doesn't start with an IP address pattern

**Solution:**
- Verify MA Published IP is set to `192.168.0.5` (not a hostname)
- Check the URL in logs - it should be `http://192.168.0.5:8098/...`

### Issue: HEAD request fails (404, timeout, etc.)

**Cause:** Nginx proxy not configured correctly

**Solution:**
1. Check Nginx Proxy Manager configuration for `ma-stream.jayekub.com`
2. Verify it forwards to `192.168.0.5:8098`
3. Test manually: `curl -I https://ma-stream.jayekub.com/`

### Issue: Developer console works, Family Hub doesn't

**Cause:** Domain not publicly accessible

**Solution:**
1. Test from outside your network: `curl -v https://ma-stream.jayekub.com/`
2. Verify port 443 is forwarded to Nginx Proxy Manager
3. Verify DNS resolves to your public IP
4. Verify SSL certificate is valid and trusted
