"""Aides de test : distances sur une droite (positions en km), donc métriques et vérifiables à la main."""

from __future__ import annotations

from deliveryopt import DistanceMatrix


def line_matrix(positions: dict[str, float]) -> DistanceMatrix:
    """dist(a, b) = |pos(a) - pos(b)|."""
    ids = list(positions)
    return DistanceMatrix({(a, b): abs(positions[a] - positions[b]) for a in ids for b in ids if a != b})
