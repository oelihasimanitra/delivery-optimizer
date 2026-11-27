"""Outils de test : fournisseur de distances contrôlable, client HTTP avec cookies, faux serveurs."""

from __future__ import annotations

import http.cookiejar
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from deliveryopt.routing import MatrixResult, haversine_km

DEPOT = (-18.91, 47.525)


class GridProvider:
    """Distances = vol d'oiseau SANS coefficient, présentées comme routières : sert à tester la logique
    avec des valeurs prévisibles. `blocked` contient des couples (lat, lon) sans route."""

    mode = "osrm"
    reliable = True

    def __init__(self, speed_kmh: float = 30.0, blocked_from_depot=(), blocked_pairs=()):
        self.speed = speed_kmh
        self.blocked_from_depot = {(round(a, 5), round(b, 5)) for a, b in blocked_from_depot}
        self.blocked_pairs = {frozenset({(round(a[0], 5), round(a[1], 5)), (round(b[0], 5), round(b[1], 5))}) for a, b in blocked_pairs}

    def matrix(self, points):
        n = len(points)
        key = lambda p: (round(p[0], 5), round(p[1], 5))  # noqa: E731
        km = [[None] * n for _ in range(n)]
        minutes = [[None] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    km[i][j], minutes[i][j] = 0.0, 0.0
                    continue
                if i == 0 and key(points[j]) in self.blocked_from_depot:
                    continue
                if frozenset({key(points[i]), key(points[j])}) in self.blocked_pairs:
                    continue
                d = haversine_km(points[i], points[j])
                km[i][j], minutes[i][j] = d, d / self.speed * 60
        return MatrixResult(km, minutes, [None] * n, self.mode, self.reliable)


def parcel(pid, lat, lon, **kw):
    row = {"id_colis": pid, "adresse": f"Adresse {pid}", "latitude": lat, "longitude": lon}
    row.update(kw)
    return row


def offset(dlat_km: float = 0.0, dlon_km: float = 0.0, base=DEPOT):
    """Point à (dlat_km vers le nord, dlon_km vers l'est) du dépôt."""
    return (base[0] + dlat_km / 111.19, base[1] + dlon_km / (111.19 * 0.9473))


class Client:
    """Client HTTP minimal avec cookies de session."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method, path, body=None, headers=None, raw=False):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=60) as resp:
                payload = resp.read()
                return resp.status, (payload if raw else json.loads(payload or b"null")), resp.headers
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, (payload if raw else json.loads(payload or b"null")), e.headers
            except ValueError:
                return e.code, payload, e.headers

    def login(self, username, password):
        return self.request("POST", "/api/login", {"username": username, "password": password})


class FakeHTTP:
    """Faux serveur HTTP (thread) dont le comportement est défini par une fonction handler(path, headers) -> (status, body)."""

    def __init__(self, handler):
        outer = self
        self.requests: list[tuple[str, dict]] = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append((self.path, dict(self.headers)))
                status, body = handler(self.path, self.headers)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
