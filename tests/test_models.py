import pytest

from deliveryopt.models import build_stops, fmt_time, normalize_priority, parse_parcels, parse_time

from support import parcel


@pytest.mark.parametrize("text, expected", [("10:00", 600), ("10h", 600), ("9h30", 570), (" 08:05 ", 485), ("", None), (None, None), ("00:00", 0)])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text", ["25:00", "10:75", "dix heures", "10-00"])
def test_parse_time_invalid(text):
    with pytest.raises(ValueError):
        parse_time(text)


def test_fmt_time():
    assert fmt_time(600) == "10:00" and fmt_time(485.4) == "08:05" and fmt_time(None) == "--:--"


def test_priority_aliases():
    assert normalize_priority("élevée") == 2 and normalize_priority("URGENTE") == 3 and normalize_priority("") == 1
    with pytest.raises(ValueError):
        normalize_priority("critique")


def test_invalid_rows_are_reported_not_dropped_silently():
    rows = [
        parcel("A", -18.9, 47.5),
        parcel("A", -18.9, 47.5),  # doublon
        {"id_colis": "", "adresse": "x", "latitude": -18.9, "longitude": 47.5},  # sans id
        parcel("B", None, None),  # non localisé
        parcel("C", 48.85, 2.35),  # hors Madagascar
        parcel("D", -18.9, 47.5, heure_min="10:00", heure_max="09:00"),  # fenêtre vide
        parcel("E", -18.9, 47.5, heure_max="abc"),  # heure invalide
        parcel("F", "pas un nombre", 47.5),
        parcel("G", -18.9, 47.5, duree_remise_min="-3"),
    ]
    parcels, rejected = parse_parcels(rows)
    assert [p.id for p in parcels] == ["A"]
    codes = {r.parcel_id or "?": r.code for r in rejected}
    assert codes["A"] == "ID_DUPLIQUE"
    assert codes["B"] == "ADRESSE_NON_LOCALISEE"
    assert codes["C"] == "COORDONNEES_HORS_MADAGASCAR"
    assert codes["D"] == "FENETRE_VIDE"
    assert codes["E"] == codes["F"] == codes["G"] == "DONNEE_INVALIDE"
    assert any(r.code == "ID_MANQUANT" for r in rejected)
    assert len(rejected) == len(rows) - 1


def test_comma_decimal_accepted():
    parcels, rejected = parse_parcels([parcel("A", "-18,9", "47,5")])
    assert not rejected and parcels[0].lat == -18.9


def test_same_coordinates_make_one_stop():
    parcels, _ = parse_parcels([parcel("A", -18.9, 47.5, duree_remise_min=4), parcel("B", -18.9, 47.5, duree_remise_min=6), parcel("C", -18.91, 47.5)])
    stops, groups, rejected = build_stops(parcels, 5.0)
    assert len(stops) == 2 and stops[0].parcel_ids == ["A", "B"]
    assert stops[0].service_min == 10  # 4 + 6
    assert not rejected and groups == []


def test_windows_are_merged_by_intersection():
    parcels, _ = parse_parcels([parcel("A", -18.9, 47.5, heure_min="09:00", heure_max="12:00"), parcel("B", -18.9, 47.5, heure_min="10:00", heure_max="13:00")])
    stops, _, _ = build_stops(parcels, 5.0)
    assert (stops[0].earliest, stops[0].latest) == (600, 720)


def test_incompatible_windows_at_same_address_are_rejected():
    parcels, _ = parse_parcels([parcel("A", -18.9, 47.5, heure_max="09:00"), parcel("B", -18.9, 47.5, heure_min="10:00"), parcel("C", -18.95, 47.5)])
    stops, _, rejected = build_stops(parcels, 5.0)
    assert {r.parcel_id for r in rejected} == {"A", "B"} and all(r.code == "FENETRE_VIDE" for r in rejected)
    assert len(stops) == 1 and stops[0].parcel_ids == ["C"]


def test_dependencies_form_ordered_groups():
    parcels, _ = parse_parcels([parcel("A", -18.90, 47.5), parcel("B", -18.91, 47.5, apres_colis="A"), parcel("C", -18.92, 47.5, apres_colis="B"), parcel("D", -18.93, 47.5)])
    stops, groups, rejected = build_stops(parcels, 5.0)
    assert not rejected and groups == [[0, 1, 2]]
    assert stops[1].after == {"S1"} and stops[2].after == {"S2"}


def test_unknown_or_circular_dependencies_are_rejected():
    parcels, _ = parse_parcels([
        parcel("A", -18.90, 47.5, apres_colis="ZZZ"), parcel("B", -18.91, 47.5, apres_colis="C"), parcel("C", -18.92, 47.5, apres_colis="B"),
        parcel("D", -18.93, 47.5, apres_colis="D"), parcel("E", -18.94, 47.5, apres_colis="A"), parcel("F", -18.95, 47.5),
    ])
    stops, _, rejected = build_stops(parcels, 5.0)
    by = {r.parcel_id: r.code for r in rejected}
    assert by["A"] == "DEPENDANCE_INCONNUE" and by["E"] == "DEPENDANCE_INCONNUE"  # E dépend de A, écarté
    assert by["B"] == by["C"] == "DEPENDANCE_CIRCULAIRE" and by["D"] == "DEPENDANCE_CIRCULAIRE"
    assert [s.parcel_ids for s in stops] == [["F"]]
