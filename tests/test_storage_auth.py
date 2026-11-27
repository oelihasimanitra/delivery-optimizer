"""Stockage SQLite, mots de passe, jetons, limitation des tentatives, paramètres."""

import time

import pytest

from deliveryopt import auth
from deliveryopt.config import AppSettings, OptimizerSettings, Settings
from deliveryopt.storage import Storage


def test_password_hash_is_salted_and_verifiable():
    h1, h2 = auth.hash_password("un-bon-mot-de-passe"), auth.hash_password("un-bon-mot-de-passe")
    assert h1 != h2 and h1.startswith("scrypt$") and "un-bon-mot-de-passe" not in h1
    assert auth.verify_password("un-bon-mot-de-passe", h1)
    assert not auth.verify_password("autre-mot-de-passe", h1)


@pytest.mark.parametrize("stored", ["", "n'importe quoi", "bcrypt$1$2$3$aa$bb", "scrypt$x$y$z$zz$zz"])
def test_verify_password_rejects_malformed_hashes(stored):
    assert auth.verify_password("whatever-123", stored) is False


def test_short_password_refused():
    with pytest.raises(ValueError):
        auth.hash_password("court")


def test_token_is_random_and_only_hash_is_stored():
    (t1, h1), (t2, h2) = auth.new_token(), auth.new_token()
    assert t1 != t2 and len(t1) >= 40 and h1 == auth.hash_token(t1) and h1 != t1


def test_login_throttle_blocks_after_five_failures_and_resets(monkeypatch):
    th = auth.LoginThrottle()
    for _ in range(4):
        th.failure("bob")
    assert th.blocked_for("bob") == 0
    th.failure("bob")
    assert 0 < th.blocked_for("bob") <= auth.LOCK_SECONDS
    assert th.blocked_for("alice") == 0  # par identifiant
    th.success("bob")
    assert th.blocked_for("bob") == 0


def test_login_throttle_expires():
    th = auth.LoginThrottle()
    for _ in range(5):
        th.failure("bob")
    th._state["bob"] = (5, time.time() - 1)
    assert th.blocked_for("bob") == 0
    th.failure("bob")  # nouveau cycle : le compteur repart de 1
    assert th.blocked_for("bob") == 0


@pytest.fixture()
def db(tmp_path):
    return Storage(tmp_path / "sub" / "t.db")  # crée aussi le sous-dossier


def test_users_crud_and_role_constraint(db):
    db.add_user("a", "h", "admin")
    assert db.count_users() == 1 and db.get_user("a")["role"] == "admin"
    with pytest.raises(Exception):
        db.add_user("a", "h", "admin")  # doublon
    with pytest.raises(Exception):
        db.add_user("b", "h", "root")  # rôle invalide
    db.set_password("a", "h2")
    assert db.get_user("a")["password_hash"] == "h2"
    assert db.list_users() == [{"username": "a", "role": "admin"}]
    db.delete_user("a")
    assert db.get_user("a") is None


def test_sessions_expire_and_cascade_on_user_delete(db):
    db.add_user("a", "h", "operateur")
    db.add_session("tok", "a", time.time() + 100)
    assert db.get_session_user("tok")["username"] == "a"
    db.add_session("old", "a", time.time() - 1)
    assert db.get_session_user("old") is None
    db.delete_session("tok")
    assert db.get_session_user("tok") is None
    db.add_session("tok2", "a", time.time() + 100)
    db.delete_user("a")
    assert db.get_session_user("tok2") is None


def test_settings_default_roundtrip_and_validation(db):
    assert db.load_settings() == AppSettings()
    s = AppSettings(pricing=Settings(flat_price_ar=4500), optimizer=OptimizerSettings(max_drivers=4))
    db.save_settings(s)
    assert db.load_settings() == s
    with pytest.raises((ValueError, TypeError)):
        AppSettings.from_dict({"pricing": {"flat_price_ar": -5}})


def test_plans_store_and_list(db):
    pid = db.add_plan("a", "Plan test", "2026-11-24", [{"id_colis": "X"}], {"totals": {"drivers": 1}})
    got = db.get_plan(pid)
    assert got["input"] == [{"id_colis": "X"}] and got["result"]["totals"]["drivers"] == 1
    assert db.list_plans()[0]["id"] == pid and db.get_plan(999) is None


def test_geocode_cache(db):
    assert db.get_geocode("x") is None
    db.put_geocode("x", [{"lat": 1, "lon": 2}])
    assert db.get_geocode("x") == [{"lat": 1, "lon": 2}]


def test_data_persists_across_connections(tmp_path):
    path = tmp_path / "p.db"
    Storage(path).add_user("a", "h", "admin")
    assert Storage(path).get_user("a") is not None
