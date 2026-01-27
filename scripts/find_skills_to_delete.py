#!/usr/bin/env python3
import sys,json

if len(sys.argv) < 2:
    print('')
    sys.exit(0)
path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception:
    print('')
    sys.exit(0)
ids = []
for item in data.get('skills', []) if isinstance(data, dict) else []:
    if isinstance(item, dict):
        name = item.get('skillName') or item.get('name') or item.get('skillNameLocal')
        # also check nameByLocale mapping
        if not name and isinstance(item.get('nameByLocale'), dict):
            # prefer en-US if available
            name = item['nameByLocale'].get('en-US') or next(iter(item['nameByLocale'].values()), None)
        sid = item.get('skillId') or item.get('id')
        if sid and name and name.strip().lower() == 'music assistant':
            ids.append(sid)

def walk(obj):
    if isinstance(obj, dict):
        if ('skillId' in obj) and (obj.get('name','').lower()=='music assistant' or obj.get('skillName','').lower()=='music assistant'):
            ids.append(obj.get('skillId'))
        for v in obj.values():
            walk(v)
    elif isinstance(obj, list):
        for v in obj:
            walk(v)
walk(data)
print(' '.join([i for i in ids if i]))
