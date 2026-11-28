"""Optimisation des tournées de livraison : règles métier, tarifs et explications."""

__version__ = "0.3.0"

from .config import Settings
from .distances import DistanceMatrix, MissingDistanceError
from .pricing import distant_price_ar, round_km, standard_price_ar
from .route_metrics import RouteSummary, StopPricing, summarize_route

__all__ = [
    "Settings",
    "DistanceMatrix",
    "MissingDistanceError",
    "distant_price_ar",
    "round_km",
    "standard_price_ar",
    "RouteSummary",
    "StopPricing",
    "summarize_route",
]
