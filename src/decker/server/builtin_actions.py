"""Actions that ship inside Decker and run in the server process (no plugin process involved)."""

import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

HTTP_REQUEST_ACTION_ID = "com.decker.core.httprequest"
_HTTP_SCHEMES = ("http://", "https://")
_MAX_STATUS_OK = 400


class ActionError(Exception):
    """An action ran and failed; the message is shown to the user."""


def http_request(settings: Mapping[str, Any]) -> None:
    """Send one HTTP request; any answer below status 400 is a success."""
    url = str(settings.get("url", "")).strip()
    if not url.lower().startswith(_HTTP_SCHEMES):
        raise ActionError("the URL must start with http:// or https://")
    body = str(settings.get("body", ""))
    request = urllib.request.Request(  # noqa: S310  # the scheme was checked above
        url,
        data=body.encode("utf-8") if body else None,
        method=str(settings.get("method", "GET")),
    )
    content_type = str(settings.get("content_type", "")).strip()
    if content_type:
        request.add_header("Content-Type", content_type)
    timeout = float(settings.get("timeout", 10) or 10)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raise ActionError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ActionError(str(getattr(exc, "reason", exc))) from exc
    if status >= _MAX_STATUS_OK:
        raise ActionError(f"HTTP {status}")


BUILTIN_ACTIONS: Mapping[str, Callable[[Mapping[str, Any]], None]] = {HTTP_REQUEST_ACTION_ID: http_request}
