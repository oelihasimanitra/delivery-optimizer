"""Distances et durées entre points.

Deux fournisseurs :
- OSRMProvider : distances et durées routières réelles (serveur OSRM auto-hébergé recommandé).
- EstimateProvider : estimation = vol d'oiseau x coefficient. Mode de démonstration, JAMAIS utilisé
  sans le dire : le plan produit est marqué `distances_estimees` et non facturable.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

Point = tuple[float, float]  # (latitude, longitude)


class RoutingError(RuntimeError):
    """Le service de routing est indisponible ou a répondu de façon inattendue."""


@dataclass
class MatrixResult:
    km: list[list[float | None]]
    minutes: list[list[float | None]]  # durées non corrigées par le coefficient de trafic
    snap_m: list[float | None]  # distance entre chaque point et la route la plus proche (OSRM)
    mode: str  # "osrm" ou "estimate"
    reliable: bool  # False : distances non routières, résultats non facturables


def haversine_km(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


class EstimateProvider:
    mode = "estimate"
    reliable = False

    def __init__(self, detour_factor: float = 1.4, speed_kmh: float = 20.0):
        if detour_factor < 1 or speed_kmh <= 0:
            raise ValueError("detour_factor >= 1 et speed_kmh > 0 requis")
        self.detour_factor, self.speed_kmh = detour_factor, speed_kmh

    def matrix(self, points: list[Point]) -> MatrixResult:
        n = len(points)
        km = [[0.0 if i == j else haversine_km(points[i], points[j]) * self.detour_factor for j in range(n)] for i in range(n)]
        minutes = [[km[i][j] / self.speed_kmh * 60 for j in range(n)] for i in range(n)]
        return MatrixResult(km, minutes, [None] * n, self.mode, self.reliable)


class OSRMProvider:
    """Client du service /table d'OSRM. Les couples sans route renvoient None (jamais une valeur inventée)."""

    mode = "osrm"
    reliable = True

    def __init__(self, base_url: str, chunk: int = 50, timeout: float = 30.0, profile: str = "driving"):
        self.base_url = base_url.rstrip("/")
        self.chunk, self.timeout, self.profile = max(2, chunk), timeout, profile

    def _get(self, url: str) -> dict:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:  # noqa: S310 (URL fournie par l'administrateur)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")[:200]
            raise RoutingError(f"OSRM a répondu {error.code} : {body}") from error
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise RoutingError(f"OSRM injoignable ({self.base_url}) : {error}") from error

    def matrix(self, points: list[Point]) -> MatrixResult:
        n = len(points)
        km: list[list[float | None]] = [[None] * n for _ in range(n)]
        minutes: list[list[float | None]] = [[None] * n for _ in range(n)]
        snap: list[float | None] = [None] * n
        blocks = [list(range(i, min(i + self.chunk, n))) for i in range(0, n, self.chunk)]
        for sb in blocks:
            for db in blocks:
                coords = ";".join(f"{points[i][1]:.6f},{points[i][0]:.6f}" for i in sb + db)
                query = urllib.parse.urlencode(
                    {
                        "sources": ";".join(str(k) for k in range(len(sb))),
                        "destinations": ";".join(str(len(sb) + k) for k in range(len(db))),
                        "annotations": "duration,distance",
                    },
                    safe=";",
                )
                data = self._get(f"{self.base_url}/table/v1/{self.profile}/{coords}?{query}")
                if data.get("code") != "Ok":
                    raise RoutingError(f"OSRM : {data.get('code')} {data.get('message', '')}".strip())
                for a, i in enumerate(sb):
                    for b, j in enumerate(db):
                        d, t = data["distances"][a][b], data["durations"][a][b]
                        if i == j:
                            km[i][j], minutes[i][j] = 0.0, 0.0
                        elif d is not None and t is not None:
                            km[i][j], minutes[i][j] = d / 1000.0, t / 60.0
                for a, i in enumerate(sb):
                    s = data.get("sources", [{}] * len(sb))[a].get("distance")
                    if s is not None:
                        snap[i] = s
        return MatrixResult(km, minutes, snap, self.mode, self.reliable)
