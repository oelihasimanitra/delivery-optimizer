"""Paramètres métier configurables (valeurs initiales validées, voir docs/business-rules.md)."""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal

ROUND_MODES = ("half_up", "ceil")


@dataclass(frozen=True)
class Settings:
    """Tous les montants sont en Ariary (Ar), toutes les distances en kilomètres."""

    # Coût interne d'un km parcouru par le livreur.
    cost_per_km_ar: int = 1000

    # Tarif client : adresse dans le groupe.
    flat_price_ar: int = 4000

    # Tarif client : adresse éloignée = km facturables x prix/km + frais d'attente fixes.
    distant_price_per_km_ar: int = 1000
    distant_waiting_fee_ar: int = 1000

    # Seuil de la distance moyenne entre arrêts successifs d'une tournée.
    mean_leg_threshold_km: float = 3.0

    # Seuil optionnel par trajet (proposition validée : 5 km). None = désactivé.
    max_leg_threshold_km: float | None = 5.0

    # Le trajet dépôt -> premier arrêt compte-t-il dans la moyenne ? (défaut validé : non)
    include_depot_leg_in_mean: bool = False

    # Arrondi de la distance facturable (défaut : 0,1 km, arrondi au plus proche).
    km_round_step: Decimal = Decimal("0.1")
    km_round_mode: str = "half_up"

    def __post_init__(self) -> None:
        for name in ("cost_per_km_ar", "flat_price_ar", "distant_price_per_km_ar", "distant_waiting_fee_ar"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} ne peut pas être négatif")
        if self.mean_leg_threshold_km <= 0:
            raise ValueError("mean_leg_threshold_km doit être > 0")
        if self.max_leg_threshold_km is not None and self.max_leg_threshold_km <= 0:
            raise ValueError("max_leg_threshold_km doit être > 0 ou None")
        if self.km_round_step <= 0:
            raise ValueError("km_round_step doit être > 0")
        if self.km_round_mode not in ROUND_MODES:
            raise ValueError(f"km_round_mode doit être l'un de {ROUND_MODES}")


@dataclass(frozen=True)
class OptimizerSettings:
    """Paramètres de planification. Les valeurs marquées (provisoire) attendent une décision
    de l'utilisateur (voir docs/open-questions.md, point E) et sont toutes modifiables."""

    day_start: str = "08:00"  # heure de départ du dépôt (provisoire)
    day_end: str = "17:00"  # fin de journée : dernière remise terminée avant cette heure (provisoire)
    max_drivers: int = 10  # nombre maximum de livreurs disponibles (provisoire)
    max_parcels_per_driver: int = 20  # maximum strict (validé)
    target_min_parcels: int = 7  # cible (validé)
    default_service_min: float = 5.0  # durée de remise par défaut d'un colis (provisoire)
    desired_tolerance_min: float = 15.0  # tolérance sur l'heure souhaitée (validé)
    duration_factor: float = 1.0  # coefficient sur les durées de trajet (trafic, moto) à calibrer

    # Poids de l'objectif, en Ar (provisoire). Le coût au km vient de Settings.cost_per_km_ar.
    driver_fixed_cost_ar: int = 0
    wait_cost_ar_per_min: float = 50.0
    desired_deviation_cost_ar_per_min: float = 30.0
    mean_excess_cost_ar_per_km: float = 500.0  # préférence : rester sous la moyenne de 3 km
    under_target_cost_ar_per_parcel: float = 1500.0
    balance_cost_ar_per_min: float = 20.0  # écart entre la tournée la plus longue et la plus courte
    unassigned_penalty_ar: float = 100000.0  # par colis non attribué, multiplié par la priorité (1 à 3)

    # Recherche
    time_limit_s: float = 8.0
    restarts: int = 6
    seed: int = 42

    def __post_init__(self) -> None:
        from .models import parse_time

        start, end = parse_time(self.day_start), parse_time(self.day_end)
        if start is None or end is None or end <= start:
            raise ValueError("day_start / day_end invalides (format HH:MM, fin après début)")
        if self.max_drivers < 0:
            raise ValueError("max_drivers ne peut pas être négatif")
        if self.max_parcels_per_driver < 1 or self.target_min_parcels < 0:
            raise ValueError("capacité ou cible invalide")
        if self.duration_factor <= 0 or self.default_service_min < 0 or self.time_limit_s <= 0 or self.restarts < 1:
            raise ValueError("paramètre numérique invalide")
        for name in (
            "driver_fixed_cost_ar", "wait_cost_ar_per_min", "desired_deviation_cost_ar_per_min",
            "mean_excess_cost_ar_per_km", "under_target_cost_ar_per_parcel", "balance_cost_ar_per_min",
            "unassigned_penalty_ar", "desired_tolerance_min",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} ne peut pas être négatif")


@dataclass(frozen=True)
class AppSettings:
    """Ensemble des paramètres modifiables depuis l'interface (administrateur)."""

    pricing: Settings = Settings()
    optimizer: OptimizerSettings = OptimizerSettings()
    depot_name: str = "Dépôt"
    depot_lat: float = -18.9100  # provisoire : centre d'Antananarivo, à régler
    depot_lon: float = 47.5250

    def __post_init__(self) -> None:
        if not (-26.0 <= self.depot_lat <= -11.0 and 43.0 <= self.depot_lon <= 51.0):
            raise ValueError("Le dépôt doit se trouver à Madagascar (latitude/longitude)")

    def to_dict(self) -> dict:
        from dataclasses import asdict

        d = asdict(self)
        d["pricing"]["km_round_step"] = str(self.pricing.km_round_step)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        def build(klass, values):
            allowed = {f.name: f for f in fields(klass)}
            unknown = set(values) - set(allowed)
            if unknown:
                raise ValueError(f"Paramètres inconnus pour {klass.__name__} : {sorted(unknown)}")
            default = klass()
            out = {}
            for name, value in values.items():
                ref = getattr(default, name)
                if isinstance(ref, Decimal):
                    out[name] = Decimal(str(value))
                elif isinstance(ref, bool):
                    if not isinstance(value, bool):
                        raise ValueError(f"{name} doit être vrai ou faux")
                    out[name] = value
                elif isinstance(ref, int):
                    out[name] = int(value)
                elif isinstance(ref, float) or ref is None:
                    out[name] = None if value is None else float(value)
                else:
                    out[name] = str(value)
            return klass(**{**{f: getattr(default, f) for f in allowed}, **out})

        base = cls()
        extra = set(data) - {"pricing", "optimizer", "depot_name", "depot_lat", "depot_lon"}
        if extra:
            raise ValueError(f"Paramètres inconnus : {sorted(extra)}")
        return cls(
            pricing=build(Settings, data.get("pricing", {})),
            optimizer=build(OptimizerSettings, data.get("optimizer", {})),
            depot_name=str(data.get("depot_name", base.depot_name)),
            depot_lat=float(data.get("depot_lat", base.depot_lat)),
            depot_lon=float(data.get("depot_lon", base.depot_lon)),
        )
