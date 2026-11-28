"""API HTTP réelle : sécurité, droits, cycle complet d'un plan, export CSV, statiques."""

import json
import urllib.request

import pytest

from deliveryopt.server import plan_to_csv

from support import Client, offset, parcel

ROWS = [parcel("A", *offset(0, 2)), parcel("B", *offset(1, 3)), parcel("C", *offset(0, 25))]


def logged(base, user="admin", pw="motdepasse-admin"):
    c = Client(base)
    status, body, _ = c.login(user, pw)
    assert status == 200, body
    return c


def test_health_is_public(live_server):
    base, _ = live_server
    status, body, headers = Client(base).request("GET", "/api/health")
    assert status == 200 and body["ok"] is True
    assert "default-src 'self'" in headers["Content-Security-Policy"] and headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("method,path", [("GET", "/api/me"), ("GET", "/api/plans"), ("GET", "/api/settings"), ("POST", "/api/plans"), ("GET", "/api/users")])
def test_api_requires_login(live_server, method, path):
    base, _ = live_server
    status, body, _ = Client(base).request(method, path, {} if method == "POST" else None)
    assert status == 401 and body["error"] == "NON_CONNECTE"


def test_login_ok_sets_secure_flags_and_me(live_server):
    base, _ = live_server
    c = Client(base)
    status, body, headers = c.login("admin", "motdepasse-admin")
    cookie = headers["Set-Cookie"]
    assert status == 200 and body["username"] == "admin" and body["role"] == "admin"
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    status, me, _ = c.request("GET", "/api/me")
    assert status == 200 and me["username"] == "admin" and me["routing_mode"] == "estimate" and me["billing_reliable"] is False
    # Régression : la réponse de login doit porter les mêmes champs que /api/me. Sinon l'interface, qui s'en sert
    # juste après la connexion, n'a pas billing_reliable et affiche à tort « MODE ESTIMATION » même avec OSRM.
    assert body == me


def test_login_reports_reliable_routing_when_osrm_is_configured(live_server):
    """Bug constaté à l'essai de la release Windows : avec OSRM actif, l'interface affichait « MODE ESTIMATION »
    après la connexion, car login ne renvoyait pas billing_reliable."""
    from support import GridProvider

    base, ctx = live_server
    ctx.provider = GridProvider()  # présenté comme routier (mode « osrm », fiable)
    status, body, _ = Client(base).login("admin", "motdepasse-admin")
    assert status == 200 and body["routing_mode"] == "osrm" and body["billing_reliable"] is True


def test_login_wrong_password_and_throttle(live_server):
    base, _ = live_server
    c = Client(base)
    for _ in range(5):
        status, body, _ = c.login("oper", "mauvais-mot-de-passe")
        assert status == 401 and body["error"] == "IDENTIFIANTS_INVALIDES"
    status, body, _ = c.login("oper", "motdepasse-oper")  # même le bon mot de passe est bloqué
    assert status == 429 and body["error"] == "TROP_DE_TENTATIVES"
    # un autre identifiant n'est pas affecté
    assert Client(base).login("admin", "motdepasse-admin")[0] == 200


def test_unknown_user_gets_same_error(live_server):
    base, _ = live_server
    status, body, _ = Client(base).login("fantome", "motdepasse-x")
    assert status == 401 and body["message"] == "Identifiant ou mot de passe incorrect."


def test_logout_invalidates_session(live_server):
    base, _ = live_server
    c = logged(base)
    assert c.request("POST", "/api/logout", {})[0] == 200
    assert c.request("GET", "/api/me")[0] == 401


def test_foreign_origin_and_non_json_rejected(live_server):
    base, _ = live_server
    c = logged(base)
    status, body, _ = c.request("POST", "/api/plans", {"parcels": ROWS}, headers={"Origin": "http://evil.example"})
    assert status == 403 and body["error"] == "ORIGINE_REFUSEE"
    req = urllib.request.Request(base + "/api/login", data=b"username=a&password=b", method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 415


def test_invalid_json_and_oversized_body(live_server):
    base, _ = live_server
    c = logged(base)
    assert c.request("POST", "/api/plans", b"{pas du json")[0] == 400
    assert c.request("POST", "/api/plans", b"[1,2]")[0] == 400
    assert c.request("POST", "/api/plans", {"parcels": "texte"})[0] == 422
    assert c.request("POST", "/api/plans", {"parcels": [1, 2]})[0] == 422


def test_operator_cannot_use_admin_routes(live_server):
    base, _ = live_server
    c = logged(base, "oper", "motdepasse-oper")
    assert c.request("GET", "/api/users")[0] == 403
    assert c.request("PUT", "/api/settings", {})[0] == 403
    assert c.request("POST", "/api/users", {"username": "zzz", "password": "motdepasse-1"})[0] == 403
    assert c.request("GET", "/api/settings")[0] == 200  # lecture autorisée


def test_full_plan_lifecycle_and_csv_export(live_server):
    base, _ = live_server
    c = logged(base, "oper", "motdepasse-oper")
    status, body, _ = c.request("POST", "/api/plans", {"parcels": ROWS, "date": "2026-11-24", "label": "Test"})
    assert status == 201 and body["label"] == "Test"
    plan = body["result"]
    assert plan["verification_errors"] == [] and plan["billing_reliable"] is False  # provider d'estimation
    assert {pid for r in plan["routes"] for s in r["stops"] for pid in s["parcel_ids"]} == {"A", "B", "C"}
    pid = body["id"]
    assert c.request("GET", "/api/plans")[1]["plans"][0]["id"] == pid
    got = c.request("GET", f"/api/plans/{pid}")[1]
    assert got["input"][0]["id_colis"] == "A" and got["result"]["totals"] == plan["totals"]
    status, raw, headers = c.request("GET", f"/api/plans/{pid}/export.csv", raw=True)
    assert status == 200 and headers["Content-Type"].startswith("text/csv") and "attachment" in headers["Content-Disposition"]
    text = raw.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("livreur;ordre;adresse") and "Adresse A" in text
    assert c.request("GET", "/api/plans/99999")[0] == 404
    assert c.request("GET", "/api/plans/abc")[0] == 404


def test_plan_with_rejected_rows_is_returned_not_failed(live_server):
    base, _ = live_server
    c = logged(base)
    status, body, _ = c.request("POST", "/api/plans", {"parcels": [parcel("OK", *offset(0, 2)), parcel("NOGPS", None, None)]})
    assert status == 201 and [r["code"] for r in body["result"]["rejected"]] == ["ADRESSE_NON_LOCALISEE"]


def test_too_many_parcels_gives_clear_error(live_server):
    base, _ = live_server
    c = logged(base)
    status, body, _ = c.request("POST", "/api/plans", {"parcels": [parcel(f"P{i}", *offset(0, 1)) for i in range(501)]})
    assert status == 503 and body["error"] == "PLANIFICATION_IMPOSSIBLE"


def test_settings_update_by_admin_applies_to_next_plan(live_server):
    base, ctx = live_server
    c = logged(base)
    s = c.request("GET", "/api/settings")[1]
    s["pricing"]["flat_price_ar"] = 5000
    assert c.request("PUT", "/api/settings", s)[0] == 200
    plan = c.request("POST", "/api/plans", {"parcels": [parcel("A", *offset(0, 2))]})[1]["result"]
    assert plan["routes"][0]["stops"][0]["price_ar"] == 5000
    s["pricing"]["flat_price_ar"] = -1
    status, body, _ = c.request("PUT", "/api/settings", s)
    assert status == 422 and body["error"] == "PARAMETRES_INVALIDES"
    assert ctx.storage.load_settings().pricing.flat_price_ar == 5000  # inchangé


def test_user_management(live_server):
    base, _ = live_server
    c = logged(base)
    assert c.request("POST", "/api/users", {"username": "nouveau", "password": "motdepasse-n", "role": "operateur"})[0] == 201
    assert c.request("POST", "/api/users", {"username": "nouveau", "password": "motdepasse-n"})[0] == 409
    assert c.request("POST", "/api/users", {"username": "x y", "password": "motdepasse-n"})[0] == 422
    assert c.request("POST", "/api/users", {"username": "court1", "password": "abc"})[0] == 422
    assert c.request("POST", "/api/users", {"username": "role1", "password": "motdepasse-n", "role": "root"})[0] == 422
    assert {u["username"] for u in c.request("GET", "/api/users")[1]["users"]} == {"admin", "oper", "nouveau"}
    assert c.request("DELETE", "/api/users/admin")[0] == 409  # pas de suicide administratif
    assert c.request("DELETE", "/api/users/nouveau")[0] == 200
    assert c.request("DELETE", "/api/users/nouveau")[0] == 404
    assert Client(base).login("nouveau", "motdepasse-n")[0] == 401


def test_change_password(live_server):
    base, _ = live_server
    c = logged(base, "oper", "motdepasse-oper")
    assert c.request("POST", "/api/password", {"old_password": "faux", "new_password": "nouveau-mdp-1"})[0] == 403
    assert c.request("POST", "/api/password", {"old_password": "motdepasse-oper", "new_password": "abc"})[0] == 422
    assert c.request("POST", "/api/password", {"old_password": "motdepasse-oper", "new_password": "nouveau-mdp-1"})[0] == 200
    assert Client(base).login("oper", "motdepasse-oper")[0] == 401
    assert Client(base).login("oper", "nouveau-mdp-1")[0] == 200


def test_geocode_not_configured_is_explicit(live_server):
    base, _ = live_server
    c = logged(base)
    status, body, _ = c.request("POST", "/api/geocode", {"address": "Analakely"})
    assert status == 503 and body["error"] == "GEOCODAGE_NON_CONFIGURE"


def test_geocode_with_fake_nominatim_and_cache(live_server, tmp_path):
    from deliveryopt.geocoding import NominatimGeocoder

    from support import FakeHTTP

    fake = FakeHTTP(lambda path, h: (200, [{"lat": "-18.9", "lon": "47.52", "display_name": "Analakely, Antananarivo", "type": "suburb", "class": "place"}]))
    base, ctx = live_server
    try:
        ctx.geocoder = NominatimGeocoder(fake.url, "test-agent", min_interval_s=0)
        c = logged(base)
        first = c.request("POST", "/api/geocode", {"address": "Analakely"})[1]
        second = c.request("POST", "/api/geocode", {"address": "  ANALAKELY "})[1]
        assert first["results"] and first["results"] == second["results"]
        assert len(fake.requests) == 1  # le second appel vient du cache
        assert c.request("POST", "/api/geocode", {"address": " "})[0] == 422
    finally:
        fake.close()


def test_static_files_and_path_traversal(live_server):
    base, _ = live_server
    c = Client(base)
    status, body, headers = c.request("GET", "/", raw=True)
    assert status == 200 and headers["Content-Type"].startswith("text/html") and b"<html" in body.lower()
    assert c.request("GET", "/static/app.js", raw=True)[0] == 200
    assert c.request("GET", "/static/../server.py", raw=True)[0] == 404
    assert c.request("GET", "/static/%2e%2e/server.py", raw=True)[0] == 404
    assert c.request("GET", "/../../etc/passwd", raw=True)[0] == 404
    assert c.request("POST", "/", {}, raw=True)[0] == 405
    assert c.request("GET", "/api/inconnu")[0] == 404


def test_xss_payload_is_stored_verbatim_never_interpreted(live_server):
    base, _ = live_server
    c = logged(base)
    evil = "<img src=x onerror=alert(1)>"
    plan = c.request("POST", "/api/plans", {"parcels": [parcel("X1", *offset(0, 2), adresse=evil)]})[1]["result"]
    assert plan["routes"][0]["stops"][0]["address"] == evil  # donnée brute ; l'interface utilise textContent


def test_csv_injection_is_neutralised():
    plan = {
        "routes": [{"driver": 1, "stops": [{"order": 1, "address": "=HYPERLINK(\"http://x\")", "parcel_ids": ["A"], "arrival": "08:10", "service_start": "08:10", "departure": "08:15", "leg_km": 1.5, "price_ar": 4000, "is_distant": False, "price_explanation": "+cmd|' /C calc'!A0"}]}],
        "unassigned": [{"address": "@SUM(1)", "parcel_ids": ["B"], "reason": "-2+3"}],
        "rejected": [{"parcel_id": "=1+1", "message": "ok"}],
    }
    lines = plan_to_csv(plan).splitlines()
    joined = "\n".join(lines)
    assert "'=HYPERLINK" in joined and "'+cmd" in joined and "'@SUM" in joined and "'-2+3" in joined and "'=1+1" in joined
    assert "1,5" in lines[1]  # décimale française


def test_concurrent_plans_do_not_break(live_server):
    import threading

    base, _ = live_server
    results = []

    def work():
        c = logged(base)
        results.append(c.request("POST", "/api/plans", {"parcels": ROWS})[0])

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == [201] * 4


def test_error_never_leaks_traceback(live_server, monkeypatch):
    base, ctx = live_server
    c = logged(base)
    monkeypatch.setattr(ctx.storage, "list_plans", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret interne")))
    status, body, _ = c.request("GET", "/api/plans")
    assert status == 500 and "secret" not in json.dumps(body) and body["error"] == "ERREUR_INTERNE"


def test_keepalive_connection_survives_unread_body_and_errors(live_server):
    """Régression : un POST dont la route n'utilise pas le corps (déconnexion) ou rejeté avant lecture
    (401) ne doit pas corrompre la requête suivante sur la même connexion persistante."""
    import http.client

    base, _ = live_server
    host, port = base.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    hdr = {"Content-Type": "application/json"}
    conn.request("POST", "/api/plans", body=b'{"parcels": []}', headers=hdr)  # 401 sans lecture du corps
    r = conn.getresponse(); r.read()
    assert r.status == 401
    conn.request("POST", "/api/login", body=json.dumps({"username": "admin", "password": "motdepasse-admin"}), headers=hdr)
    r = conn.getresponse(); r.read()
    assert r.status == 200
    cookie = r.getheader("Set-Cookie").split(";")[0]
    conn.request("POST", "/api/logout", body=b"{}", headers={**hdr, "Cookie": cookie})  # route qui ignore le corps
    r = conn.getresponse(); r.read()
    assert r.status == 200
    conn.request("GET", "/api/health")  # même connexion
    r = conn.getresponse()
    assert r.status == 200 and json.loads(r.read())["ok"] is True
    # Corps trop gros : le serveur répond 413 et coupe la connexion ; selon le timing, le client voit la
    # réponse ou une connexion coupée en cours d'envoi. Dans les deux cas rien n'est traité.
    try:
        conn.request("POST", "/api/plans", body=b"x" * (5 * 1024 * 1024 + 10), headers=hdr)
        r = conn.getresponse(); r.read()
        assert r.status == 413
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, http.client.RemoteDisconnected):
        # ConnectionAbortedError (WinError 10053) : forme que prend la coupure sous Windows.
        pass
    finally:
        conn.close()
    status, body, _ = Client(base).request("GET", "/api/health")  # le serveur reste en vie
    assert status == 200
