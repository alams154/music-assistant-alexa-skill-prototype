#!/usr/bin/env python3
import sys,json,os

if len(sys.argv) < 3:
    print('usage: build_skill_manifest.py <infile> <outfile> [endpoint] [locale]')
    sys.exit(2)

infile = sys.argv[1]
outfile = sys.argv[2]
endpoint = sys.argv[3] if len(sys.argv) > 3 else ''
target_locale = sys.argv[4] if len(sys.argv) > 4 else ''

with open(infile,'r') as f:
    data = json.load(f)

pub = data.setdefault('manifest',{}).setdefault('publishingInformation',{})
locales = pub.setdefault('locales',{})

# If a target locale is specified, ensure only that locale is present in the
# publishing information. Otherwise default to en-US as before.
if target_locale:
    # ensure target locale exists and only include it
    loc = locales.setdefault(target_locale, {})
    target = target_locale
else:
    loc = locales.setdefault('en-US', {})
    target = 'en-US'

loc['name'] = 'Music Assistant'
loc['examplePhrases'] = ["Alexa, open music assistant", "Alexa, ask music assistant to play", "Alexa, play music assistant"]

if target_locale:
    # keep only the requested locale in the locales map
    pub['locales'] = { target: locales[target] }
    locales = pub['locales']

# Normalize icons: ensure all locales use the same small/large icon URIs as the target locale
target_small = loc.get('smallIconUri')
target_large = loc.get('largeIconUri')
if target_small or target_large:
    for loc_key, loc_val in locales.items():
        if not isinstance(loc_val, dict):
            continue
        if target_small:
            loc_val['smallIconUri'] = target_small
        if target_large:
            loc_val['largeIconUri'] = target_large

apis = data.setdefault('manifest',{}).setdefault('apis', {})
custom = apis.setdefault('custom', {})
if endpoint:
    custom['endpoint'] = { 'uri': endpoint, 'sslCertificateType': 'Wildcard' }
else:
    ep = custom.get('endpoint') if isinstance(custom.get('endpoint'), dict) else None
    if ep and 'uri' in ep and ep.get('uri'):
        ep.pop('sourceDir', None)
    else:
        # No usable endpoint found; the SMAPI manifest requires a valid endpoint URI (HTTPS or Lambda ARN).
        print('ERROR: No endpoint URI found in manifest. Provide --endpoint <https://...> or ensure manifest has an endpoint.uri', file=sys.stderr)
        sys.exit(4)

# Ensure APL interface is enabled alongside any existing interfaces
ifs = custom.setdefault('interfaces', [])
if isinstance(ifs, list):
    has_apl = any(isinstance(i, dict) and i.get('type') == 'ALEXA_PRESENTATION_APL' for i in ifs)
    if not has_apl:
        ifs.append({'type': 'ALEXA_PRESENTATION_APL'})

with open(outfile,'w') as f:
    json.dump(data, f, indent=2)
print('WROTE', outfile)

