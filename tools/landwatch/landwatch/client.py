"""HTTP transport for the LandWatch JSON endpoints.

Two transport details are load-bearing and were established by probing the live
site; changing either produces a blanket ``403 Access Denied`` from the CDN:

1. Requests must go over HTTP/2. The identical request over HTTP/1.1 is refused,
   which is why this module requires ``httpx`` with the ``h2`` extra rather than
   a simpler HTTP/1.1 client.
2. The full browser header set must be sent. A request carrying only
   ``user-agent`` is refused; the ``sec-ch-ua*``, ``sec-fetch-*`` and ``priority``
   headers all have to be present, along with a ``referer`` pointing at the
   corresponding public page.
"""

from __future__ import annotations

import logging
import random
import time
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from .vocab import BASE_URL, SITE_ID

logger = logging.getLogger(__name__)

# Shorter queries always come back empty from the autocomplete endpoint.
MIN_AUTOCOMPLETE_QUERY = 3

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# Sent on every request. Omitting any of these triggers a 403.
BROWSER_HEADERS: dict[str, str] = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "priority": "u=1, i",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": _USER_AGENT,
}


class LandWatchError(RuntimeError):
    """Base class for all LandWatch client failures."""


class LocationNotFound(LandWatchError):
    """The search path did not resolve, usually an unknown place slug."""


class BlockedError(LandWatchError):
    """The CDN refused the request even after retries."""


class LandWatchClient:
    """Fetches JSON from LandWatch's search endpoints.

    Usable as a context manager::

        with LandWatchClient() as client:
            payload = client.search_payload("/texas-land-for-sale")
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        min_delay: float = 1.0,
        site_id: int = SITE_ID,
        base_url: str = BASE_URL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.site_id = site_id
        self.max_retries = max_retries
        self.min_delay = min_delay
        self._last_request_at = 0.0

        try:
            self._client = httpx.Client(
                http2=True,
                timeout=timeout,
                headers=BROWSER_HEADERS,
                follow_redirects=True,
            )
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise LandWatchError(
                "HTTP/2 support is required because LandWatch rejects HTTP/1.1 requests. "
                "Install it with: pip install 'httpx[http2]'"
            ) from exc

    def __enter__(self) -> LandWatchClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        """Space out requests to stay well within polite crawling limits."""
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self._last_request_at = time.monotonic()

    def _request(
        self,
        method: str,
        api_path: str,
        *,
        referer_path: str,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{api_path}"
        headers = {"referer": f"{self.base_url}{referer_path}"}
        if json_body is not None:
            headers["content-type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self._client.request(method, url, headers=headers, json=json_body)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("request to %s failed (attempt %d): %s", url, attempt, exc)
            else:
                if response.status_code == 404:
                    raise LocationNotFound(
                        f"LandWatch has no page for '{referer_path}'. "
                        "Check the state, county, city or region spelling."
                    )
                if response.status_code == 200:
                    return response
                if response.status_code in (403, 429) or response.status_code >= 500:
                    last_error = LandWatchError(f"HTTP {response.status_code} from {url}")
                    logger.warning(
                        "transient HTTP %d from %s (attempt %d)",
                        response.status_code,
                        url,
                        attempt,
                    )
                else:
                    raise LandWatchError(f"HTTP {response.status_code} from {url}")

            if attempt < self.max_retries:
                backoff = 2 ** (attempt - 1) + random.uniform(0, 0.5)
                time.sleep(backoff)

        raise BlockedError(
            f"giving up on {url} after {self.max_retries} attempts: {last_error}. "
            "LandWatch may have changed its bot protection."
        ) from last_error

    def search_payload(self, path: str) -> dict[str, Any]:
        """Fetch the raw search payload for a search URL path."""
        response = self._request(
            "GET", f"/api/property/search/{self.site_id}{path}", referer_path=path
        )
        return response.json()

    def criteria_payload(self, path: str) -> dict[str, Any]:
        """Fetch LandWatch's own reading of a search URL path.

        Useful for confirming a constructed URL was understood as intended.
        """
        response = self._request(
            "GET", f"/api/property/criteria/{self.site_id}{path}", referer_path=path
        )
        return response.json()

    def autocomplete_payload(self, query: str) -> list[dict[str, Any]]:
        """Look up places whose name matches ``query``.

        Returns raw entries of the form ``{id, location, searchPath, stateId, type}``
        where ``type`` is 1 for a city, 2 for a county, 5 for a region and 6 for a
        state. See :mod:`landwatch.places` for the parsed form.

        LandWatch needs at least three characters and returns an empty list for
        anything shorter, so short queries are skipped rather than sent.
        """
        if len(query.strip()) < MIN_AUTOCOMPLETE_QUERY:
            return []

        response = self._request(
            "GET",
            f"/api/location/autocomplete/{self.site_id}/{quote(query.strip())}",
            referer_path="/",
        )
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def detail_payload(self, property_id: int) -> dict[str, Any]:
        """Fetch the raw detail payload for one listing."""
        response = self._request(
            "GET", f"/api/property/{property_id}", referer_path=f"/pid/{property_id}"
        )
        return response.json()

    def resolve_path(self, criteria_body: dict[str, Any]) -> str:
        """Ask LandWatch to convert a raw criteria object into a URL path.

        This mirrors what the site's own filter UI does. ``url.build_path`` covers
        this locally without a network round trip; this endpoint is here for
        cross-checking that local output.
        """
        response = self._request(
            "POST",
            f"/api/property/searchUrl/{self.site_id}",
            referer_path="/",
            json_body=criteria_body,
        )
        return response.text.strip()
