"""Serveur HTTP (bibliothèque standard) : API JSON, authentification par session, interface web."""

from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import re
import sqlite3
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .auth import SESSION_SECONDS, LoginThrottle, hash_password, hash_token, new_token, verify_password
from .config import AppSettings
from .geocoding import GeocodingError, NominatimGeocoder, normalize_query
from .planner import PlanningError, run_plan
from .storage import Storage
from .verify import verify_plan

log = logging.getLogger("deliveryopt")
MAX_BODY = 5 * 1024 * 1024
STATIC_DIR = Path(__file__).parent / "static"
CSP = (
    "default-src 'self'; img-src 'self' data: https://*.tile.openstreetmap.org https://unpkg.com; "
    "script-src 'self' https://unpkg.com; style-src 'self' 'unsafe-inline' https://unpkg.com; connect-src 'self'; frame-ancestors 'none'"
)


class HttpError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class AppContext:
    storage: Storage
    provider: object
    geocoder: NominatimGeocoder | None = None
    secure_cookie: bool = False
    throttle: LoginThrottle | None = None

    def __post_init__(self) -> None:
        self.throttle = self.throttle or LoginThrottle()


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def plan_to_csv(plan: dict) -> str:
    out = io.StringIO()
    out.write("﻿")
    w = csv.writer(out, delimiter=";")
    w.writerow(["livreur", "ordre", "adresse", "colis", "arrivee", "remise", "depart", "trajet_km", "prix_ar", "adresse_eloignee", "explication_prix"])
    for r in plan["routes"]:
        for s in r["stops"]:
            w.writerow([r["driver"], s["order"], _csv_safe(s["address"]), " ".join(s["parcel_ids"]), s["arrival"], s["service_start"], s["departure"], str(s["leg_km"]).replace(".", ","), s["price_ar"], "oui" if s["is_distant"] else "non", _csv_safe(s["price_explanation"])])
    for u in plan["unassigned"]:
        w.writerow(["NON ATTRIBUE", "", _csv_safe(u["address"]), " ".join(u["parcel_ids"]), "", "", "", "", "", "", _csv_safe(u["reason"])])
    for rej in plan["rejected"]:
        w.writerow(["ECARTE", "", "", _csv_safe(rej["parcel_id"]), "", "", "", "", "", "", _csv_safe(rej["message"])])
    return out.getvalue()


def make_handler(ctx: AppContext):
    routes: list[tuple[str, re.Pattern, str, str | None]] = []

    def route(method: str, pattern: str, role: str | None = "operateur"):
        """role : None = public ; 'operateur' = tout utilisateur connecté ; 'admin' = administrateurs."""

        def deco(fn):
            routes.append((method, re.compile(f"^{pattern}$"), fn.__name__, role))
            return fn

        return deco

    class Handler(BaseHTTPRequestHandler):
        server_version = f"deliveryopt/{__version__}"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # noqa: A003
            log.info("%s - %s", self.address_string(), fmt % args)

        # ---- infrastructure ----
        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")  # OSM refuse (403) les tuiles sans Referer
            self.send_header("Content-Security-Policy", CSP)
            if content_type.startswith("application/json") or content_type.startswith("text/csv"):
                self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, data, extra: dict | None = None):
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

        def _read_raw_body(self) -> bytes:
            """Lit TOUJOURS le corps annoncé, même si la route ne s'en sert pas : en HTTP/1.1 avec connexion
            persistante, un corps non lu serait pris pour le début de la requête suivante."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self.close_connection = True
                raise HttpError(400, "REQUETE_INVALIDE", "Content-Length invalide.") from None
            if length > MAX_BODY:
                self.close_connection = True  # on ne lit pas 5 Mo+ : on coupe la connexion
                raise HttpError(413, "CORPS_TROP_GRAND", "Requête trop volumineuse.")
            return self.rfile.read(length) if length > 0 else b""

        def _body(self) -> dict:
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise HttpError(415, "JSON_ATTENDU", "Content-Type application/json requis.")
            try:
                data = json.loads(self._raw or b"{}")
            except (ValueError, UnicodeDecodeError):
                raise HttpError(400, "JSON_INVALIDE", "Corps JSON invalide.") from None
            if not isinstance(data, dict):
                raise HttpError(400, "JSON_INVALIDE", "Un objet JSON est attendu.")
            return data

        def _token(self) -> str | None:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie["session"].value if "session" in cookie else None

        def _user(self):
            token = self._token()
            return ctx.storage.get_session_user(hash_token(token)) if token else None

        def _dispatch(self, method: str):
            self._raw = b""
            try:
                self._raw = self._read_raw_body()
                path = urlparse(self.path).path
                if path.startswith("/api/"):
                    origin = self.headers.get("Origin")
                    if origin and urlparse(origin).netloc != self.headers.get("Host"):
                        raise HttpError(403, "ORIGINE_REFUSEE", "Requête d'une autre origine refusée.")
                    for m, pattern, name, role in routes:
                        match = pattern.match(path)
                        if m == method and match:
                            user = self._user()
                            if role is not None and user is None:
                                raise HttpError(401, "NON_CONNECTE", "Connexion requise.")
                            if role == "admin" and user["role"] != "admin":
                                raise HttpError(403, "ACCES_REFUSE", "Réservé aux administrateurs.")
                            getattr(self, name)(user, *match.groups())
                            return
                    raise HttpError(404, "INTROUVABLE", "Ressource introuvable.")
                if method != "GET":
                    raise HttpError(405, "METHODE", "Méthode non autorisée.")
                self._static(path)
            except HttpError as e:
                self._json(e.status, {"error": e.code, "message": e.message})
            except Exception:  # noqa: BLE001 - dernier filet : ne jamais exposer de trace
                log.exception("Erreur interne")
                self._json(500, {"error": "ERREUR_INTERNE", "message": "Erreur interne du serveur."})

        def _static(self, path: str):
            rel = "index.html" if path in ("/", "") else path.removeprefix("/static/").lstrip("/")
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                raise HttpError(404, "INTROUVABLE", "Fichier introuvable.")
            if not target.is_file():
                raise HttpError(404, "INTROUVABLE", "Fichier introuvable.")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})

        def do_GET(self): self._dispatch("GET")  # noqa: E704
        def do_POST(self): self._dispatch("POST")  # noqa: E704
        def do_PUT(self): self._dispatch("PUT")  # noqa: E704
        def do_DELETE(self): self._dispatch("DELETE")  # noqa: E704

        # ---- API ----
        @route("GET", "/api/health", None)
        def health(self, user):
            self._json(200, {"ok": True, "version": __version__})

        @route("POST", "/api/login", None)
        def login(self, user):
            data = self._body()
            username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
            wait = ctx.throttle.blocked_for(username)
            if wait > 0:
                raise HttpError(429, "TROP_DE_TENTATIVES", f"Trop de tentatives : réessayez dans {int(wait) + 1} s.")
            row = ctx.storage.get_user(username)
            if row is None or not verify_password(password, row["password_hash"]):
                ctx.throttle.failure(username)
                raise HttpError(401, "IDENTIFIANTS_INVALIDES", "Identifiant ou mot de passe incorrect.")
            ctx.throttle.success(username)
            token, token_hash = new_token()
            ctx.storage.add_session(token_hash, username, time.time() + SESSION_SECONDS)
            cookie = f"session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_SECONDS}" + ("; Secure" if ctx.secure_cookie else "")
            self._json(200, {"username": username, "role": row["role"]}, {"Set-Cookie": cookie})

        @route("POST", "/api/logout", None)
        def logout(self, user):
            token = self._token()
            if token:
                ctx.storage.delete_session(hash_token(token))
            self._json(200, {"ok": True}, {"Set-Cookie": "session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"})

        @route("GET", "/api/me")
        def me(self, user):
            provider = ctx.provider
            self._json(200, {
                "username": user["username"], "role": user["role"], "version": __version__,
                "routing_mode": getattr(provider, "mode", "unknown"), "billing_reliable": bool(getattr(provider, "reliable", False)),
                "geocoding_enabled": ctx.geocoder is not None,
            })

        @route("POST", "/api/password")
        def change_password(self, user):
            data = self._body()
            row = ctx.storage.get_user(user["username"])
            if not verify_password(str(data.get("old_password", "")), row["password_hash"]):
                raise HttpError(403, "MOT_DE_PASSE_INCORRECT", "Ancien mot de passe incorrect.")
            try:
                ctx.storage.set_password(user["username"], hash_password(str(data.get("new_password", ""))))
            except ValueError as e:
                raise HttpError(422, "MOT_DE_PASSE_INVALIDE", str(e)) from None
            self._json(200, {"ok": True})

        @route("GET", "/api/settings")
        def get_settings(self, user):
            self._json(200, ctx.storage.load_settings().to_dict())

        @route("PUT", "/api/settings", "admin")
        def put_settings(self, user):
            try:
                settings = AppSettings.from_dict(self._body())
            except (ValueError, TypeError, ArithmeticError) as e:
                raise HttpError(422, "PARAMETRES_INVALIDES", str(e)) from None
            ctx.storage.save_settings(settings)
            self._json(200, settings.to_dict())

        @route("POST", "/api/geocode")
        def geocode(self, user):
            if ctx.geocoder is None:
                raise HttpError(503, "GEOCODAGE_NON_CONFIGURE", "Géocodage non configuré : placez le point sur la carte ou saisissez latitude et longitude.")
            address = str(self._body().get("address", "")).strip()
            if not address:
                raise HttpError(422, "ADRESSE_VIDE", "Adresse vide.")
            key = normalize_query(address)
            results = ctx.storage.get_geocode(key)
            if results is None:
                try:
                    results = ctx.geocoder.search(address)
                except GeocodingError as e:
                    raise HttpError(502, "GEOCODAGE_INDISPONIBLE", str(e)) from None
                ctx.storage.put_geocode(key, results)
            self._json(200, {"results": results, "message": None if results else "Adresse introuvable : placez le point sur la carte."})

        @route("POST", "/api/plans")
        def create_plan(self, user):
            data = self._body()
            rows = data.get("parcels")
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                raise HttpError(422, "COLIS_INVALIDES", "'parcels' doit être une liste d'objets.")
            app = ctx.storage.load_settings()
            try:
                result = run_plan(rows, ctx.provider, app, data.get("date"))
            except PlanningError as e:
                raise HttpError(503, "PLANIFICATION_IMPOSSIBLE", str(e)) from None
            plan = result.plan
            problems = verify_plan(plan, rows, app)
            plan["verification_errors"] = problems
            if problems:
                log.error("Le vérificateur indépendant a détecté des écarts : %s", problems)
            label = str(data.get("label") or f"Plan du {data.get('date') or time.strftime('%Y-%m-%d')}")[:120]
            plan_id = ctx.storage.add_plan(user["username"], label, data.get("date"), rows, plan)
            self._json(201, {"id": plan_id, "label": label, "result": plan})

        @route("GET", "/api/plans")
        def list_plans(self, user):
            self._json(200, {"plans": ctx.storage.list_plans()})

        @route("GET", r"/api/plans/(\d+)")
        def get_plan(self, user, plan_id):
            plan = ctx.storage.get_plan(int(plan_id))
            if plan is None:
                raise HttpError(404, "PLAN_INTROUVABLE", "Plan introuvable.")
            self._json(200, plan)

        @route("GET", r"/api/plans/(\d+)/export\.csv")
        def export_plan(self, user, plan_id):
            plan = ctx.storage.get_plan(int(plan_id))
            if plan is None:
                raise HttpError(404, "PLAN_INTROUVABLE", "Plan introuvable.")
            self._send(200, plan_to_csv(plan["result"]).encode("utf-8"), "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="plan-{plan_id}.csv"'})

        @route("GET", "/api/users", "admin")
        def list_users(self, user):
            self._json(200, {"users": ctx.storage.list_users()})

        @route("POST", "/api/users", "admin")
        def add_user(self, user):
            data = self._body()
            username, role = str(data.get("username", "")).strip(), str(data.get("role", "operateur"))
            if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
                raise HttpError(422, "IDENTIFIANT_INVALIDE", "Identifiant : 3 à 40 caractères (lettres, chiffres, _ . -).")
            if role not in ("admin", "operateur"):
                raise HttpError(422, "ROLE_INVALIDE", "Rôle : admin ou operateur.")
            try:
                ctx.storage.add_user(username, hash_password(str(data.get("password", ""))), role)
            except ValueError as e:
                raise HttpError(422, "MOT_DE_PASSE_INVALIDE", str(e)) from None
            except sqlite3.IntegrityError:
                raise HttpError(409, "UTILISATEUR_EXISTANT", "Cet identifiant existe déjà.") from None
            self._json(201, {"username": username, "role": role})

        @route("DELETE", r"/api/users/([A-Za-z0-9_.-]+)", "admin")
        def delete_user(self, user, username):
            if username == user["username"]:
                raise HttpError(409, "SUPPRESSION_DE_SOI", "Vous ne pouvez pas supprimer votre propre compte.")
            if ctx.storage.get_user(username) is None:
                raise HttpError(404, "UTILISATEUR_INTROUVABLE", "Utilisateur introuvable.")
            ctx.storage.delete_user(username)
            self._json(200, {"ok": True})

    return Handler


def create_server(ctx: AppContext, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(ctx))
    server.daemon_threads = True
    return server
