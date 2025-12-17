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

EXPOSE 5000
EXPOSE 5678

ENV AWS_DEFAULT_REGION=us-east-1
ENV SKILL_ID=""

# API / Music Assistant configuration (set these when running the container)
# Examples:
#  docker run -e API_HOSTNAME=api.example.com ...
ENV API_HOSTNAME=""
ENV MA_HOSTNAME=""
ENV API_USERNAME=""
ENV API_PASSWORD=""

CMD ["/app/venv/bin/python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "src/app.py"]
# docker run -it   -v $(pwd)/app/lambda/py:/app/src   -p 5000:5000   -p 5678:5678   alexa-skill