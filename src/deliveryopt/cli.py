"""Ligne de commande : serve, create-user, plan, benchmark, vendor-leaflet."""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

from . import __version__
from .auth import hash_password
from .benchmark import format_table, run_benchmark
from .config import AppSettings
from .geocoding import NominatimGeocoder
from .planner import PlanningError, run_plan
from .routing import EstimateProvider, OSRMProvider
from .server import STATIC_DIR, AppContext, create_server
from .storage import Storage
from .verify import verify_plan

LEAFLET_VERSION = "1.9.4"
LEAFLET_FILES = {
    "leaflet.js": f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js",
    "leaflet.css": f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css",
}


def make_provider(env=os.environ):
    url = env.get("DELIVERYOPT_OSRM_URL", "").strip()
    if url:
        return OSRMProvider(url, chunk=int(env.get("DELIVERYOPT_OSRM_CHUNK", "50")))
    return EstimateProvider()


def make_geocoder(env=os.environ):
    url = env.get("DELIVERYOPT_NOMINATIM_URL", "").strip()
    if not url:
        return None
    agent = env.get("DELIVERYOPT_USER_AGENT", "").strip()
    if "nominatim.openstreetmap.org" in url and not agent:
        raise SystemExit("Le service public Nominatim exige DELIVERYOPT_USER_AGENT (nom de l'application + contact). Préférez une instance auto-hébergée.")
    interval = 1.0 if "nominatim.openstreetmap.org" in url else 0.0
    return NominatimGeocoder(url, agent or f"deliveryopt/{__version__}", min_interval_s=interval)


def read_parcels_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]


def cmd_serve(args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    storage = Storage(os.environ.get("DELIVERYOPT_DB", "data/app.db"))
    user, password = os.environ.get("DELIVERYOPT_ADMIN_USER"), os.environ.get("DELIVERYOPT_ADMIN_PASSWORD")
    if storage.count_users() == 0:
        if user and password:
            storage.add_user(user, hash_password(password), "admin")
            print(f"Administrateur « {user} » créé.")
        else:
            print("Aucun utilisateur : créez un administrateur avec « python run.py create-user » ou définissez DELIVERYOPT_ADMIN_USER et DELIVERYOPT_ADMIN_PASSWORD.", file=sys.stderr)
            return 2
    provider = make_provider()
    ctx = AppContext(storage, provider, make_geocoder(), secure_cookie=os.environ.get("DELIVERYOPT_SECURE_COOKIE") == "1")
    server = create_server(ctx, args.host, args.port)
    print(f"deliveryopt {__version__} : http://{args.host}:{args.port}")
    if not provider.reliable:
        print("ATTENTION : mode ESTIMATION (DELIVERYOPT_OSRM_URL absent). Les distances sont à vol d'oiseau x 1,4 : "
              "résultats indicatifs, tarifs non facturables. Configurez OSRM (voir docs/deployment.md).", file=sys.stderr)
    if ctx.geocoder is None:
        print("Géocodage désactivé (DELIVERYOPT_NOMINATIM_URL absent) : coordonnées saisies ou placées sur la carte.", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Arrêt.")
    return 0


def cmd_create_user(args) -> int:
    storage = Storage(os.environ.get("DELIVERYOPT_DB", "data/app.db"))
    password = os.environ.get("DELIVERYOPT_PASSWORD") or getpass.getpass("Mot de passe : ")
    try:
        storage.add_user(args.username, hash_password(password), args.role)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"Impossible de créer l'utilisateur : {error}", file=sys.stderr)
        return 2
    print(f"Utilisateur « {args.username} » ({args.role}) créé.")
    return 0


def cmd_plan(args) -> int:
    rows = read_parcels_csv(args.csv)
    app = AppSettings()
    if args.depot:
        lat, lon = (float(x) for x in args.depot.split(","))
        app = AppSettings(depot_lat=lat, depot_lon=lon)
    provider = make_provider()
    try:
        result = run_plan(rows, provider, app, args.date)
    except PlanningError as error:
        print(error, file=sys.stderr)
        return 2
    plan = result.plan
    problems = verify_plan(plan, rows, app)
    plan["verification_errors"] = problems
    if args.out:
        Path(args.out).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    t = plan["totals"]
    print(f"{t['drivers']} livreur(s), {t['parcels_planned']} colis, {t['distance_km']} km, total à facturer {t['revenue_ar']} Ar, coût interne {t['cost_ar']} Ar")
    for a in plan["alerts"]:
        print(f"[{a['severity']}] {a['message']}")
    for r in plan["routes"]:
        print(f"\nLivreur {r['driver']} : {r['parcel_count']} colis, {r['distance_km']} km, fin {r['end_time']}")
        for s in r["stops"]:
            print(f"  {s['order']:>2}. {s['service_start']} {s['address']} ({', '.join(s['parcel_ids'])}) {s['leg_km']} km, {s['price_ar']} Ar{' [éloigné]' if s['is_distant'] else ''}")
    for u in plan["unassigned"]:
        print(f"\nNON ATTRIBUÉ {u['parcel_ids']} : {u['reason']}")
    for rej in plan["rejected"]:
        print(f"ÉCARTÉ {rej['parcel_id']} : {rej['message']}")
    print("\nVérification indépendante :", "OK" if not problems else problems)
    return 0 if not problems else 1


def cmd_benchmark(args) -> int:
    print(format_table(run_benchmark(args.n, args.seeds, args.time_limit)))
    return 0


def cmd_vendor_leaflet(_args) -> int:
    target = STATIC_DIR / "vendor"
    target.mkdir(exist_ok=True)
    for name, url in LEAFLET_FILES.items():
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            (target / name).write_bytes(response.read())
        print("Téléchargé :", target / name)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deliveryopt", description="Optimisation des tournées de livraison")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="démarre le serveur web")
    s.add_argument("--host", default=os.environ.get("DELIVERYOPT_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.environ.get("DELIVERYOPT_PORT", "8000")))
    s.set_defaults(func=cmd_serve)
    u = sub.add_parser("create-user", help="crée un utilisateur")
    u.add_argument("username")
    u.add_argument("--role", choices=["admin", "operateur"], default="operateur")
    u.set_defaults(func=cmd_create_user)
    p = sub.add_parser("plan", help="planifie un fichier CSV de colis (sans serveur)")
    p.add_argument("csv")
    p.add_argument("--out", help="écrit le plan complet en JSON")
    p.add_argument("--date")
    p.add_argument("--depot", help="latitude,longitude du dépôt")
    p.set_defaults(func=cmd_plan)
    b = sub.add_parser("benchmark", help="compare le moteur à des méthodes simples")
    b.add_argument("--n", type=int, default=40)
    b.add_argument("--seeds", type=int, default=5)
    b.add_argument("--time-limit", type=float, default=4.0)
    b.set_defaults(func=cmd_benchmark)
    v = sub.add_parser("vendor-leaflet", help="télécharge Leaflet en local (nécessite Internet)")
    v.set_defaults(func=cmd_vendor_leaflet)
    args = parser.parse_args(argv)
    return args.func(args)
