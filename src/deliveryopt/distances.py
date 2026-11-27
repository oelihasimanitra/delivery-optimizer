"""Matrice de distances routières (en km), dirigée.

Règle importante (cahier des charges, phase 5) : aucune distance n'est inventée.
Si une distance routière manque ou si la destination est inaccessible, on lève une erreur.
Il n'existe volontairement aucun repli sur la distance à vol d'oiseau.
"""

from __future__ import annotations

from collections.abc import Mapping


class MissingDistanceError(LookupError):
    """Distance routière absente ou route inaccessible entre deux adresses."""


class DistanceMatrix:
    """Distances routières dirigées : dist(a, b) peut différer de dist(b, a) (sens uniques)."""

    def __init__(self, distances_km: Mapping[tuple[str, str], float | None]):
        for key, value in distances_km.items():
            if value is not None and value < 0:
                raise ValueError(f"Distance négative pour {key}: {value}")
        self._d = dict(distances_km)

    def dist(self, a: str, b: str) -> float:
        if a == b:
            return 0.0
        value = self._d.get((a, b))
        if value is None:
            raise MissingDistanceError(f"Aucune distance routière disponible de {a!r} vers {b!r}")
        return value

    @classmethod
    def from_symmetric(cls, distances_km: Mapping[tuple[str, str], float | None]) -> "DistanceMatrix":
        """Construit une matrice où dist(a, b) == dist(b, a). Utile pour les tests."""
        full: dict[tuple[str, str], float | None] = {}
        for (a, b), value in distances_km.items():
            full[(a, b)] = value
            full[(b, a)] = value
        return cls(full)
