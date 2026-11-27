import pytest

from deliveryopt import Settings, summarize_route
from deliveryopt.route_metrics import mean_leg_km

from helpers import line_matrix


def test_mean_excludes_depot_leg_by_default():
    m = line_matrix({"D": 0, "A": 10, "B": 11, "C": 13})
    assert mean_leg_km(["A", "B", "C"], m) == pytest.approx(1.5)  # (1 + 2) / 2
    assert mean_leg_km(["A", "B", "C"], m, depot="D", include_depot_leg=True) == pytest.approx(13 / 3)


def test_mean_undefined_for_single_stop():
    m = line_matrix({"A": 0})
    assert mean_leg_km(["A"], m) is None


def test_single_stop_route_is_never_distant():
    m = line_matrix({"D": 0, "A": 20})
    s = summarize_route(["A"], m, depot="D")
    assert s.distant_ids == ()
    assert s.stops[0].price_ar == 4000
    assert s.total_distance_km == 20  # le coût interne compte bien le trajet du dépôt
    assert s.cost_ar == 20000


def test_empty_route():
    s = summarize_route([], line_matrix({}))
    assert s.stops == () and s.revenue_ar == 0 and s.cost_ar == 0


def test_duplicate_address_rejected():
    m = line_matrix({"A": 0, "B": 1})
    with pytest.raises(ValueError):
        summarize_route(["A", "B", "A"], m)


def test_close_stops_are_all_in_group():
    # Scénario A : 5 clients dans la même zone -> tournée courte et cohérente, aucun éloigné
    m = line_matrix({"A": 0, "B": 1, "C": 2, "D": 3, "E": 4})
    s = summarize_route(["A", "B", "C", "D", "E"], m)
    assert s.distant_ids == ()
    assert s.raw_mean_km == pytest.approx(1.0)
    assert s.revenue_ar == 5 * 4000
    assert s.alerts == ()


def test_spec_example_mean_rule_alone_misses_an_isolated_detour():
    # Trajets 1,2 / 2 / 1,5 / 1 / 8 km : moyenne 2,74 km <= 3 km, donc la règle de la
    # moyenne seule ne signale personne, alors que le trajet de 8 km coûte 8 000 Ar.
    m = line_matrix({"A": 0, "B": 1.2, "C": 3.2, "D": 4.7, "E": 5.7, "X": 13.7})
    order = ["A", "B", "C", "D", "E", "X"]
    only_mean = summarize_route(order, m, Settings(max_leg_threshold_km=None))
    assert only_mean.raw_mean_km == pytest.approx(2.74)
    assert only_mean.distant_ids == ()


def test_leg_threshold_flags_the_isolated_detour():
    m = line_matrix({"A": 0, "B": 1.2, "C": 3.2, "D": 4.7, "E": 5.7, "X": 13.7})
    s = summarize_route(["A", "B", "C", "D", "E", "X"], m)  # seuil par trajet = 5 km
    assert s.distant_ids == ("X",)
    assert s.group_ids == ("A", "B", "C", "D", "E")
    x = s.stops[-1]
    assert x.is_distant and x.billable_km == pytest.approx(8.0)
    assert x.price_ar == 8 * 1000 + 1000
    assert s.revenue_ar == 5 * 4000 + 9000
    assert "CLIENT_ELOIGNE:X" in s.alerts
    assert s.group_mean_km == pytest.approx(1.425)
    assert "8,0 km" in x.explanation and "9 000 Ar" in x.explanation


def test_mean_rule_triggers_on_short_route():
    # Scénario C : un client très éloigné dans une tournée courte (moyenne 4,5 km > 3 km)
    m = line_matrix({"A": 0, "B": 1, "X": 9})
    s = summarize_route(["A", "B", "X"], m)
    assert s.raw_mean_km == pytest.approx(4.5)
    assert s.distant_ids == ("X",)
    assert "MOYENNE_SUPERIEURE_AU_SEUIL" in s.alerts
    assert s.group_mean_km == pytest.approx(1.0)


def test_outlier_in_the_middle_is_flagged_not_its_neighbours():
    # Ordre A B X C D : X est loin (12 km), ses voisins C et B ne doivent pas être accusés.
    m = line_matrix({"A": 0, "B": 1, "C": 2, "D": 3, "X": 12})
    s = summarize_route(["A", "B", "X", "C", "D"], m)
    assert s.distant_ids == ("X",)
    assert s.group_ids == ("A", "B", "C", "D")
    # distance facturable : depuis l'arrêt du groupe le plus proche (D, à 9 km), pas la somme des trajets
    assert s.stops[2].billable_km == pytest.approx(9.0)
    assert s.stops[2].price_ar == 10000


def test_two_zones_in_one_route_are_not_split_artificially():
    # Scénario B : deux zones proches l'une de l'autre, la moyenne reste sous 3 km
    m = line_matrix({"A": 0, "B": 1, "C": 2, "D": 4, "E": 5, "F": 6})
    s = summarize_route(["A", "B", "C", "D", "E", "F"], m)
    assert s.distant_ids == ()


def test_dispersed_route_degrades_with_alert():
    m = line_matrix({"A": 0, "B": 4, "C": 8, "D": 12})
    s = summarize_route(["A", "B", "C", "D"], m)
    assert s.group_ids == ("A",)
    assert set(s.distant_ids) == {"B", "C", "D"}
    assert "TOURNEE_DISPERSEE" in s.alerts
    assert [p.price_ar for p in s.stops] == [4000, 5000, 9000, 13000]


def test_depot_leg_counts_in_cost_and_not_in_mean_by_default():
    m = line_matrix({"D": 0, "A": 10, "B": 11, "C": 12})
    s = summarize_route(["A", "B", "C"], m, depot="D")
    assert s.depot_leg_km == 10
    assert s.total_distance_km == 12
    assert s.cost_ar == 12000
    assert s.raw_mean_km == pytest.approx(1.0)
    assert s.distant_ids == ()  # un dépôt lointain ne rend aucun client éloigné
    assert s.margin_ar == 3 * 4000 - 12000


def test_depot_leg_in_mean_when_configured():
    m = line_matrix({"D": 0, "A": 10, "B": 11, "C": 12})
    s = summarize_route(["A", "B", "C"], m, Settings(include_depot_leg_in_mean=True), depot="D")
    assert s.raw_mean_km == pytest.approx(4.0)  # (10 + 1 + 1) / 3
    with pytest.raises(ValueError):
        summarize_route(["A", "B", "C"], m, Settings(include_depot_leg_in_mean=True))


def test_tie_break_removes_latest_stop():
    # Deux extrémités à égalité de détour : on retire la plus tardive (déterministe)
    m = line_matrix({"A": 0, "B": 8})
    s = summarize_route(["A", "B"], m)
    assert s.distant_ids == ("B",)


def test_changing_threshold_changes_result():
    m = line_matrix({"A": 0, "B": 1, "C": 2, "X": 6})
    assert summarize_route(["A", "B", "C", "X"], m, Settings(max_leg_threshold_km=None)).distant_ids == ()
    assert summarize_route(["A", "B", "C", "X"], m, Settings(max_leg_threshold_km=3.0)).distant_ids == ("X",)
    assert summarize_route(["A", "B", "C", "X"], m, Settings(mean_leg_threshold_km=1.5, max_leg_threshold_km=None)).distant_ids == ("X",)


def test_two_far_zones_are_not_all_flagged_distant():
    # Deux groupes de 3 arrêts séparés de 10 km : ce n'est pas un arrêt isolé, c'est une tournée
    # multi-zones. Personne n'est facturé à la distance, mais une alerte propose de séparer la tournée.
    m = line_matrix({"A": 0, "B": 1, "C": 2, "D": 12, "E": 13, "F": 14})
    s = summarize_route(["A", "B", "C", "D", "E", "F"], m)
    assert s.distant_ids == ()
    assert "TOURNEE_MULTI_ZONES" in s.alerts
    assert s.revenue_ar == 6 * 4000


def test_isolated_stop_next_to_a_far_zone_is_still_flagged():
    m = line_matrix({"A": 0, "B": 1, "C": 2, "X": 20})
    s = summarize_route(["A", "B", "C", "X"], m)
    assert s.distant_ids == ("X",)
    assert "TOURNEE_MULTI_ZONES" not in s.alerts
