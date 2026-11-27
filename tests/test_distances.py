import pytest

from deliveryopt import DistanceMatrix, MissingDistanceError, Settings, summarize_route


def test_same_address_is_zero():
    assert DistanceMatrix({}).dist("A", "A") == 0.0


def test_missing_distance_raises_instead_of_guessing():
    m = DistanceMatrix({("A", "B"): 1.0})
    with pytest.raises(MissingDistanceError):
        m.dist("B", "A")  # la matrice est dirigée : pas de symétrie implicite
    with pytest.raises(MissingDistanceError):
        m.dist("A", "Z")


def test_unreachable_route_is_reported_not_invented():
    # Scénario H : route inaccessible -> None -> erreur explicite, jamais une distance inventée
    m = DistanceMatrix.from_symmetric({("A", "B"): 1.0, ("A", "X"): None, ("B", "X"): None})
    with pytest.raises(MissingDistanceError):
        summarize_route(["A", "B", "X"], m)


def test_negative_distance_rejected():
    with pytest.raises(ValueError):
        DistanceMatrix({("A", "B"): -1.0})


def test_asymmetric_matrix_is_supported():
    m = DistanceMatrix({("A", "B"): 1.0, ("B", "A"): 2.5})
    assert m.dist("A", "B") == 1.0
    assert m.dist("B", "A") == 2.5
