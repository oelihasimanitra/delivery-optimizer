"""Scénarios métier A à J du cahier des charges, plus propriétés globales. Chaque plan est aussi
contrôlé par le vérificateur indépendant (verify_plan)."""

import random

import pytest

from deliveryopt.benchmark import compare, synthetic_rows
from deliveryopt.config import AppSettings, OptimizerSettings, Settings
from deliveryopt.planner import run_plan
from deliveryopt.routing import EstimateProvider
from deliveryopt.verify import verify_plan

from support import DEPOT, GridProvider, offset, parcel

FAST = OptimizerSettings(time_limit_s=3.0)
APP = AppSettings(optimizer=FAST)


def plan(rows, provider=None, app=APP):
    result = run_plan(rows, provider or GridProvider(), app, "2026-11-24")
    assert verify_plan(result.plan, rows, app) == []
    return result.plan


def ids_in_order(route):
    return [pid for s in route["stops"] for pid in s["parcel_ids"]]


def all_planned(p):
    return {pid for r in p["routes"] for s in r["stops"] for pid in s["parcel_ids"]}


def test_A_five_clients_same_zone_one_short_coherent_route():
    rows = [parcel(f"A{i}", *offset(0.3 * i, 3 + 0.2 * i)) for i in range(5)]
    p = plan(rows)
    assert p["totals"]["drivers"] == 1 and len(all_planned(p)) == 5
    assert p["totals"]["distance_km"] < 6 and p["totals"]["distant_addresses"] == 0
    assert p["totals"]["revenue_ar"] == 5 * 4000
    assert not p["unassigned"] and not p["rejected"]


def test_B_two_zones_are_visited_zone_by_zone_not_interleaved():
    zone1 = [parcel(f"N{i}", *offset(6 + 0.2 * i, 0.3 * i)) for i in range(5)]
    zone2 = [parcel(f"E{i}", *offset(0.2 * i, 12 + 0.3 * i)) for i in range(5)]
    rows = [r for pair in zip(zone1, zone2) for r in pair]  # saisie mélangée
    p = plan(rows)
    assert p["totals"]["drivers"] == 1
    sequence = [pid[0] for pid in ids_in_order(p["routes"][0])]
    changes = sum(1 for a, b in zip(sequence, sequence[1:]) if a != b)
    assert changes == 1  # une seule transition entre les deux zones
    assert any(a["code"] == "TOURNEE_MULTI_ZONES" for a in p["routes"][0]["alerts"])
    assert p["totals"]["distant_addresses"] == 0  # deux groupes cohérents, pas d'adresse éloignée


def test_C_isolated_far_client_is_identified_and_priced():
    rows = [parcel(f"A{i}", *offset(0.3 * i, 2 + 0.2 * i)) for i in range(5)] + [parcel("FAR", *offset(0, 25))]
    p = plan(rows)
    stops = {s["parcel_ids"][0]: s for r in p["routes"] for s in r["stops"]}
    far = stops["FAR"]
    assert far["is_distant"] and p["totals"]["distant_addresses"] == 1
    assert far["billable_km"] > 15
    assert far["price_ar"] == round(round(far["billable_km"], 1) * 1000) + 1000
    assert "Adresse éloignée" in far["price_explanation"]
    assert all(not s["is_distant"] and s["price_ar"] == 4000 for pid, s in stops.items() if pid != "FAR")


def test_D_three_zones_three_drivers_each_zone_to_one_driver():
    app = AppSettings(optimizer=OptimizerSettings(time_limit_s=4.0, max_parcels_per_driver=8))
    centers = [offset(6, 0), offset(0, 7), offset(-6, -1)]
    rows = [parcel(f"Z{z}-{i}", c[0] + 0.002 * i, c[1] + 0.002 * (i % 3)) for i in range(8) for z, c in enumerate(centers)]
    random.Random(1).shuffle(rows)
    p = plan(rows, app=app)
    assert p["totals"]["drivers"] == 3 and not p["unassigned"]
    for r in p["routes"]:
        assert r["parcel_count"] <= 8
        assert len({pid.split("-")[0] for pid in ids_in_order(r)}) == 1, "chaque livreur doit garder une seule zone"


def test_E_deadline_respected_when_possible():
    rows = [parcel("NEAR", *offset(0, 2)), parcel("WEST", *offset(0, -4)), parcel("URGENT", *offset(0, 8), heure_max="08:30")]
    p = plan(rows)
    urgent = next(s for r in p["routes"] for s in r["stops"] if "URGENT" in s["parcel_ids"])
    assert urgent["service_start"] <= "08:30"
    assert "Contrainte horaire" in " ".join(urgent["why_order"]) or "heure" in " ".join(urgent["why_order"]).lower()


def test_E_impossible_deadline_is_reported_with_reason():
    rows = [parcel("OK", *offset(0, 2)), parcel("TOOFAR", *offset(0, 40), heure_max="08:10")]
    p = plan(rows)
    assert all_planned(p) == {"OK"}
    rej = next(r for r in p["rejected"] if r["parcel_id"] == "TOOFAR")
    assert rej["code"] == "CONTRAINTE_IMPOSSIBLE" and "heure limite" in rej["message"] and "08:10" in rej["message"]
    assert any(a["code"] == "COLIS_ECARTES" for a in p["alerts"])


def test_E_window_waiting_is_reported():
    rows = [parcel("LATE", *offset(0, 2), heure_min="10:00", heure_max="11:00")]
    p = plan(rows)
    stop = p["routes"][0]["stops"][0]
    assert stop["service_start"] == "10:00" and stop["wait_min"] > 90
    assert any(a["code"] == "ATTENTE_IMPORTANTE" for a in p["routes"][0]["alerts"])


def test_F_dependency_a_before_b_same_driver_even_if_b_is_closer():
    rows = [parcel("B", *offset(0, 1), apres_colis="A"), parcel("A", *offset(0, 6)), parcel("C", *offset(0, -3))]
    p = plan(rows)
    route = next(r for r in p["routes"] if "A" in ids_in_order(r))
    order = ids_in_order(route)
    assert "B" in order and order.index("A") < order.index("B")
    b = next(s for s in route["stops"] if "B" in s["parcel_ids"])
    assert any("après" in line for line in b["why_order"])


def test_G_incorrect_addresses_are_identified():
    rows = [parcel("OK", *offset(0, 2)), parcel("NOGPS", None, None), parcel("PARIS", 48.8566, 2.3522), parcel("BADTIME", *offset(0, 3), heure_max="midi")]
    p = plan(rows)
    codes = {r["parcel_id"]: r["code"] for r in p["rejected"]}
    assert codes == {"NOGPS": "ADRESSE_NON_LOCALISEE", "PARIS": "COORDONNEES_HORS_MADAGASCAR", "BADTIME": "DONNEE_INVALIDE"}
    assert all_planned(p) == {"OK"}


def test_H_unreachable_address_is_not_pretended_reachable():
    island = offset(0, 6)
    rows = [parcel("OK", *offset(0, 2)), parcel("ISLAND", *island)]
    p = plan(rows, GridProvider(blocked_from_depot=[island]))
    rej = next(r for r in p["rejected"] if r["parcel_id"] == "ISLAND")
    assert rej["code"] == "ROUTE_INACCESSIBLE" and "ne suppose pas" in rej["message"]
    assert all_planned(p) == {"OK"}


def test_H_blocked_pair_between_stops_is_never_used():
    q, pt, r = offset(0, 2), offset(0, 4), offset(0, 6)
    rows = [parcel("Q", *q), parcel("P", *pt), parcel("R", *r)]
    p = plan(rows, GridProvider(blocked_pairs=[(q, r)]))
    order = ids_in_order(p["routes"][0])
    assert set(order) == {"Q", "P", "R"}
    assert abs(order.index("Q") - order.index("R")) != 1


def test_I_same_address_is_one_stop_one_price():
    here = offset(2, 2)
    rows = [parcel("P1", *here, duree_remise_min=3), parcel("P2", *here, duree_remise_min=4), parcel("P3", *here, duree_remise_min=5), parcel("OTHER", *offset(0, 3))]
    p = plan(rows)
    stops = [s for r in p["routes"] for s in r["stops"]]
    shared = next(s for s in stops if "P1" in s["parcel_ids"])
    assert shared["parcel_ids"] == ["P1", "P2", "P3"] and shared["price_ar"] == 4000 and shared["service_min"] == 12
    assert len(stops) == 2 and p["totals"]["revenue_ar"] == 8000


def test_J_no_driver_available_means_no_artificial_assignment():
    app = AppSettings(optimizer=OptimizerSettings(max_drivers=0, time_limit_s=1))
    rows = [parcel("A", *offset(0, 2)), parcel("B", *offset(0, 3))]
    p = plan(rows, app=app)
    assert p["routes"] == [] and {pid for u in p["unassigned"] for pid in u["parcel_ids"]} == {"A", "B"}
    assert all("Aucun livreur" in u["reason"] for u in p["unassigned"])
    assert any(a["code"] == "AUCUN_LIVREUR" for a in p["alerts"])


def test_capacity_of_20_parcels_is_strict():
    rows = [parcel(f"P{i}", *offset(0.05 * i, 2 + 0.03 * i)) for i in range(25)]
    p = plan(rows)
    assert len(p["routes"]) >= 2 and all(r["parcel_count"] <= 20 for r in p["routes"])
    assert len(all_planned(p)) == 25


def test_end_of_day_forces_unassigned_with_reason():
    app = AppSettings(optimizer=OptimizerSettings(max_drivers=1, day_end="12:00", time_limit_s=2))
    rows = [parcel(f"P{i}", *offset(0.1 * i, 2), duree_remise_min=100) for i in range(5)]
    p = plan(rows, app=app)
    assert p["unassigned"] and any("fin de journée" in u["reason"] for u in p["unassigned"])
    assert any(a["code"] == "COLIS_NON_ATTRIBUES" for a in p["alerts"])


def test_estimate_mode_is_never_silent():
    rows = [parcel("A", *offset(0, 2)), parcel("B", *offset(0, 3))]
    p = plan(rows, EstimateProvider())
    assert p["routing_mode"] == "estimate" and p["billing_reliable"] is False
    assert any(a["code"] == "DISTANCES_ESTIMEES" and a["severity"] == "critique" for a in p["alerts"])


def test_empty_input():
    p = plan([])
    assert p["routes"] == [] and p["totals"]["drivers"] == 0


def test_too_many_parcels_refused():
    from deliveryopt.planner import PlanningError

    with pytest.raises(PlanningError):
        run_plan([parcel(f"P{i}", *offset(0, 1)) for i in range(501)], GridProvider(), APP)


def test_explanations_are_numeric_and_present_for_every_stop():
    rows = synthetic_rows(18, 3)
    p = plan(rows, EstimateProvider())
    for r in p["routes"]:
        for s in r["stops"]:
            assert s["why_assigned"] and s["why_order"] and s["price_explanation"]
            assert any("Ar" in line or "km" in line for line in s["why_assigned"])


@pytest.mark.parametrize("seed", range(12))
def test_random_instances_pass_independent_verification(seed):
    rng = random.Random(seed)
    n = rng.randint(3, 24)
    rows = []
    for i in range(n):
        r = parcel(f"R{i}", *offset(rng.uniform(-8, 8), rng.uniform(-8, 8)))
        if rng.random() < 0.25:
            r["heure_max"] = f"{rng.randint(9, 16)}:00"
        if rng.random() < 0.2:
            r["heure_min"] = f"{rng.randint(8, 13)}:00"
        if rng.random() < 0.15:
            r["priorite"] = rng.choice(["elevee", "urgente"])
        if rng.random() < 0.15 and i > 0:
            r["apres_colis"] = f"R{rng.randint(0, i - 1)}"
        rows.append(r)
    p = plan(rows)  # plan() lance verify_plan : couverture, capacité, horaires, ordre, tarifs
    planned = all_planned(p)
    unplaced = {pid for u in p["unassigned"] for pid in u["parcel_ids"]} | {r["parcel_id"] for r in p["rejected"]}
    assert planned | unplaced == {r["id_colis"] for r in rows} and not planned & unplaced


def test_independent_verifier_detects_tampering():
    rows = [parcel("A", *offset(0, 2)), parcel("B", *offset(0, 4), heure_max="09:00")]
    result = run_plan(rows, GridProvider(), APP)
    good = result.plan
    assert verify_plan(good, rows, APP) == []
    import copy

    bad = copy.deepcopy(good)
    bad["routes"][0]["stops"][0]["price_ar"] += 1000
    assert any("prix" in e for e in verify_plan(bad, rows, APP))
    bad = copy.deepcopy(good)
    bad["routes"][0]["stops"][0]["parcel_ids"].append("GHOST")
    assert verify_plan(bad, rows, APP)
    bad = copy.deepcopy(good)
    bad["routes"][0]["stops"][-1]["service_start"] = "23:00"
    assert verify_plan(bad, rows, APP)
    bad = copy.deepcopy(good)
    bad["rejected"] = []
    bad["routes"][0]["stops"] = bad["routes"][0]["stops"][:1]
    assert any("disparu" in e for e in verify_plan(bad, rows, APP))
    bad = copy.deepcopy(good)
    bad["billing_reliable"] = True
    bad["routing_mode"] = "estimate"
    assert any("estimées" in e for e in verify_plan(bad, rows, APP))


def test_optimizer_beats_simple_methods_on_benchmark():
    wins_distance, total = 0, 0
    for seed in range(1, 6):
        app = AppSettings(optimizer=OptimizerSettings(time_limit_s=2.5))
        result = run_plan(synthetic_rows(30, seed), EstimateProvider(), app)
        table = compare(result, app)
        opt = table["optimisé"]
        assert opt["contraintes_violees"] == 0
        for name, m in table.items():
            if name == "optimisé":
                continue
            total += 1
            wins_distance += opt["distance_km"] <= m["distance_km"] + 1e-6
            assert opt["adresses_eloignees"] <= m["adresses_eloignees"] + 1  # jamais nettement pire sur la qualité des groupes
    assert wins_distance == total, "le moteur doit être au moins aussi bon que chaque méthode simple en distance"


def test_pricing_settings_flow_through_the_plan():
    app = AppSettings(pricing=Settings(flat_price_ar=5000), optimizer=FAST)
    p = plan([parcel("A", *offset(0, 2))], app=app)
    assert p["routes"][0]["stops"][0]["price_ar"] == 5000
