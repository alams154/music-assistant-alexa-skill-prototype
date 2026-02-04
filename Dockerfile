FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install Python and system dependencies
RUN apt-get update && \
    apt-get install -y python3.10 python3.10-venv python3-pip libssl-dev curl gnupg ca-certificates && \
    # Install Node.js 18 from NodeSource (ASK CLI requires a modern Node version)
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first, then install dependencies
COPY app/lambda/py/requirements.txt /app/requirements.txt
RUN python3.10 -m venv venv && \
    . venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install debugpy

# Install ASK CLI (v2) globally so container can run `ask configure`
RUN npm install -g ask-cli || true

# Now copy the rest of your source code (commented out for dynamic development)
COPY app/lambda/py /app/src
# Copy the skill manifest and related app files so runtime can find app/skill.json
# This ensures /app/app/skill.json exists inside the container for the create script.
COPY app /app/app
# Copy repository-level assets (icons, images) into the container so favicons are available
COPY assets /app/assets
# Copy top-level helper scripts so runtime can execute them (ask_create_skill.sh)
COPY scripts /app/scripts
RUN chmod +x /app/scripts/ask_create_skill.sh || true

# Amazon Skill & Host Configuration
ENV AWS_DEFAULT_REGION=us-east-1

# Host configuration:
# MA_HOSTNAME: hostname for the Music Assistant stream
# SKILL_HOSTNAME: hostname used when creating the Alexa skill manifest and endpoints
ENV MA_HOSTNAME=""
ENV SKILL_HOSTNAME=""
ENV PORT=5000

# Debugging Configuration
ARG DEBUG_PORT=0
 # default 0 (disabled); launch.json default 5678
ENV DEBUG_PORT=${DEBUG_PORT}

# Expose the port the app runs on
EXPOSE ${PORT}
EXPOSE ${DEBUG_PORT}

# If DEBUG_PORT is empty or set to 0, run without debugpy. Otherwise start debugpy.
CMD ["/bin/sh", "-lc", "if [ -n \"${DEBUG_PORT}\" ] && [ \"${DEBUG_PORT}\" != \"0\" ]; then exec /app/venv/bin/python -m debugpy --listen 0.0.0.0:${DEBUG_PORT} src/app.py; else exec /app/venv/bin/python src/app.py; fi"]