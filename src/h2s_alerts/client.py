"""Small client for the public Holland2Stay REST endpoints.

It says who it is in the User-Agent, sends one request at a time and keeps a gap
between requests. It never pretends to be a browser.
"""

from __future__ import annotations

import math
import threading
import time
from email.utils import parsedate_to_datetime

import requests

from . import USER_AGENT
from .config import DEFAULT_BASE_URL

Filter = tuple[str, str, str]  # field, value, condition


class H2SError(Exception):
    kind = "error"


class Blocked(H2SError):
    kind = "blocked"


class RateLimited(H2SError):
    kind = "rate_limited"

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class Unavailable(H2SError):
    kind = "unavailable"


class Changed(H2SError):
    kind = "changed"


def criteria(filters: list[Filter], page_size: int = 300, page: int = 1,
             sort: tuple[str, str] | None = None) -> list[tuple[str, str]]:
    """Magento searchCriteria. Each filter is its own group, so they combine with AND."""
    params = [("searchCriteria[pageSize]", str(page_size)), ("searchCriteria[currentPage]", str(page))]
    for i, (fld, value, cond) in enumerate(filters):
        base = f"searchCriteria[filter_groups][{i}][filters][0]"
        params += [(f"{base}[field]", fld), (f"{base}[value]", value), (f"{base}[condition_type]", cond)]
    if sort:
        params += [("searchCriteria[sortOrders][0][field]", sort[0]),
                   ("searchCriteria[sortOrders][0][direction]", sort[1])]
    return params


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


class Client:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, min_gap: float = 1.5, timeout: float = 20,
                 session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.min_gap = min_gap
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json",
                                     "Accept-Language": "en"})
        self._lock = threading.Lock()
        self._last = 0.0
        self.requests = 0
        self.bytes = 0

    def get(self, path: str, params: list[tuple[str, str]] | None = None):
        with self._lock:
            wait = self.min_gap - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.session.get(f"{self.base_url}/api/rest/{path}", params=params,
                                     timeout=self.timeout)
            except requests.RequestException as e:
                raise Unavailable(f"Can't reach Holland2Stay ({type(e).__name__})") from None
            finally:
                self._last = time.monotonic()
                self.requests += 1
        self.bytes += len(r.content or b"")
        return self._parse(r)

    @staticmethod
    def _parse(r):
        status = r.status_code
        text = r.text[:2000] if r.content else ""
        if status == 429:
            raise RateLimited("Holland2Stay asked us to slow down", _retry_after(r.headers.get("Retry-After")))
        if status in (403, 503) and (r.headers.get("cf-mitigated") or "Just a moment" in text):
            raise Blocked("Cloudflare is blocking automated requests")
        if status == 403 and "clearance_required" in text:
            raise Blocked("Holland2Stay wants a browser check")
        if status == 403:
            raise Blocked("Holland2Stay refused the request (403)")
        if status in (404, 410):
            raise Changed("Holland2Stay moved or removed the listing endpoint")
        if status >= 500:
            raise Unavailable(f"Holland2Stay is having trouble (HTTP {status})")
        if status != 200:
            raise Changed(f"Unexpected answer from Holland2Stay (HTTP {status})")
        try:
            return r.json()
        except ValueError:
            raise Changed("Holland2Stay sent something that isn't JSON") from None

    def products(self, filters: list[Filter], fields: str, page_size: int = 300, page: int = 1,
                 sort: tuple[str, str] | None = None) -> list[dict]:
        params = criteria(filters, page_size, page, sort)
        params += [("storeId", "1"), ("currencyCode", "EUR"), ("fields", fields)]
        data = self.get("V1/products-render-info", params)
        if not isinstance(data, dict) or "items" not in data:
            raise Changed("The listing endpoint changed its format")
        items = data["items"] or []  # Magento sends null when nothing matches
        if not isinstance(items, list):
            raise Changed("The listing endpoint changed its format")
        return items

    def buckets(self, filters: list[Filter]) -> dict[str, dict[int, int]]:
        """Facet counts from the catalog search, e.g. {'city_bucket': {29: 18, ...}}."""
        params = [("searchCriteria[requestName]", "catalog_view_container")]
        params += criteria(filters, page_size=1)
        data = self.get("V1/search", params)
        try:
            out: dict[str, dict[int, int]] = {}
            for b in data["aggregations"]["buckets"]:
                values = {}
                for v in b["values"]:
                    if str(v["value"]).isdigit():
                        values[int(v["value"])] = int(v["metrics"][1])
                out[b["name"]] = values
            return out
        except (KeyError, TypeError, IndexError, ValueError):
            raise Changed("The search endpoint changed its format") from None
