from decimal import Decimal

import pytest

from deliveryopt import Settings, distant_price_ar, round_km, standard_price_ar


def test_standard_price_is_flat():
    assert standard_price_ar(Settings()) == 4000


@pytest.mark.parametrize(
    "km, expected",
    [(5, 6000), (10, 11000), (3, 4000), (1, 2000), (0, 1000), (12.5, 13500)],
)
def test_distant_price_examples_from_spec(km, expected):
    # 5 km -> 6 000 Ar et 10 km -> 11 000 Ar viennent du cahier des charges V2 (§8.3)
    assert distant_price_ar(km, Settings()) == expected


def test_price_is_continuous_at_3_km():
    # À 3 km, la formule des adresses éloignées rejoint exactement le forfait.
    assert distant_price_ar(3, Settings()) == standard_price_ar(Settings())


def test_rounding_half_up_to_tenth_of_km():
    s = Settings()
    assert round_km(5.04, s) == Decimal("5.0")
    assert round_km(5.05, s) == Decimal("5.1")
    assert round_km(5.06, s) == Decimal("5.1")


def test_rounding_ceil_mode():
    s = Settings(km_round_mode="ceil")
    assert round_km(5.01, s) == Decimal("5.1")
    assert round_km(5.0, s) == Decimal("5.0")
    assert distant_price_ar(5.01, s) == 5100 + 1000


def test_rounding_whole_km():
    s = Settings(km_round_step=Decimal("1"), km_round_mode="ceil")
    assert distant_price_ar(4.2, s) == 5000 + 1000


def test_rules_are_configurable():
    s = Settings(flat_price_ar=5000, distant_price_per_km_ar=1500, distant_waiting_fee_ar=500)
    assert standard_price_ar(s) == 5000
    assert distant_price_ar(4, s) == 4 * 1500 + 500


def test_negative_distance_rejected():
    with pytest.raises(ValueError):
        distant_price_ar(-1, Settings())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"flat_price_ar": -1},
        {"mean_leg_threshold_km": 0},
        {"max_leg_threshold_km": 0},
        {"km_round_step": Decimal("0")},
        {"km_round_mode": "floor"},
    ],
)
def test_invalid_settings_rejected(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)
