import os
import re
import json
import subprocess
from pathlib import Path


def get_ask_credentials_dir() -> Path:
    """Resolve ASK credentials directory.

    Preference order:
    1) ASK_CREDENTIALS_DIR environment variable
    2) /root/.ask when mounted in container
    3) ~/.ask
    """
    configured = (os.environ.get('ASK_CREDENTIALS_DIR') or '').strip()
    if configured:
        return Path(configured).expanduser()
    root_ask = Path('/root/.ask')
    if root_ask.exists():
        return root_ask
    return Path.home() / '.ask'


def get_ask_cli_config_path() -> Path:
    return get_ask_credentials_dir() / 'cli_config'


def ask_home_from_credentials_dir() -> str:
    """Return HOME value that maps tools to the resolved credentials dir."""
    cred_dir = get_ask_credentials_dir()
    try:
        return str(cred_dir.parent)
    except Exception:
        return str(Path.home())


def _load_cli_config(path: Path):
    try:
        raw = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    except Exception:
        return None

    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def prepare_cli_config_for_configure(profile: str = 'default') -> tuple[bool, str]:
    """Ensure ASK config dir exists and remove non-functional cli_config.

    ASK CLI can treat a placeholder profile entry as configured, so we avoid
    writing any baseline profile data here.
    """
    cfg_path = get_ask_cli_config_path()
    cfg_dir = cfg_path.parent

    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f'could not create ASK credentials directory: {e}'

    if not cfg_path.exists():
        return True, f'ASK cli_config not found at {cfg_path}; auth will create it'

    if has_functional_cli_config(profile=profile):
        return True, f'ASK cli_config is functional for profile {profile}'

    try:
        cfg_path.unlink()
        return True, f'deleted non-functional ASK cli_config at {cfg_path}'
    except Exception as e:
        return False, f'could not delete non-functional ASK cli_config: {e}'


def has_functional_cli_config(profile: str = 'default') -> bool:
    """Return True when cli_config has usable credentials for the profile."""
    data = _load_cli_config(get_ask_cli_config_path())
    if not data:
        return False

    profiles = data.get('profiles')
    if not isinstance(profiles, dict):
        return False

    entry = profiles.get(profile)
    if not isinstance(entry, dict) or not entry:
        return False

    token = entry.get('token')
    if isinstance(token, dict):
        access_token = str(token.get('access_token') or '').strip()
        refresh_token = str(token.get('refresh_token') or '').strip()
        if access_token or refresh_token:
            return True

    # Fallback for alternate/older formats.
    access_token = str(entry.get('access_token') or '').strip()
    refresh_token = str(entry.get('refresh_token') or '').strip()
    return bool(access_token or refresh_token)


def _parse_json_from_cli_output(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        idx = raw.find('{')
        if idx != -1:
            return json.loads(raw[idx:])
    except Exception:
        pass
    return None


def get_vendors(profile: str = 'default') -> list[dict]:
    """Return vendors available for the ASK profile.

    Each entry has: {'id': '<vendor-id>', 'name': '<display-name>'}
    """
    if not profile:
        profile = 'default'
    if not has_functional_cli_config(profile=profile):
        return []

    try:
        proc = subprocess.run(
            ['ask', 'smapi', 'list-vendors', '--profile', profile],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return []

    raw = (proc.stdout or '').strip()
    if not raw:
        raw = (proc.stderr or '').strip()
    if not raw:
        return []

    obj = _parse_json_from_cli_output(raw)
    if not isinstance(obj, dict):
        return []

    vendors_raw = obj.get('vendors')
    if not isinstance(vendors_raw, list):
        return []

    seen = set()
    vendors = []
    for item in vendors_raw:
        if not isinstance(item, dict):
            continue
        vid = str(item.get('id') or item.get('vendorId') or item.get('vendor_id') or '').strip()
        if not vid or vid in seen:
            continue
        seen.add(vid)
        vname = str(item.get('name') or item.get('vendorName') or item.get('displayName') or vid).strip()
        vendors.append({'id': vid, 'name': vname})
    return vendors


def _active_vendor_path() -> Path:
    return get_ask_credentials_dir() / 'active_vendor.json'


def get_active_vendor(profile: str = 'default') -> str:
    """Return the persisted vendor id for a profile when available."""
    path = _active_vendor_path()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    stored = str(data.get(profile) or '').strip()
    if not stored:
        return ''

    vendors = get_vendors(profile=profile)
    if vendors and any(v.get('id') == stored for v in vendors):
        return stored
    return ''


def save_active_vendor(vendor_id: str, profile: str = 'default') -> None:
    """Persist selected vendor id per ASK profile."""
    path = _active_vendor_path()
    try:
        existing = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    if vendor_id:
        existing[profile] = vendor_id
    else:
        existing.pop(profile, None)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    except Exception:
        pass

def sanitize_log(s: str) -> str:
    try:
        if not isinstance(s, str):
            s = str(s)
    except Exception:
        s = ''
    s = s.replace('\\u001b', '')
    s = s.replace('\r', '')
    try:
        s = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', s)
    except Exception:
        pass
    if 'authorization code' in s.lower():
        s = re.sub(r'(?i)(authorization code[:]?\s*).*', r"\1<REDACTED-AUTH-CODE>", s)
    return s


def enqueue_setup_log(logs, line: str):
    try:
        logs.append(sanitize_log(line))
    except Exception:
        try:
            logs.append(str(line))
        except Exception:
            pass


def setup_reader_thread(proc, enqueue_func, prefix=None):
    try:
        for line in proc.stdout:
            if not line:
                continue
            text = line.rstrip('\n')
            if prefix:
                text = f'[{prefix}] {text}'
            enqueue_func(text)
    except Exception as e:
        enqueue_func(f"[reader error] {e}")


def read_master_loop(master_fd, enqueue_func, prefix=None):
    try:
        buf = b''
        while True:
            try:
                chunk = os.read(master_fd, 1024)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                text = line.decode('utf-8', errors='replace')
                if prefix:
                    text = f'[{prefix}] {text}'
                enqueue_func(text)
            try:
                s = chunk.decode('utf-8', errors='replace')
                for m in re.findall(r"https?://[^\s'\"]+", s):
                    txt = m
                    if prefix:
                        txt = f'[{prefix}] {txt}'
                    enqueue_func(txt)
            except Exception:
                pass
        if buf:
            text = buf.decode('utf-8', errors='replace')
            if text.strip():
                if prefix:
                    text = f'[{prefix}] {text}'
                enqueue_func(text)
    except Exception as e:
        enqueue_func(f"[pty reader error] {e}")
