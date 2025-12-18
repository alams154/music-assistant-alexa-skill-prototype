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
6. Setup a reverse proxy for the Alexa skill endpoint
7. Create a skill in the Alexa Developer Console pointing to your public HTTPS endpoint

---

See [LIMITATIONS.md](LIMITATIONS.md) for known limitations and future improvements.