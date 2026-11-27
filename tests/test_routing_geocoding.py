import pytest

from deliveryopt.geocoding import GeocodingError, NominatimGeocoder, normalize_query
from deliveryopt.routing import EstimateProvider, OSRMProvider, RoutingError, haversine_km

from support import FakeHTTP


def test_haversine_known_distance():
    # Antananarivo -> Toamasina : environ 215 km à vol d'oiseau (la route fait bien plus)
    assert 205 < haversine_km((-18.9137, 47.5361), (-18.1492, 49.4023)) < 225


def test_estimate_provider_is_flagged_unreliable_and_scaled():
    r = EstimateProvider(detour_factor=1.5, speed_kmh=30).matrix([(-18.91, 47.52), (-18.90, 47.53)])
    assert r.reliable is False and r.mode == "estimate"
    assert r.km[0][1] == pytest.approx(haversine_km((-18.91, 47.52), (-18.90, 47.53)) * 1.5)
    assert r.minutes[0][1] == pytest.approx(r.km[0][1] / 30 * 60) and r.km[0][0] == 0.0


def osrm_handler(null_pairs=(), code="Ok", snap=10.0):
    """Imite /table/v1 : lit les coordonnées, sources, destinations, renvoie distances (m) et durées (s)."""
    from urllib.parse import parse_qs, urlsplit

    def handler(path, headers):
        url = urlsplit(path)  # urlparse couperait le chemin au premier ';'
        coords = [tuple(map(float, c.split(","))) for c in url.path.split("/")[-1].split(";")]
        q = parse_qs(url.query)
        src = [int(x) for x in q["sources"][0].split(";")]
        dst = [int(x) for x in q["destinations"][0].split(";")]
        assert q["annotations"] == ["duration,distance"]
        if code != "Ok":
            return 200, {"code": code, "message": "boom"}
        dist = [[None if (coords[i], coords[j]) in null_pairs else haversine_km((coords[i][1], coords[i][0]), (coords[j][1], coords[j][0])) * 1000 for j in dst] for i in src]
        dur = [[None if d is None else d / 10 for d in row] for row in dist]
        return 200, {"code": "Ok", "distances": dist, "durations": dur, "sources": [{"distance": snap} for _ in src]}

    return handler


def test_osrm_matrix_with_chunking_matches_direct_computation():
    server = FakeHTTP(osrm_handler())
    try:
        pts = [(-18.9 + 0.01 * i, 47.5 + 0.005 * i) for i in range(7)]
        r = OSRMProvider(server.url, chunk=3).matrix(pts)
        assert r.reliable and r.mode == "osrm"
        for i in range(7):
            for j in range(7):
                expected = 0.0 if i == j else haversine_km(pts[i], pts[j])
                assert r.km[i][j] == pytest.approx(expected, abs=1e-4)
                assert r.minutes[i][j] == pytest.approx(expected * 1000 / 10 / 60, abs=1e-4)
        assert r.snap_m == [10.0] * 7
        assert len(server.requests) == 9  # 3 x 3 blocs
    finally:
        server.close()


def test_osrm_unreachable_pair_stays_none_never_invented():
    pts = [(-18.9, 47.5), (-18.91, 47.51), (-18.92, 47.52)]
    blocked = ((pts[0][::-1], pts[2][::-1]),)
    server = FakeHTTP(osrm_handler(null_pairs=blocked))
    try:
        r = OSRMProvider(server.url).matrix(pts)
        assert r.km[0][2] is None and r.minutes[0][2] is None
        assert r.km[2][0] is not None and r.km[0][1] is not None
    finally:
        server.close()


def test_osrm_errors_are_raised():
    server = FakeHTTP(osrm_handler(code="InvalidQuery"))
    try:
        with pytest.raises(RoutingError):
            OSRMProvider(server.url).matrix([(-18.9, 47.5), (-18.91, 47.51)])
    finally:
        server.close()
    with pytest.raises(RoutingError):
        OSRMProvider("http://127.0.0.1:9", timeout=1).matrix([(-18.9, 47.5), (-18.91, 47.51)])


def nominatim_handler(payload, status=200):
    return lambda path, headers: (status, payload)


def test_geocoder_parses_filters_and_flags_approximate():
    payload = [
        {"lat": "-18.8796", "lon": "47.5285", "display_name": "Ankorondrano, Antananarivo", "type": "suburb"},
        {"lat": "-18.87", "lon": "47.53", "display_name": "Rue X", "type": "residential"},
        {"lat": "48.85", "lon": "2.35", "display_name": "Paris", "type": "city"},
        {"lat": "oops", "lon": "x"},
    ]
    server = FakeHTTP(nominatim_handler(payload))
    try:
        results = NominatimGeocoder(server.url, "test-app/1.0 (contact@example.org)", min_interval_s=0).search("Ankorondrano")
        assert [r["label"] for r in results] == ["Ankorondrano, Antananarivo", "Rue X"]
        assert results[0]["approximate"] is True and results[1]["approximate"] is False
        path, headers = server.requests[0]
        assert "countrycodes=mg" in path and headers["User-Agent"].startswith("test-app/1.0")
    finally:
        server.close()


def test_geocoder_empty_and_outage():
    server = FakeHTTP(nominatim_handler([]))
    try:
        assert NominatimGeocoder(server.url, "ua", min_interval_s=0).search("introuvable") == []
    finally:
        server.close()
    with pytest.raises(GeocodingError):
        NominatimGeocoder("http://127.0.0.1:9", "ua", min_interval_s=0, timeout=1).search("x")
    with pytest.raises(ValueError):
        NominatimGeocoder("http://x", " ")
    with pytest.raises(ValueError):
        NominatimGeocoder("http://x", "ua").search("  ")


def test_normalize_query():
    assert normalize_query("  Ankorondrano   ANTANANARIVO ") == "ankorondrano antananarivo"
