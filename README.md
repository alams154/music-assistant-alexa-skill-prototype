# Music Assistant Alexa Skill Prototype
This project is an Alexa skill prototype for controlling the Music Assistant server. It provides a Flask-based web service, Alexa skill handler, and API, with support for Docker deployment.

## How to Run

### 1. Using Docker (Recommended)

The easiest way to run the project is with Docker Compose. This will build and start the Alexa skill container with all required environment variables and secrets.

#### Steps:

1. **Copy the docker-compose.yml** and ensure Docker and Docker Compose are installed
2. **Set up secrets (if needed):**
	- Place your API username in `./secrets/api_username.txt` (Relative to your docker-compose.yml file)
	- Place your API password in `./secrets/api_password.txt` (Relative to your docker-compose.yml file)
3. **Edit environment variables** in `docker-compose.yml` as needed (e.g., `MA_HOSTNAME`, `PORT`)
4. **Start the service:**

	```sh
	docker compose up -d
	```

5. The service will be available at `http://localhost:5000` (or the port you set)
6. Setup a reverse proxy for the Alexa skill endpoint (port 443 required)
7. Create a skill in the Alexa Developer Console pointing to your public HTTPS endpoint
    -   Click Create Skill and give it a name
    -   Choose your default language
    -   Select Music & Audio as the experience, Custom as the model, and "Provision your own" as the hosting service
    -   Choose "Start from Scratch"
	-   Go to the Build tab in the Alexa Developer Console
    -   Click the Invocation Name field and type in "music assistant" and hit save
    -   Click the Endpoint field and change it to https
    -   Fill the Default Region with https://<your api host> and click save
    -   On the left Side goto Interaction Model > Intents
    -   Add an Intent named PlayAudio with the Sampe Utterances "play audio" "start" and "play"
    -   Now Click Build Skill and Activate it in your Alexa App
	

## Basic Troubleshooting

### API Endpoints

Returns 401 Unauthorized when the authentication environment variables are provided and the requests does not provide  correct credentials.

#### POST `/ma/push-url`

**Body:**

```json
{
  "album": null,
  "artist": null,
  "imageUrl": "https://github.com/music-assistant/server/blob/dev/music_assistant/logo.png",
  "streamUrl": "https://example.com/stream.mp3",
  "title": "Music Assistant"
}
```

**Response:**

```json
{ "status": "ok" }
```

#### GET `/ma/latest-url`

**Response:**

```json
{
  "album": null,
  "artist": null,
  "imageUrl": "https://github.com/music-assistant/server/blob/dev/music_assistant/logo.png",
  "streamUrl": "https://example.com/stream.mp3",
  "title": "Music Assistant"
}
```
Returns `404` if no URL has been received yet:
```json
{
  "error": "No URL available, please check if Music Assistant has pushed a URL to the API"
}
```

### Status Page
`/status`

Returns a simple status page API return code and checked endpoint


---

See [COMPATIBILITY.md](COMPATIBILITY.md) for known supported devices, languages, and regions.

See [LIMITATIONS.md](LIMITATIONS.md) for known limitations.

See [TODO.md](TODO.md) for future improvements

