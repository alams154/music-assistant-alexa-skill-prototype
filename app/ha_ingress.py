"""Browser paths for pages opened through Home Assistant ingress."""

INGRESS_PREFIX = "/api/hassio_ingress/"


def ingress_prefix(header_value):
    """Return the ingress path prefix when the header is from Home Assistant."""
    value = (header_value or "").strip()
    if not value.startswith(INGRESS_PREFIX):
        return ""
    return value.rstrip("/")


def browser_path(header_value, path):
    """Prefix an app path so a browser inside ingress stays on the add-on."""
    if not path.startswith("/"):
        path = "/" + path
    prefix = ingress_prefix(header_value)
    if prefix:
        return f"{prefix}{path}"
    return path
