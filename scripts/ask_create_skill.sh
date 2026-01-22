#!/usr/bin/env bash
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
UPLOAD_MODELS=false

usage(){
  cat <<EOF
Usage: $(basename "$0") [--profile NAME] [--endpoint https://host] [--upload-models] [--stage development|live]

Options:
  --profile NAME       ASK CLI profile to use (default: default)
  --endpoint URL       HTTPS endpoint to set for the skill (optional)
  --upload-models      Upload interaction models from the repo's models/ directory after creating the skill
  --stage STAGE        Skill stage to target for interaction model uploads (default: development)
  -h, --help           Show this help
EOF
}

while [[ ${#} -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2;;
    --endpoint) ENDPOINT="$2"; shift 2;;
    --upload-models) UPLOAD_MODELS=true; shift 1;;
    --stage) STAGE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
  esac
done

command -v ask >/dev/null 2>&1 || { echo "ask CLI not found in PATH. Install it first: https://developer.amazon.com/en-US/docs/alexa/smapi/ask-cli.html"; exit 2; }

mkdir -p "$OUT_DIR"
mkdir -p "$TMP_DIR"

# Delete any existing skill(s) named "Music Assistant" for this vendor/profile
LIST_FILE="$TMP_DIR/list_skills.json"
ask smapi list-skills-for-vendor --profile "$PROFILE" > "$LIST_FILE" 2>&1 || true
TO_DELETE=$(python3 - <<PY
import json,sys
f='''$LIST_FILE'''
try:
  data=json.load(open(f))
except Exception:
  print('')
  sys.exit(0)
ids=[]
def walk(obj):
  if isinstance(obj, dict):
    if ('skillId' in obj) and (obj.get('name')=='Music Assistant' or obj.get('skillName')=='Music Assistant'):
      ids.append(obj.get('skillId'))
    for v in obj.values():
      walk(v)
  elif isinstance(obj, list):
    for v in obj:
      walk(v)
walk(data)
print(' '.join([i for i in ids if i]))
PY
)
if [ -n "$TO_DELETE" ]; then
  echo "Found existing Music Assistant skill(s): $TO_DELETE"
  for sid in $TO_DELETE; do
  echo "Deleting existing skill $sid"
  ask smapi delete-skill --skill-id "$sid" --profile "$PROFILE" --debug > "$TMP_DIR/delete_skill_${sid}.txt" 2>&1 || true
  echo "WROTE $TMP_DIR/delete_skill_${sid}.txt"
  done
fi

python3 - <<PY
import json,sys
infile = "$MANIFEST_SRC"
outfile = "$OUT_MANIFEST"
endpoint = "${ENDPOINT}"
with open(infile,'r') as f:
    data = json.load(f)
# Ensure publishingInformation locales en-US exists and set invocation name
pub = data.setdefault('manifest',{}).setdefault('publishingInformation',{})
locales = pub.setdefault('locales',{})
en = locales.setdefault('en-US',{})
en['name'] = 'Music Assistant'
en['examplePhrases'] = ["Alexa, open music assistant", "", ""]
# If endpoint provided, set HTTPS endpoint and certificate type
if endpoint:
    apis = data.setdefault('manifest',{}).setdefault('apis',{})
    custom = apis.setdefault('custom',{})
    custom['endpoint'] = { 'uri': endpoint, 'sslCertificateType': 'Wildcard' }

with open(outfile,'w') as f:
    json.dump(data, f, indent=2)
print('WROTE', outfile)
PY

echo "Creating skill using ASK CLI (profile=$PROFILE)..."
CREATE_OUT_FILE="$TMP_DIR/create_skill_out.txt"
ask smapi create-skill-for-vendor --manifest file://$OUT_MANIFEST --profile $PROFILE > "$CREATE_OUT_FILE" 2>&1 || true
CREATE_OUT="$(cat "$CREATE_OUT_FILE")"
echo "WROTE $CREATE_OUT_FILE"
echo "$CREATE_OUT"

# Try to extract skillId from JSON output
SKILL_ID=""
SKILL_ID=$(python3 - <<PY
import sys,json
try:
    obj = json.loads('''$CREATE_OUT''')
    print(obj.get('skillId',''))
except Exception:
    # fallback: try to find skillId key in text
    import re
    m = re.search(r'amzn1\.ask\.skill\.[0-9a-fA-F\-]+', '''$CREATE_OUT''')
    print(m.group(0) if m else '')
PY
)

if [ -z "$SKILL_ID" ]; then
  echo "Failed to detect skillId. Check the output above for errors." >&2
  exit 3
fi

echo "Created skill: $SKILL_ID"

if [ "$UPLOAD_MODELS" = true ]; then
  echo "Uploading interaction models from models/ for locales (injecting invocationName)..."
  # Ensure a minimal invocation-only interaction model exists for en-US so the invocationName is set
  MIN_INV="$TMP_DIR/invocation_en-US.json"
  python3 - <<PY
import json
dst='''$MIN_INV'''
data={"interactionModel": {"languageModel": {"invocationName": "music assistant", "intents": [{"name": "AMAZON.FallbackIntent"}, {"name": "AMAZON.PauseIntent"}, {"name": "AMAZON.ResumeIntent"}, {"name": "AMAZON.StopIntent"}, {"name": "PlayIntent","samples":["play"]}], "types": []}}}
with open(dst,'w') as f:
    json.dump(data, f, indent=2)
print('WROTE', dst)
PY
  echo "Uploading minimal invocation model for en-US"
  ask smapi set-interaction-model --skill-id "$SKILL_ID" --stage "$STAGE" --locale en-US --interaction-model file://"$MIN_INV" --profile "$PROFILE" > "$TMP_DIR/set_interaction_en-US_min.txt" 2>&1 || true
  echo "WROTE $TMP_DIR/set_interaction_en-US_min.txt"
  for model in "$REPO_ROOT"/models/*.json; do
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

echo "Done. Skill ID: $SKILL_ID"
echo "Next steps:"
echo " - In the developer console set any additional endpoints, intents or testing settings as needed."
echo " - To export the hosted package: ask smapi export-package --skill-id $SKILL_ID --stage $STAGE --profile $PROFILE"
