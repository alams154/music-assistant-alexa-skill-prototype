"""Bridge Alexa skill and Echo audio through the Nabu Casa remote UI.

Both the skill POST endpoint and the stream proxy live under one
*.ui.nabu.casa API prefix. Home Assistant forwards skill requests to the
add-on and stream requests to Music Assistant port 8097.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote, urlparse

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import ADDON_PORT, DOMAIN, MA_STREAM_PORT, REGISTER_PATH, SKILL_PATH, STREAM_PATH

_LOGGER = logging.getLogger(__name__)

_HOP_BY_HOP = {
    "connection",
    "content-encoding",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_FORWARD_REQUEST_HEADERS = ("range", "if-range", "accept")

_DATA_ADDON_URL = "addon_base_url"
_DATA_MA_BASE = "ma_stream_base"
_DATA_MA_CHECKED = "ma_stream_checked"
_DATA_VIEW = "view_registered"
_MA_CACHE_SECONDS = 60


def _valid_addon_url(url: str) -> bool:
    """Accept only the add-on's internal HTTP address."""
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.username or parsed.password:
        return False
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return False
    if parsed.port != ADDON_PORT:
        return False
    host = parsed.hostname or ""
    return bool(host) and host not in {"localhost", "127.0.0.1", "::1"}


def _remote_info(hass: HomeAssistant) -> dict:
    """Public skill and stream URLs on the Nabu Casa remote UI."""
    info = {
        "skill_url": "",
        "remote_stream_url": "",
        "remote_enabled": False,
        "remote_connected": False,
    }
    cloud = hass.data.get("cloud")
    if cloud is None:
        return info
    client = getattr(cloud, "client", None)
    prefs = getattr(client, "prefs", None) if client is not None else None
    info["remote_enabled"] = bool(getattr(prefs, "remote_enabled", False))
    remote = getattr(cloud, "remote", None)
    domain = getattr(remote, "instance_domain", None) if remote is not None else None
    connected = bool(getattr(remote, "is_connected", False)) and bool(domain)
    info["remote_connected"] = connected
    if connected:
        info["skill_url"] = f"https://{domain}{SKILL_PATH}"
        info["remote_stream_url"] = f"https://{domain}{STREAM_PATH}"
    return info


def _is_music_assistant(addon: dict) -> bool:
    slug = addon.get("slug") or ""
    name = (addon.get("name") or "").strip().lower()
    return slug == "music_assistant" or slug.endswith("_music_assistant") or name == "music assistant"


def _supervisor_data(response) -> dict:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if isinstance(data, dict):
        return data
    return response


async def _discover_ma_stream_base(hass: HomeAssistant) -> str | None:
    """Find the Music Assistant add-on on the Supervisor network."""
    hassio = hass.data.get("hassio")
    if hassio is None or not hasattr(hassio, "send_command"):
        return None
    try:
        listed = _supervisor_data(await hassio.send_command("/addons", method="get"))
    except Exception:
        _LOGGER.exception("Could not list Home Assistant add-ons")
        return None
    addons = listed.get("addons") or []
    chosen = None
    for addon in addons:
        if not isinstance(addon, dict) or not _is_music_assistant(addon):
            continue
        chosen = addon
        if addon.get("state") == "started":
            break
    if chosen is None:
        return None
    slug = chosen.get("slug")
    data = chosen
    if slug:
        try:
            data = _supervisor_data(
                await hassio.send_command(f"/addons/{slug}/info", method="get")
            )
        except Exception:
            _LOGGER.debug("Music Assistant add-on info was unavailable", exc_info=True)
            data = chosen
    if data.get("state") not in (None, "started"):
        _LOGGER.warning("Music Assistant add-on is not started")
        return None
    target = data.get("ip_address") or data.get("hostname")
    if not target:
        return None
    return f"http://{target}:{MA_STREAM_PORT}"


async def _ma_stream_base(hass: HomeAssistant) -> str | None:
    """Return the Music Assistant stream address, refreshing it about once a minute."""
    store = hass.data.setdefault(DOMAIN, {})
    now = time.monotonic()
    cached = store.get(_DATA_MA_BASE)
    if cached and now - store.get(_DATA_MA_CHECKED, 0) < _MA_CACHE_SECONDS:
        return cached
    base = await _discover_ma_stream_base(hass)
    store[_DATA_MA_CHECKED] = now
    if base:
        store[_DATA_MA_BASE] = base
        return base
    return cached


async def _forward_skill(hass: HomeAssistant, request: web.Request) -> web.Response:
    """Forward an Alexa skill POST to the add-on."""
    base = hass.data.get(DOMAIN, {}).get(_DATA_ADDON_URL)
    if not base:
        return web.Response(status=503, text="Music Assistant Alexa add-on is not registered")

    body = await request.read()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _HOP_BY_HOP
    }
    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with session.post(f"{base}/", data=body, headers=headers, timeout=timeout) as resp:
            payload = await resp.read()
            return web.Response(
                status=resp.status,
                body=payload,
                content_type=resp.content_type or "application/json",
            )
    except aiohttp.ClientError:
        _LOGGER.exception("Music Assistant Alexa add-on did not respond")
        return web.Response(status=502, text="Music Assistant Alexa add-on did not respond")


class SkillProxyView(HomeAssistantView):
    """Public Alexa skill endpoint on the Nabu Casa remote UI.

    Intentionally unauthenticated: Amazon cannot log in to Home Assistant.
    Requests are authenticated by Alexa signature verification inside the add-on.
    """

    url = SKILL_PATH
    name = "api:music_assistant_alexa_skill:skill"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        return await _forward_skill(hass, request)


class StreamProxyView(HomeAssistantView):
    """Forward Echo audio requests to the Music Assistant stream server.

    This view is intentionally unauthenticated. An Echo cannot log in to
    Home Assistant, and the stream URLs already carry Music Assistant's own
    tokens. Remote access must be enabled for those requests to arrive.
    """

    url = STREAM_PATH + "/{path:.+}"
    name = "api:music_assistant_alexa_skill:stream"
    requires_auth = False

    async def get(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._proxy(request, path, include_body=True)

    async def head(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._proxy(request, path, include_body=False)

    async def _proxy(self, request: web.Request, path: str, include_body: bool) -> web.StreamResponse:
        hass: HomeAssistant = request.app["hass"]
        if any(part == ".." for part in path.split("/")):
            return web.Response(status=400, text="invalid path")

        base = await _ma_stream_base(hass)
        if not base:
            return web.Response(status=503, text="Music Assistant stream server was not found")

        suffix = "/" + "/".join(quote(part, safe="") for part in path.split("/") if part)
        upstream_url = base + suffix
        if request.query_string:
            upstream_url += "?" + request.query_string

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in _FORWARD_REQUEST_HEADERS
        }
        session = async_get_clientsession(hass)
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=None)
        stream = None
        try:
            async with session.request(
                request.method,
                upstream_url,
                headers=headers,
                timeout=timeout,
            ) as upstream:
                response_headers = {
                    key: value
                    for key, value in upstream.headers.items()
                    if key.lower() not in {
                        "connection",
                        "keep-alive",
                        "proxy-authenticate",
                        "proxy-authorization",
                        "te",
                        "trailers",
                        "transfer-encoding",
                        "upgrade",
                    }
                }
                stream = web.StreamResponse(status=upstream.status, headers=response_headers)
                await stream.prepare(request)
                if include_body and request.method != "HEAD":
                    async for chunk in upstream.content.iter_chunked(64 * 1024):
                        await stream.write(chunk)
                return stream
        except (aiohttp.ClientError, ConnectionError, ConnectionResetError, RuntimeError):
            if stream is not None and stream.prepared:
                return stream
            _LOGGER.exception("Music Assistant stream server did not respond")
            return web.Response(status=502, text="Music Assistant stream server did not respond")


class RegisterView(HomeAssistantView):
    """Let the add-on publish its address and read the remote UI URLs."""

    url = REGISTER_PATH
    name = "api:music_assistant_alexa_skill:register"

    async def get(self, request: web.Request) -> web.Response:
        return await self._response(request, None)

    async def post(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return await self._response(request, data.get("addon_base_url"))

    async def _response(self, request: web.Request, addon_base_url: str | None) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        user = request["hass_user"]
        if user is None or not user.is_admin:
            return self.json({"error": "admin required"}, status_code=403)

        store = hass.data.setdefault(DOMAIN, {})
        if addon_base_url:
            if not _valid_addon_url(addon_base_url):
                return self.json({"error": "invalid addon_base_url"}, status_code=400)
            store[_DATA_ADDON_URL] = addon_base_url.rstrip("/")
            entries = hass.config_entries.async_entries(DOMAIN)
            if entries:
                hass.config_entries.async_update_entry(
                    entries[0],
                    options={**entries[0].options, _DATA_ADDON_URL: store[_DATA_ADDON_URL]},
                )

        remote = _remote_info(hass)
        if not remote["remote_connected"]:
            return self.json(
                {
                    "error": "Home Assistant Cloud remote access is not connected",
                    "skill_url": "",
                    "remote_stream_url": "",
                    "addon_base_url": store.get(_DATA_ADDON_URL, ""),
                    "remote_enabled": remote["remote_enabled"],
                    "remote_connected": remote["remote_connected"],
                    "ma_stream_base": "",
                },
                status_code=503,
            )

        ma_base = await _ma_stream_base(hass)
        _LOGGER.info("Alexa skill remote URL is %s", remote["skill_url"])
        _LOGGER.info("Echo stream URL prefix is %s", remote["remote_stream_url"])
        return self.json(
            {
                "skill_url": remote["skill_url"],
                "remote_stream_url": remote["remote_stream_url"],
                "addon_base_url": store.get(_DATA_ADDON_URL, ""),
                "remote_enabled": remote["remote_enabled"],
                "remote_connected": remote["remote_connected"],
                "ma_stream_base": ma_base or "",
            }
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the public skill and stream views plus the add-on API."""
    store = hass.data.setdefault(DOMAIN, {})
    saved = entry.options.get(_DATA_ADDON_URL)
    if isinstance(saved, str) and _valid_addon_url(saved):
        store[_DATA_ADDON_URL] = saved.rstrip("/")

    if not store.get(_DATA_VIEW):
        hass.http.register_view(SkillProxyView())
        hass.http.register_view(StreamProxyView())
        hass.http.register_view(RegisterView())
        store[_DATA_VIEW] = True

    remote = _remote_info(hass)
    if remote["skill_url"]:
        _LOGGER.info("Alexa skill remote URL is %s", remote["skill_url"])
        _LOGGER.info("Echo stream URL prefix is %s", remote["remote_stream_url"])
    else:
        _LOGGER.warning(
            "Home Assistant Cloud remote access is not connected, "
            "so no public skill or stream URL is available"
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    return True
