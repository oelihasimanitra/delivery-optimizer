"""Géocodage via Nominatim (auto-hébergé recommandé ; le service public limite à 1 requête/seconde)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .models import LAT_RANGE, LON_RANGE

# Types OSM trop larges pour localiser une livraison : le point doit être confirmé sur la carte.
BROAD_TYPES = {"city", "town", "village", "suburb", "neighbourhood", "quarter", "state", "region", "country", "administrative", "county", "municipality", "hamlet"}


class GeocodingError(RuntimeError):
    pass


def normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


class NominatimGeocoder:
    def __init__(self, base_url: str, user_agent: str, country_codes: str = "mg", min_interval_s: float = 1.0, timeout: float = 15.0):
        if not user_agent.strip():
            raise ValueError("Nominatim exige un User-Agent identifiant l'application")
        self.base_url = base_url.rstrip("/")
        self.user_agent, self.country_codes = user_agent, country_codes
        self.min_interval_s, self.timeout = min_interval_s, timeout
        self._lock = threading.Lock()
        self._last = 0.0

    def search(self, query: str, limit: int = 3) -> list[dict]:
        query = query.strip()
        if not query:
            raise ValueError("Adresse vide")
        params = urllib.parse.urlencode(
            {"q": query, "format": "jsonv2", "limit": limit, "countrycodes": self.country_codes, "addressdetails": 0}
        )
        request = urllib.request.Request(f"{self.base_url}/search?{params}", headers={"User-Agent": self.user_agent})
        with self._lock:  # respecte l'intervalle minimal entre deux requêtes
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    raw = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                raise GeocodingError(f"Géocodage indisponible : {error}") from error
            finally:
                self._last = time.monotonic()
        results = []
        for item in raw:
            try:
                lat, lon = float(item["lat"]), float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
                continue
            kind = str(item.get("type", ""))
            results.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "label": str(item.get("display_name", "")),
                    "type": kind,
                    "approximate": kind in BROAD_TYPES,
                }
            )
        return results
