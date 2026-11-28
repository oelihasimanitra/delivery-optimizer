"""Ligne de commande : plan sur CSV, création d'utilisateur, fabrique de fournisseurs, démarrage réel du serveur."""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from deliveryopt import cli
from deliveryopt.routing import EstimateProvider, OSRMProvider
from deliveryopt.storage import Storage

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "src" / "deliveryopt" / "static" / "demo.csv"


def test_make_provider_defaults_to_explicit_estimate():
    p = cli.make_provider({})
    assert isinstance(p, EstimateProvider) and p.reliable is False
    q = cli.make_provider({"DELIVERYOPT_OSRM_URL": "http://osrm:5000"})
    assert isinstance(q, OSRMProvider) and q.reliable is True


def test_make_geocoder_rules():
    assert cli.make_geocoder({}) is None
    with pytest.raises(SystemExit):
        cli.make_geocoder({"DELIVERYOPT_NOMINATIM_URL": "https://nominatim.openstreetmap.org"})  # User-Agent obligatoire
    g = cli.make_geocoder({"DELIVERYOPT_NOMINATIM_URL": "https://nominatim.openstreetmap.org", "DELIVERYOPT_USER_AGENT": "app (a@b.mg)"})
    assert g.min_interval_s == 1.0
    assert cli.make_geocoder({"DELIVERYOPT_NOMINATIM_URL": "http://nominatim:8080"}).min_interval_s == 0.0


def test_read_csv_semicolon_and_comma(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("﻿id_colis;adresse\nA;Rue 1, Tana\n", encoding="utf-8")
    b.write_text("id_colis,adresse\nB,Rue 2\n", encoding="utf-8")
    assert cli.read_parcels_csv(str(a)) == [{"id_colis": "A", "adresse": "Rue 1, Tana"}]
    assert cli.read_parcels_csv(str(b)) == [{"id_colis": "B", "adresse": "Rue 2"}]


def test_plan_command_on_demo_csv(tmp_path, capsys):
    out = tmp_path / "plan.json"
    code = cli.main(["plan", str(DEMO), "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0 and "Vérification indépendante : OK" in text
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert plan["routing_mode"] == "estimate" and plan["totals"]["parcels_planned"] >= 10
    assert any("[critique]" in line for line in text.splitlines())  # l'estimation est signalée


def test_create_user_command(tmp_path, monkeypatch, capsys):
    db = tmp_path / "u.db"
    monkeypatch.setenv("DELIVERYOPT_DB", str(db))
    monkeypatch.setenv("DELIVERYOPT_PASSWORD", "motdepasse-long")
    assert cli.main(["create-user", "marie", "--role", "admin"]) == 0
    assert Storage(db).get_user("marie")["role"] == "admin"
    assert cli.main(["create-user", "marie"]) == 2  # doublon
    monkeypatch.setenv("DELIVERYOPT_PASSWORD", "court")
    assert cli.main(["create-user", "paul"]) == 2


def test_benchmark_command(capsys):
    assert cli.main(["benchmark", "--n", "12", "--seeds", "1", "--time-limit", "1"]) == 0
    assert "optimisé" in capsys.readouterr().out


def test_serve_without_user_refuses(tmp_path):
    env = {**os.environ, "DELIVERYOPT_DB": str(tmp_path / "x.db"), "PYTHONPATH": str(ROOT / "src")}
    env.pop("DELIVERYOPT_ADMIN_USER", None)
    env.pop("DELIVERYOPT_ADMIN_PASSWORD", None)
    r = subprocess.run([sys.executable, str(ROOT / "run.py"), "serve", "--port", "0"], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "Aucun utilisateur" in r.stderr


def test_serve_real_process_end_to_end(tmp_path):
    port = 18765
    env = {**os.environ, "DELIVERYOPT_DB": str(tmp_path / "s.db"), "DELIVERYOPT_ADMIN_USER": "root", "DELIVERYOPT_ADMIN_PASSWORD": "motdepasse-root", "PYTHONPATH": str(ROOT / "src")}
    proc = subprocess.Popen([sys.executable, str(ROOT / "run.py"), "serve", "--port", str(port)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(50):
            try:
                body = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("le serveur n'a pas démarré")
        assert json.loads(body)["ok"] is True
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read()
        assert b"<html" in page.lower()
    finally:
        proc.terminate()
        _, err = proc.communicate(timeout=10)
    assert "ESTIMATION" in err  # avertissement affiché au démarrage
