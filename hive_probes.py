"""Configuration-only Internet health probes for ULTRON (P1.3).

Only the URLs listed in HIVE_INTERNET_PROBES are contacted; there are no default URLs and nothing is discovered or scanned.
Each probe is one HTTPS HEAD request: no credentials, no request body, no cookies, a fixed User-Agent, a 3 s timeout, and
redirects are NOT followed (a redirect would reach a host that is not on the allowlist). Private, loopback and link-local
IP literals are rejected. The result says only whether the host answered; it is never treated as provider connectivity.
"""
from __future__ import annotations

import ipaddress
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import hive_registry as hr

PROBE_TIMEOUT_S = 3.0
MAX_PROBES = 5
USER_AGENT = "hive-dashboard-health/1 (read-only HEAD probe)"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - never follow
        return None


def default_opener():
    return build_opener(_NoRedirect())


def parse_probe_config(raw):
    """(accepted URLs, rejected [(entry, reason)]). Accepts only explicit https URLs to public hosts."""
    accepted, rejected = [], []
    entries = [e.strip() for e in str(raw or "").replace(",", " ").split() if e.strip()]
    for entry in entries:
        parts = urlsplit(entry)
        host = parts.hostname
        if parts.scheme != "https":
            rejected.append((entry, "only https URLs are allowed"))
        elif not host:
            rejected.append((entry, "no host"))
        elif parts.username or parts.password or "@" in parts.netloc:
            rejected.append((entry, "credentials in a URL are not allowed"))
        else:
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                    rejected.append((entry, "private, loopback or link-local addresses are not Internet probes"))
                    continue
            except ValueError:
                if host.lower() in ("localhost",) or host.lower().endswith((".local", ".localhost", ".internal")):
                    rejected.append((entry, "local host names are not Internet probes"))
                    continue
            if len(accepted) >= MAX_PROBES:
                rejected.append((entry, f"more than {MAX_PROBES} probes configured"))
            else:
                accepted.append(entry)
    return accepted, rejected


def probe(url, opener=None, timeout=PROBE_TIMEOUT_S, clock=time.monotonic):
    """One HEAD request. Any HTTP answer (including 3xx/4xx/5xx) proves the host answered; errors mean unavailable."""
    opener = opener or default_opener()
    req = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    t0 = clock()
    try:
        with opener.open(req, timeout=timeout) as resp:
            code = resp.status
        note = None
    except HTTPError as error:  # an HTTP status is an answer (3xx is not followed)
        code, note = error.code, ("redirect not followed" if 300 <= error.code < 400 else None)
    except (URLError, OSError, ValueError) as error:
        return {"ok": False, "status_code": None, "latency_ms": round((clock() - t0) * 1000), "error": f"{type(error).__name__}: {str(getattr(error, 'reason', error))[:120]}"}
    return {"ok": True, "status_code": code, "latency_ms": round((clock() - t0) * 1000), "note": note}


def read_internet(raw, observed, opener=None, source="internet"):
    accepted, rejected = parse_probe_config(raw)
    src = f"{source}:probes"
    if not accepted and not rejected:
        conn = hr.envelope("connector", "connector:internet", src, None, "not_configured", "HIVE_INTERNET_PROBES is not configured; no Internet probe is made.",
                           name="Internet health", transport="https HEAD (allowlist)", part="internet")
        return {"connectors": [conn], "internet": hr.section([], src, None, "not_configured", conn["reason"])}
    items = []
    for entry, why in rejected:
        host = urlsplit(entry).hostname or urlsplit("//" + entry).hostname or None
        items.append(hr.envelope("connector", "internet:rejected:" + hr.sha256_text(entry)[7:19], src, None, "not_verified", f"rejected: {why}", source_id=host,
                                 name=f"Internet probe {host or 'entry'} (rejected)", transport="https HEAD (allowlist)", part="internet", target_host=host))
    with ThreadPoolExecutor(max_workers=MAX_PROBES) as pool:
        results = list(pool.map(lambda u: (u, probe(u, opener)), accepted))
    for url, r in results:
        host = urlsplit(url).hostname
        validity = "valid" if r["ok"] else "unavailable"
        reason = (f"answered HTTP {r['status_code']} in {r['latency_ms']} ms" + (f" ({r['note']})" if r.get("note") else "")) if r["ok"] else f"no answer: {r['error']}"
        items.append(hr.envelope("connector", f"internet:{host}", src, observed if r["ok"] else None, validity, reason, source_id=host,
                                 name=f"Internet probe {host}", transport="https HEAD (allowlist)", part="internet", target_host=host,
                                 status_code=r["status_code"], latency_ms=r["latency_ms"]))
    return {"connectors": items, "internet": hr.section(items, f"{src} ({len(accepted)} configured)", observed, "valid",
                                                        "Aggregate of the configured probes; each probe reports its own state. A host answering is not provider connectivity.",
                                                        aggregate=True)}
