import os

def get_env_secret(name: str):
    """Return the environment variable value or, if it points to an existing
    file, return the file contents trimmed.

    This allows Docker secrets passed as `/run/secrets/NAME` to work when the
    compose file sets the env var to the secret file path.
    """
    val = os.environ.get(name)
    if not val:
        return None
    try:
        if os.path.exists(val) and os.path.isfile(val):
            with open(val, 'r') as fh:
                return fh.read().strip()
    except Exception:
        # Fall back to returning the raw env value on any error
        return val
    return val
