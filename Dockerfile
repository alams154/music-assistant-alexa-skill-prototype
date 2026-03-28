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
COPY app/requirements.txt /app/requirements.txt
RUN python3.10 -m venv venv && \
    . venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install debugpy

# Apply verifier.py patch inside the venv so the container runtime has the fix
RUN /app/venv/bin/python - <<'PY'
import sysconfig, os, sys
try:
        site = sysconfig.get_paths()['purelib']
except Exception:
        print('Could not determine site-packages path; skipping verifier patch')
        sys.exit(0)

verifier_path = os.path.join(site, 'ask_sdk_webservice_support', 'verifier.py')
if not os.path.exists(verifier_path):
        print('verifier.py not found at', verifier_path, '; skipping patch')
        sys.exit(0)

with open(verifier_path, 'r', encoding='utf-8') as f:
        src = f.read()

needle = (
    '        now = datetime.utcnow()\n'
    '        if not (x509_cert.not_valid_before <= now <=\n'
    '                x509_cert.not_valid_after):\n'
    '            raise VerificationException("Signing Certificate expired")'
)
patch = (
    '        from datetime import timezone\n'
    '        now = datetime.now(timezone.utc)\n'
    '        # Use timezone-aware UTC datetimes and updated cryptography properties\n'
    "        not_valid_before = getattr(x509_cert, 'not_valid_before_utc', None) or x509_cert.not_valid_before.replace(tzinfo=timezone.utc)\n"
    "        not_valid_after = getattr(x509_cert, 'not_valid_after_utc', None) or x509_cert.not_valid_after.replace(tzinfo=timezone.utc)\n"
    '        if not (not_valid_before <= now <= not_valid_after):\n'
    '            raise VerificationException("Signing Certificate expired")'
)

if needle in src:
    new_src = src.replace(needle, patch)
    backup = verifier_path + '.orig'
    try:
        if not os.path.exists(backup):
            with open(backup, 'w', encoding='utf-8') as b:
                b.write(src)
        with open(verifier_path, 'w', encoding='utf-8') as f:
            f.write(new_src)
        print('Patched', verifier_path, '(backup at', backup + ')')
    except Exception as e:
        print('Failed to write patch:', e)
else:
    print('No patch needed for verifier.py')
PY

# Apply certvalidator registry.py patch so OS trust-root iteration does not crash
# with asn1crypto >= 1.5.1. certvalidator 0.11.1 (2016) calls
# trust_root.subject.hashable for every OS CA cert; asn1crypto 1.5.1 changed
# NameTypeAndValue internals so that call raises KeyError for certain cert
# structures present in modern CA stores. Wrap the call in try/except so
# incompatible trust roots are skipped rather than aborting every Alexa request.
RUN /app/venv/bin/python - <<'PY'
import sysconfig, os, sys
try:
        site = sysconfig.get_paths()['purelib']
except Exception:
        print('Could not determine site-packages path; skipping registry patch')
        sys.exit(0)

registry_path = os.path.join(site, 'certvalidator', 'registry.py')
if not os.path.exists(registry_path):
        print('registry.py not found at', registry_path, '; skipping patch')
        sys.exit(0)

with open(registry_path, 'r', encoding='utf-8') as f:
        src = f.read()

needle = (
    '        for trust_root in trust_roots:\n'
    '            hashable = trust_root.subject.hashable\n'
    '            if hashable not in self._subject_map:\n'
    '                self._subject_map[hashable] = []\n'
    '            self._subject_map[hashable].append(trust_root)\n'
    '            if trust_root.key_identifier:\n'
    '                self._key_identifier_map[trust_root.key_identifier] = trust_root\n'
    '            self._ca_lookup[trust_root.signature] = True'
)
patch = (
    '        for trust_root in trust_roots:\n'
    '            try:\n'
    '                hashable = trust_root.subject.hashable\n'
    '            except Exception:\n'
    '                # Skip trust roots whose subject cannot be hashed by this\n'
    '                # version of asn1crypto (certvalidator 0.11.1 incompatibility)\n'
    '                continue\n'
    '            if hashable not in self._subject_map:\n'
    '                self._subject_map[hashable] = []\n'
    '            self._subject_map[hashable].append(trust_root)\n'
    '            if trust_root.key_identifier:\n'
    '                self._key_identifier_map[trust_root.key_identifier] = trust_root\n'
    '            self._ca_lookup[trust_root.signature] = True'
)

if needle in src:
    new_src = src.replace(needle, patch)
    backup = registry_path + '.orig'
    try:
        if not os.path.exists(backup):
            with open(backup, 'w', encoding='utf-8') as b:
                b.write(src)
        with open(registry_path, 'w', encoding='utf-8') as f:
            f.write(new_src)
        print('Patched', registry_path, '(backup at', backup + ')')
    except Exception as e:
        print('Failed to write patch:', e)
else:
    print('No patch needed for registry.py (needle not found)')
PY
# Install ASK CLI (v2) globally so container can run `ask configure`
RUN npm install -g ask-cli || true

# Now copy the rest of your source code (commented out for dynamic development)
COPY app /app/src
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

# Timezone (defaults to UTC) — can be overridden at runtime via TZ env
ENV TZ=UTC

# Host configuration:
# MA_HOSTNAME: hostname for the Music Assistant stream
# SKILL_HOSTNAME: hostname used when creating the Alexa skill manifest and endpoints
ENV MA_HOSTNAME=""
ENV SKILL_HOSTNAME=""
ENV PORT=5000
ENV LOCALE=en-US
# When set to 1 (default) we reduce HTTP request log noise (werkzeug/urllib3)
ENV QUIET_HTTP=1

# Debugging Configuration
ARG DEBUG_PORT=0
 # default 0 (disabled); launch.json default 5678
ENV DEBUG_PORT=${DEBUG_PORT}

# Expose the port the app runs on
EXPOSE ${PORT}

# If DEBUG_PORT is empty or set to 0, run without debugpy. Otherwise start debugpy.
CMD ["/bin/sh", "-lc", "if [ -n \"${DEBUG_PORT}\" ] && [ \"${DEBUG_PORT}\" != \"0\" ]; then exec /app/venv/bin/python -m debugpy --listen 0.0.0.0:${DEBUG_PORT} src/app.py; else exec /app/venv/bin/python src/app.py; fi"]