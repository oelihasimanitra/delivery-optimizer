"""Calcul des tarifs clients (fonctions pures, tous les montants en Ar entiers)."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from .config import Settings


def round_km(km: float, settings: Settings) -> Decimal:
    """Arrondit une distance facturable selon le pas et le mode configurés."""
    if km < 0:
        raise ValueError("La distance ne peut pas être négative")
    value = Decimal(repr(float(km)))
    step = settings.km_round_step
    rounding = ROUND_HALF_UP if settings.km_round_mode == "half_up" else ROUND_CEILING
    return (value / step).to_integral_value(rounding=rounding) * step


def standard_price_ar(settings: Settings) -> int:
    """Prix d'une adresse du groupe : forfait, quel que soit le nombre de colis à cette adresse."""
    return settings.flat_price_ar


def distant_price_ar(billable_km: float, settings: Settings) -> int:
    """Prix d'une adresse éloignée : km facturables x prix/km + frais d'attente."""
    km = round_km(billable_km, settings)
    variable = (km * settings.distant_price_per_km_ar).to_integral_value(rounding=ROUND_HALF_UP)
    return int(variable) + settings.distant_waiting_fee_ar
