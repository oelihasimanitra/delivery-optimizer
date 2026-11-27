"""Tests de propriété : invariants vérifiés sur des centaines de tournées aléatoires (graine fixe)."""

import random

import pytest

from deliveryopt import Settings, summarize_route

from helpers import line_matrix

EPS = 1e-6


def random_case(rng: random.Random):
    n = rng.randint(1, 20)
    positions = {f"S{i}": rng.uniform(0, rng.choice([5, 15, 40])) for i in range(n)}
    positions["DEPOT"] = rng.uniform(0, 40)
    order = list(positions)
    order.remove("DEPOT")
    rng.shuffle(order)
    return positions, order


@pytest.mark.parametrize("seed", range(300))
def test_invariants(seed):
    rng = random.Random(seed)
    positions, order = random_case(rng)
    settings = Settings(
        max_leg_threshold_km=rng.choice([None, 4.0, 5.0, 8.0]),
        include_depot_leg_in_mean=rng.choice([False, True]),
    )
    m = line_matrix(positions)
    s = summarize_route(order, m, settings, depot="DEPOT")

    # Chaque arrêt a exactement un tarif ; rien ne disparaît, rien n'est doublé.
    assert [p.address_id for p in s.stops] == order
    assert set(s.group_ids) | set(s.distant_ids) == set(order)
    assert not set(s.group_ids) & set(s.distant_ids)

    # Le groupe n'est jamais vide.
    assert len(s.group_ids) >= 1

    # Une fois les adresses éloignées retirées, la moyenne respecte le seuil (sauf groupe d'un seul arrêt).
    # Un trajet trop long peut subsister seulement si la tournée est multi-zones (alerte).
    if len(s.group_ids) >= 2:
        legs = [m.dist(a, b) for a, b in zip(s.group_ids, s.group_ids[1:])]
        if settings.include_depot_leg_in_mean:
            legs = [m.dist("DEPOT", s.group_ids[0])] + legs
        assert sum(legs) / len(legs) <= settings.mean_leg_threshold_km + EPS
        if settings.max_leg_threshold_km is not None and max(legs) > settings.max_leg_threshold_km + EPS:
            assert "TOURNEE_MULTI_ZONES" in s.alerts

    # Tarifs cohérents.
    for stop in s.stops:
        if stop.is_distant:
            assert stop.billable_km is not None and stop.billable_km >= 0
            assert stop.price_ar >= settings.distant_waiting_fee_ar
            nearest = min(m.dist(g, stop.address_id) for g in s.group_ids)
            assert stop.billable_km == pytest.approx(nearest)
        else:
            assert stop.price_ar == settings.flat_price_ar
    assert s.revenue_ar == sum(p.price_ar for p in s.stops)

    # Distances et coût : pas d'erreur mathématique.
    expected_km = m.dist("DEPOT", order[0]) + sum(m.dist(a, b) for a, b in zip(order, order[1:]))
    assert s.total_distance_km == pytest.approx(expected_km)
    assert abs(s.cost_ar - expected_km * settings.cost_per_km_ar) <= 0.5 + EPS
    assert s.margin_ar == s.revenue_ar - s.cost_ar

    # Déterminisme.
    assert summarize_route(order, m, settings, depot="DEPOT") == s
