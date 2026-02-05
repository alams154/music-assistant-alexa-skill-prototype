#!/usr/bin/env bash
# ./scripts/ask_create_skill.sh --profile default --endpoint https://test.app --upload-models > ./tmp/ask_create_with_complete_invocation.txt 2>&1 || tru
set -euo pipefail

# Create an Alexa skill using ASK CLI based on the README instructions
# - adjusts the `en-US` locale invocation name to "Music Assistant"
# - optionally sets the HTTPS endpoint
# - optionally uploads interaction models from `models/`

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_SRC="$REPO_ROOT/app/skill.json"
OUT_DIR="$REPO_ROOT/build"
OUT_MANIFEST="$OUT_DIR/skill-create.json"
TMP_DIR="$REPO_ROOT/tmp"

PROFILE="default"
STAGE="development"
ENDPOINT=""
UPLOAD_MODELS=true
# Default to en-US to avoid uploading/managing all locales by default
LOCALE="en-US"

usage(){
  cat <<EOF
Usage: $(basename "$0") [--profile NAME] [--endpoint https://host] [--upload-models] [--stage development|live] [--locale LOCALE]

Options:
  --profile NAME       ASK CLI profile to use (default: default)
  --endpoint URL       HTTPS endpoint to set for the skill (optional)
  --upload-models      Upload interaction models from the repo's models/ directory after creating the skill
  --stage STAGE        Skill stage to target for interaction model uploads (default: development)
  --locale LOCALE      Locale to include in the manifest and upload (default: en-US)
  -h, --help           Show this help
EOF
}

while [[ ${#} -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2;;
    --endpoint) ENDPOINT="$2"; shift 2;;
    --upload-models) UPLOAD_MODELS=true; shift 1;;
    --stage) STAGE="$2"; shift 2;;
    --locale) LOCALE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
  esac
done

# Require endpoint: user requested endpoint must be provided to publish a valid manifest
if [ -z "${ENDPOINT:-}" ]; then
  echo "Error: --endpoint is required. Provide --endpoint https://your-host or a Lambda ARN." >&2
  usage
  exit 1
fi

command -v ask >/dev/null 2>&1 || { echo "ask CLI not found in PATH. Install it first: https://developer.amazon.com/en-US/docs/alexa/smapi/ask-cli.html"; exit 2; }

# If the container has a mounted persistent credentials dir at /root/.ask, use it.
# This avoids requiring a user-configurable env var; the Docker Compose named
# volume `ask_data` is mounted to /root/.ask by the service configuration.
if [ -d "/root/.ask" ]; then
  export HOME="/root"
  echo "Using persistent ASK credentials at /root/.ask (HOME=${HOME})"
fi

mkdir -p "$OUT_DIR"
mkdir -p "$TMP_DIR"

# Query existing skill(s) named "Music Assistant" for this vendor/profile
LIST_FILE="$TMP_DIR/list_skills.json"
ask smapi list-skills-for-vendor --profile "$PROFILE" > "$LIST_FILE" 2>&1 || true
TO_DELETE=$(python3 "$REPO_ROOT/scripts/find_skills_to_delete.py" "$LIST_FILE" 2>/dev/null || true)

# Default: we will create a new skill unless we find and reuse an existing one
SKIP_CREATE=0
SKILL_ID=""
if [ -n "$TO_DELETE" ]; then
  echo "Found existing Music Assistant skill(s): $TO_DELETE"
  # Convert to array
  read -r -a existing_arr <<< "$TO_DELETE"
  # If more than one exists, delete extras (keep the first entry)
  if [ ${#existing_arr[@]} -gt 1 ]; then
    echo "Multiple existing Music Assistant skills found; deleting extras and keeping first: ${existing_arr[0]}"
    for ((i=1;i<${#existing_arr[@]};i++)); do
      sid=${existing_arr[i]}
      echo "Deleting extra existing skill $sid"
      ask smapi delete-skill --skill-id "$sid" --profile "$PROFILE" --debug > "$TMP_DIR/delete_skill_${sid}.txt" 2>&1 || true
      echo "WROTE $TMP_DIR/delete_skill_${sid}.txt"
    done
  fi
  # Reuse the remaining existing skill instead of creating a new one
  SKILL_ID=${existing_arr[0]}
  echo "Reusing existing skill: $SKILL_ID"
  SKIP_CREATE=1
fi

if ! python3 "$REPO_ROOT/scripts/build_skill_manifest.py" "$MANIFEST_SRC" "$OUT_MANIFEST" "${ENDPOINT}" "${LOCALE}"; then
  echo "Failed to build manifest (see error above). Pass --endpoint or add a valid endpoint.uri to $MANIFEST_SRC." >&2
  exit 4
fi
echo "WROTE $OUT_MANIFEST"

# Create a new skill only if we didn't find an existing one to reuse
if [ "$SKIP_CREATE" -eq 0 ]; then
  echo "Creating skill using ASK CLI (profile=$PROFILE)..."
  CREATE_OUT_FILE="$TMP_DIR/create_skill_out.txt"
  ask smapi create-skill-for-vendor --manifest file://$OUT_MANIFEST --profile $PROFILE > "$CREATE_OUT_FILE" 2>&1 || true
  CREATE_OUT="$(cat "$CREATE_OUT_FILE")"
  echo "WROTE $CREATE_OUT_FILE"
  echo "$CREATE_OUT"

  # Try to extract skillId from JSON output
  SKILL_ID=""
  SKILL_ID=$(python3 - <<PY
import sys,json,re
try:
    obj = json.loads('''$CREATE_OUT''')
    print(obj.get('skillId',''))
except Exception:
    m = re.search(r'amzn1\.ask\.skill\.[0-9a-fA-F\-]+', '''$CREATE_OUT''')
    print(m.group(0) if m else '')
PY
)

  if [ -z "$SKILL_ID" ]; then
    echo "Failed to detect skillId. Check the output above for errors." >&2
    exit 3
  fi

  echo "Created skill: $SKILL_ID"
else
  # We are reusing an existing skill; update its manifest to match the desired manifest
  echo "Updating manifest for existing skill: $SKILL_ID"
  UPDATE_OUT_FILE="$TMP_DIR/update_manifest_${SKILL_ID}.txt"
  ask smapi update-skill-manifest --skill-id "$SKILL_ID" --manifest file://$OUT_MANIFEST --profile $PROFILE > "$UPDATE_OUT_FILE" 2>&1 || true
  echo "WROTE $UPDATE_OUT_FILE"
  echo "Rebuilt existing skill: $SKILL_ID"
fi

# Note: enablement must happen after interaction models are uploaded and built.
# We'll poll model build status (if we uploaded models) and then attempt enablement.

if [ "$UPLOAD_MODELS" = true ]; then
  echo "Uploading interaction models from models/ for locales (injecting invocationName)..."
  # Determine which locale to upload; default to en-US when not specified
  INV_LOCALE="${LOCALE:-en-US}"
  # Ensure a minimal invocation-only interaction model exists for the target locale so the invocationName is set
  MIN_INV="$TMP_DIR/invocation_${INV_LOCALE}.json"
  python3 - <<PY
import json
dst='''$MIN_INV'''
data = {
  "interactionModel": {
    "languageModel": {
      "invocationName": "music assistant",
      "intents": [
        {"name": "AMAZON.FallbackIntent"},
        {"name": "AMAZON.PauseIntent"},
        {"name": "AMAZON.ResumeIntent"},
        {"name": "AMAZON.StopIntent"},
        {"name": "PlayIntent", "samples": ["play"]}
      ],
      "types": []
    }
  }
}
with open(dst, 'w') as f:
  json.dump(data, f, indent=2)
print('WROTE', dst)
PY
  echo "Uploading minimal invocation model for $INV_LOCALE"
  ask smapi set-interaction-model --skill-id "$SKILL_ID" --stage "$STAGE" --locale "$INV_LOCALE" --interaction-model file://"$MIN_INV" --profile "$PROFILE" > "$TMP_DIR/set_interaction_${INV_LOCALE}_min.txt" 2>&1 || true
  echo "WROTE $TMP_DIR/set_interaction_${INV_LOCALE}_min.txt"

  # Build list of locales to upload: single `$LOCALE` if provided, else all models
  if [ -n "$LOCALE" ]; then
    model_list=("$REPO_ROOT/app/models/${LOCALE}.json")
  else
    model_list=("$REPO_ROOT"/app/models/*.json)
  fi
  for model in "${model_list[@]}"; do
    [ -f "$model" ] || continue
    # derive locale from filename (models/en-US.json -> en-US)
    locale=$(basename "$model" .json)
    echo "Preparing $model -> locale $locale"
    MOD_MODEL="$TMP_DIR/modified_model_${locale}.json"
    python3 - <<PY
import json,sys
src='''$model'''
dst='''$MOD_MODEL'''
try:
    with open(src,'r') as f:
        data = json.load(f)
except Exception as e:
    print('ERROR_LOADING', src, e)
    sys.exit(0)
im = data.setdefault('interactionModel', {})
lm = im.setdefault('languageModel', {})
# set invocationName to desired phrase
lm['invocationName'] = 'music assistant'
with open(dst,'w') as f:
    json.dump(data, f, indent=2)
print('WROTE', dst)
PY
    echo "Uploading $MOD_MODEL -> locale $locale"
    ask smapi set-interaction-model --skill-id "$SKILL_ID" --stage "$STAGE" --locale "$locale" --interaction-model file://"$MOD_MODEL" --profile "$PROFILE" > "$TMP_DIR/set_interaction_${locale}.txt" 2>&1 || true
    echo "WROTE $TMP_DIR/set_interaction_${locale}.txt"
  done
fi

# If we uploaded models, poll until model builds are reported as SUCCEEDED,
# then attempt to enable the skill for testing. If --upload-models wasn't used
# we skip automatic enablement (it requires models to be built first).
if [ "$UPLOAD_MODELS" = true ]; then
    echo "Waiting for interaction model builds to complete (polling skill status)..."
    # Cap total polling time to roughly 60s: MAX_RETRIES * SLEEP_SECONDS <= 60
    # Poll every 5s so builds are detected within ~5s of completion
    MAX_RETRIES=12
    SLEEP_SECONDS=5
    # Only poll for the locale(s) we will upload; LOCALE defaults to en-US.
    if [ -n "$LOCALE" ]; then
      LOCALES="$LOCALE"
    else
      LOCALES=""
      for model in "$REPO_ROOT"/app/models/*.json; do
        [ -f "$model" ] || continue
        LOCALES="$LOCALES $(basename "$model" .json)"
      done
    fi

  for locale in $LOCALES; do
    echo -n "Waiting for model build for $locale"
    attempts=0
    success=0
    while [ $attempts -lt $MAX_RETRIES ]; do
            STATUS_JSON=$(ask smapi get-skill-status --skill-id "$SKILL_ID" --resource interactionModel --profile "$PROFILE" 2>/dev/null || true)
            # Immediate quick check: if raw JSON contains a status SUCCEEDED anywhere, accept it
            if printf '%s' "$STATUS_JSON" | grep -q '"status"[[:space:]]*:[[:space:]]*"SUCCEEDED"'; then
              cur_status="SUCCEEDED"
            fi
            # Try jq if available to read lastUpdateRequest.status (only if we don't already have cur_status)
            if [ -z "${cur_status:-}" ]; then
              if command -v jq >/dev/null 2>&1; then
                cur_status=$(printf '%s' "$STATUS_JSON" | jq -r --arg loc "$locale" '.interactionModel[$loc].lastUpdateRequest.status // ""' 2>/dev/null || echo "")
              else
              cur_status=$(printf '%s' "$STATUS_JSON" | python3 - "$locale" <<'PY'
import sys,json
try:
  loc=sys.argv[1]
  obj=json.load(sys.stdin)
  print(obj.get('interactionModel', {}).get(loc, {}).get('lastUpdateRequest', {}).get('status',''))
except Exception:
  print('')
PY
)
              fi
            fi
            # If we still don't have a status, try a more robust inspection (check buildDetails.steps)
            if [ -z "$cur_status" ]; then
              cur_status=$(printf '%s' "$STATUS_JSON" | python3 - "$locale" <<'PY'
import sys,json
loc=sys.argv[1]
try:
  obj=json.load(sys.stdin)
  lm=obj.get('interactionModel', {}).get(loc, {})
  lr=lm.get('lastUpdateRequest', {})
  status=lr.get('status')
  if status:
    print(status)
  else:
    bd=lr.get('buildDetails', {})
    steps=bd.get('steps', [])
    if steps and all(s.get('status')=='SUCCEEDED' for s in steps):
      print('SUCCEEDED')
    else:
      print('')
except Exception:
  print('')
PY
)
            fi
          if [ "$cur_status" = "SUCCEEDED" ]; then
            echo " - build SUCCEEDED"
            success=1
            break
          fi
          attempts=$((attempts+1))
          echo -n "."
          sleep $SLEEP_SECONDS
        done
        if [ $success -eq 0 ]; then
          echo " - WARNING: model build for $locale did not reach SUCCEEDED after $((MAX_RETRIES*SLEEP_SECONDS))s"
          # Dump last get-skill-status JSON to TMP_DIR for debugging in containers
          STATUS_DUMP="$TMP_DIR/get_skill_status_${SKILL_ID}_${locale}.json"
          printf '%s' "$STATUS_JSON" > "$STATUS_DUMP" 2>/dev/null || true
          echo "WROTE $STATUS_DUMP"
        fi
      done
      # Additional fallback: if the STATUS_JSON contains a top-level "status": "SUCCEEDED"
      # somewhere (some ASK CLI outputs differ), treat as SUCCEEDED.
      if [ $success -eq 0 ]; then
        if printf '%s' "$STATUS_JSON" | grep -q '"status"[[:space:]]*:[[:space:]]*"SUCCEEDED"'; then
          echo " - build SUCCEEDED (fallback via grep)"
          success=1
        fi
      fi

  # Now attempt enablement (best-effort). Store outputs in tmp/.
  ENABLE_OUT="$TMP_DIR/enable_testing_${SKILL_ID}.txt"
  echo "Attempting to enable testing for skill $SKILL_ID (outputs -> ${ENABLE_OUT} and ${ENABLE_OUT}.verify)"
  ask smapi set-skill-enablement --skill-id "$SKILL_ID" --stage "$STAGE" --profile "$PROFILE" > "$ENABLE_OUT" 2>&1 || true
  echo "WROTE $ENABLE_OUT"

  VERIFY_OUT="${ENABLE_OUT}.verify"
  ask smapi get-skill-enablement-status --skill-id "$SKILL_ID" --stage "$STAGE" --profile "$PROFILE" > "$VERIFY_OUT" 2>&1 || true
  echo "WROTE $VERIFY_OUT"

  # Fallback for older/other CLIs (non-fatal)
  FALLBACK_OUT="${ENABLE_OUT}.fallback"
  ask smapi update-skill-testing --skill-id "$SKILL_ID" --profile "$PROFILE" > "$FALLBACK_OUT" 2>&1 || true
  if [ -s "$FALLBACK_OUT" ]; then
    echo "WROTE $FALLBACK_OUT"
  fi
else
  echo "Skipping automatic enablement because --upload-models was not used. Upload models and re-run enablement when models are built."
fi

echo "Done. Skill ID: $SKILL_ID"
echo "Next steps:"
echo " - In the developer console set any additional endpoints, intents or testing settings as needed."
echo " - To export the hosted package: ask smapi export-package --skill-id $SKILL_ID --stage $STAGE --profile $PROFILE"
