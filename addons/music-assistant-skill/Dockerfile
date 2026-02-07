FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /opt/music-assistant

# Install build dependencies required by some Python packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libffi-dev \
       libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the whole repository into the image so the service can import local modules
COPY . /opt/music-assistant

# Install Python dependencies used by the skill web service
RUN pip install --no-cache-dir -r app/requirements.txt

EXPOSE 5000 5678

CMD ["python", "app/app.py"]
