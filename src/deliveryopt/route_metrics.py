"""Métriques d'une tournée : distance moyenne, adresses éloignées, tarifs, coût et alertes.

Règle de désignation des adresses éloignées (validée, voir docs/business-rules.md) :
- tant que la moyenne des trajets dépasse 3 km, on retire l'arrêt dont le retrait raccourcit le
  plus la tournée ;
- tant qu'un trajet dépasse le seuil par trajet, on retire un arrêt isolé dont le retrait supprime
  ce trajet trop long (s'il n'y en a pas, la tournée couvre plusieurs zones : alerte, pas d'éloignés).
Les arrêts retirés sont les adresses éloignées ; ceux qui restent forment le groupe.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Sequence

from .config import Settings
from .distances import DistanceMatrix
from .pricing import distant_price_ar, round_km, standard_price_ar

EPS = 1e-9
DistFn = Callable[[str, str], float]


@dataclass(frozen=True)
class StopPricing:
    address_id: str
    is_distant: bool
    billable_km: float | None
    price_ar: int
    explanation: str


@dataclass(frozen=True)
class RouteSummary:
    order: tuple[str, ...]
    depot: str | None
    depot_leg_km: float | None
    leg_km: tuple[float, ...]  # trajets entre arrêts successifs, dans l'ordre de la tournée
    raw_mean_km: float | None  # moyenne avant retrait des adresses éloignées
    group_mean_km: float | None  # moyenne du groupe (sans les adresses éloignées)
    group_ids: tuple[str, ...]
    distant_ids: tuple[str, ...]
    stops: tuple[StopPricing, ...]  # même ordre que la tournée
    total_distance_km: float  # inclut le trajet depuis le dépôt s'il est fourni
    cost_ar: int  # coût interne : km parcourus x coût/km
    revenue_ar: int  # somme des tarifs clients
    margin_ar: int
    alerts: tuple[str, ...]


@dataclass(frozen=True)
class _Removal:
    address_id: str
    reduction_km: float
    mean_before: float | None
    mean_after: float | None
    trigger: str  # "moyenne" ou "trajet"


def _path(order: Sequence[str], depot: str | None, include_depot: bool) -> list[str]:
    return ([depot] if include_depot and depot is not None else []) + list(order)


def _legs(path: Sequence[str], dist: DistFn) -> list[float]:
    return [dist(a, b) for a, b in zip(path, path[1:])]


def _mean(legs: Sequence[float]) -> float | None:
    return sum(legs) / len(legs) if legs else None


def mean_leg_km(
    order: Sequence[str],
    distances: DistanceMatrix,
    *,
    depot: str | None = None,
    include_depot_leg: bool = False,
) -> float | None:
    """Moyenne = somme des distances routières entre arrêts successifs / nombre de transitions."""
    if include_depot_leg and depot is None:
        raise ValueError("include_depot_leg=True nécessite un dépôt")
    return _mean(_legs(_path(order, depot, include_depot_leg), distances.dist))


def _trigger(legs: Sequence[float], settings: Settings) -> str | None:
    if not legs:
        return None
    if sum(legs) / len(legs) > settings.mean_leg_threshold_km + EPS:
        return "moyenne"
    limit = settings.max_leg_threshold_km
    if limit is not None and max(legs) > limit + EPS:
        return "trajet"
    return None


def _fmt_km(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}".replace(".", ",")


def _fmt_ar(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " Ar"


def _select_removals(
    order: Sequence[str], depot: str | None, dist: DistFn, settings: Settings
) -> tuple[list[str], list[_Removal]]:
    """Retire successivement l'arrêt au plus grand détour tant qu'un seuil est dépassé.

    Départage des égalités : on retire l'arrêt le plus tardif dans la tournée (les arrêts
    éloignés sont naturellement en fin de tournée puisque le retour n'est pas obligatoire).
    """
    include_depot = settings.include_depot_leg_in_mean
    current = list(order)
    removals: list[_Removal] = []

    limit = settings.max_leg_threshold_km
    while len(current) >= 2:
        legs = _legs(_path(current, depot, include_depot), dist)
        trigger = _trigger(legs, settings)
        if trigger is None:
            break
        base_total = sum(legs)
        over_before = sum(1 for leg in legs if limit is not None and leg > limit + EPS)
        best_index, best_reduction = -1, float("-inf")
        for i in range(len(current)):
            reduced = current[:i] + current[i + 1 :]
            reduced_legs = _legs(_path(reduced, depot, include_depot), dist)
            if trigger == "trajet":
                # Seuil par trajet : on ne désigne qu'un arrêt isolé, dont le retrait supprime au moins
                # un trajet trop long. Un groupe de plusieurs arrêts éloigné d'un autre groupe n'est pas
                # "éloigné" : la tournée couvre plusieurs zones (alerte TOURNEE_MULTI_ZONES).
                if sum(1 for leg in reduced_legs if leg > limit + EPS) >= over_before:
                    continue
            reduction = base_total - sum(reduced_legs)
            if reduction > best_reduction - EPS:  # égalité -> l'indice le plus tardif l'emporte
                best_index, best_reduction = i, reduction
        if best_index < 0:
            break
        removed_id = current[best_index]
        del current[best_index]
        mean_after = _mean(_legs(_path(current, depot, include_depot), dist))
        removals.append(_Removal(removed_id, best_reduction, _mean(legs), mean_after, trigger))
    return current, removals


def summarize_route(
    order: Sequence[str],
    distances: DistanceMatrix,
    settings: Settings | None = None,
    depot: str | None = None,
) -> RouteSummary:
    """Calcule moyenne, adresses éloignées, tarifs, coût interne, marge et alertes d'une tournée.

    `order` : identifiants d'adresses dans l'ordre de passage (une adresse = un arrêt).
    """
    settings = settings or Settings()
    if len(set(order)) != len(order):
        raise ValueError("Une adresse ne peut apparaître qu'une seule fois dans une tournée")
    if settings.include_depot_leg_in_mean and depot is None:
        raise ValueError("include_depot_leg_in_mean=True nécessite un dépôt")
    dist = distances.dist

    group, removals = _select_removals(order, depot, dist, settings)
    removal_by_id = {r.address_id: r for r in removals}

    stops: list[StopPricing] = []
    for address_id in order:
        removal = removal_by_id.get(address_id)
        if removal is None:
            price = standard_price_ar(settings)
            stops.append(
                StopPricing(address_id, False, None, price, f"Dans le groupe : forfait de {_fmt_ar(price)} par adresse.")
            )
            continue
        nearest = min(group, key=lambda g: dist(g, address_id))  # égalité -> premier de la tournée
        billable = dist(nearest, address_id)
        price = distant_price_ar(billable, settings)
        reason = (
            "la moyenne des trajets dépassait le seuil"
            if removal.trigger == "moyenne"
            else "un trajet dépassait le seuil par trajet"
        )
        explanation = (
            f"Adresse éloignée du groupe ({reason}). Sans elle, la moyenne des trajets passe de "
            f"{_fmt_km(removal.mean_before)} km à {_fmt_km(removal.mean_after)} km "
            f"(détour évité : {_fmt_km(removal.reduction_km)} km). "
            f"Distance depuis l'arrêt le plus proche du groupe ({nearest}) : {_fmt_km(billable)} km, "
            f"facturée {_fmt_km(float(round_km(billable, settings)))} km x "
            f"{_fmt_ar(settings.distant_price_per_km_ar)} + {_fmt_ar(settings.distant_waiting_fee_ar)} d'attente "
            f"= {_fmt_ar(price)}."
        )
        stops.append(StopPricing(address_id, True, billable, price, explanation))

    legs_original = _legs(list(order), dist)
    depot_leg = dist(depot, order[0]) if depot is not None and order else None
    total_km = sum(legs_original) + (depot_leg or 0.0)
    cost = int((Decimal(repr(float(total_km))) * settings.cost_per_km_ar).to_integral_value(ROUND_HALF_UP))
    revenue = sum(s.price_ar for s in stops)

    raw_mean = _mean(_legs(_path(order, depot, settings.include_depot_leg_in_mean), dist))
    group_legs = _legs(_path(group, depot, settings.include_depot_leg_in_mean), dist)
    group_mean = _mean(group_legs)

    alerts: list[str] = []
    if raw_mean is not None and raw_mean > settings.mean_leg_threshold_km + EPS:
        alerts.append("MOYENNE_SUPERIEURE_AU_SEUIL")
    alerts.extend(f"CLIENT_ELOIGNE:{a}" for a in order if a in removal_by_id)
    if len(removals) > len(order) / 2:
        alerts.append("TOURNEE_DISPERSEE")
    remaining = _trigger(group_legs, settings)
    if remaining == "trajet":
        alerts.append("TOURNEE_MULTI_ZONES")
    elif remaining == "moyenne":
        alerts.append("SEUIL_NON_RESPECTE")

    return RouteSummary(
        order=tuple(order),
        depot=depot,
        depot_leg_km=depot_leg,
        leg_km=tuple(legs_original),
        raw_mean_km=raw_mean,
        group_mean_km=group_mean,
        group_ids=tuple(group),
        distant_ids=tuple(a for a in order if a in removal_by_id),  # ordre de la tournée
        stops=tuple(stops),
        total_distance_km=total_km,
        cost_ar=cost,
        revenue_ar=revenue,
        margin_ar=revenue - cost,
        alerts=tuple(alerts),
    )
