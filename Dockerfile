FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install Python and system dependencies
RUN apt-get update && \
    apt-get install -y python3.10 python3.10-venv python3-pip libssl-dev && \
    apt-get clean

WORKDIR /app

# Copy only requirements first, then install dependencies
COPY app/lambda/py/requirements.txt /app/requirements.txt
RUN python3.10 -m venv venv && \
    . venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install debugpy

# Now copy the rest of your source code (commented out for dynamic development)
COPY app/lambda/py /app/src

ENV AWS_DEFAULT_REGION=us-east-1
ENV SKILL_ID=""

# API / Music Assistant configuration
ENV MA_HOSTNAME=""
ENV API_USERNAME=""
ENV API_PASSWORD=""
ENV PORT=5000
ENV DEBUG_PORT=5678

# Expose the port the app runs on
EXPOSE ${PORT}
EXPOSE ${DEBUG_PORT}

CMD ["/bin/sh", "-lc", "/app/venv/bin/python -m debugpy --listen 0.0.0.0:${DEBUG_PORT} src/app.py"]