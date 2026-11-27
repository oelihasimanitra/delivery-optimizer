"""Benchmark : le moteur est comparé à des méthodes simples, à nombre de livreurs égal.

Méthodes de référence : ordre initial (colis découpés dans l'ordre de saisie), plus proche voisin
(même découpage, ordre amélioré), regroupement simple (balayage angulaire autour du dépôt).
Les méthodes simples ne respectent pas forcément les contraintes : on compte leurs violations.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

from .config import AppSettings, OptimizerSettings
from .distances import DistanceMatrix
from .models import INF
from .optimizer import Problem
from .planner import PlanResult, run_plan
from .route_metrics import summarize_route
from .routing import EstimateProvider


def synthetic_rows(n: int, seed: int, constrained: bool = True) -> list[dict]:
    """Colis fictifs répartis en quartiers autour d'Antananarivo (aucune donnée réelle)."""
    rng = random.Random(seed)
    centers = [(-18.88, 47.53), (-18.92, 47.52), (-18.95, 47.48), (-18.87, 47.57), (-18.90, 47.55)]
    rows = []
    for i in range(n):
        c = rng.choice(centers)
        row = {
            "id_colis": f"C{i + 1}", "adresse": f"Adresse fictive {i + 1}",
            "latitude": round(c[0] + rng.gauss(0, 0.008), 6), "longitude": round(c[1] + rng.gauss(0, 0.008), 6),
        }
        if constrained:
            if rng.random() < 0.15:
                row["heure_max"] = f"{rng.randint(11, 15)}:00"
            if rng.random() < 0.10:
                row["heure_min"] = f"{rng.randint(9, 12)}:00"
        rows.append(row)
    return rows


def _chunks(items: list[int], k: int) -> list[list[int]]:
    size = math.ceil(len(items) / k)
    return [items[i:i + size] for i in range(0, len(items), size)]


def _nearest_neighbour(p: Problem, chunk: list[int]) -> list[int]:
    todo, order, node = set(chunk), [], 0
    while todo:
        nxt = min(todo, key=lambda i: (p.km[node][i + 1], i))
        order.append(nxt)
        todo.remove(nxt)
        node = nxt + 1
    return order


def baseline_routes(p: Problem, coords: list[tuple[float, float]], depot: tuple[float, float], k: int) -> dict[str, list[list[int]]]:
    indices = list(range(p.n))
    initial = _chunks(indices, k)
    by_angle = sorted(indices, key=lambda i: math.atan2(coords[i][0] - depot[0], coords[i][1] - depot[1]))
    return {
        "ordre initial": initial,
        "plus proche voisin": [_nearest_neighbour(p, c) for c in initial],
        "regroupement simple": [_nearest_neighbour(p, c) for c in _chunks(by_angle, k)],
    }


def free_metrics(p: Problem, routes: list[list[int]] | list[tuple[int, ...]]) -> dict:
    """Mesure une tournée SANS imposer les contraintes : on compte les violations."""
    routes = [list(r) for r in routes if r]
    owner = {i: ri for ri, r in enumerate(routes) for i in r}
    km_total = wait_total = 0.0
    violations = 0
    durations, mean_legs, distant = [], [], 0
    for ri, r in enumerate(routes):
        t, prev, legs = p.day_start, 0, []
        if sum(p.parcels[i] for i in r) > p.s.max_parcels_per_driver:
            violations += 1
        pos = {x: j for j, x in enumerate(r)}
        for j, x in enumerate(r):
            d = p.km[prev][x + 1]
            if d == INF:
                violations += 1
                d = 0.0
            km_total += d
            if j > 0:
                legs.append(d)
            arrive = t + (p.minutes[prev][x + 1] if p.minutes[prev][x + 1] != INF else 0)
            start = max(arrive, p.earliest[x])
            wait_total += start - arrive
            if start > p.latest[x] + 1e-9:
                violations += 1
            for a in p.after[x]:
                if owner.get(a) != ri or pos.get(a, 10**9) > j:
                    violations += 1
            t, prev = start + p.service[x], x + 1
        if t > p.day_end + 1e-9:
            violations += 1
        durations.append(t - p.day_start)
        mean_legs.extend(legs)
        ids = [f"S{x}" for x in r]
        nodes = ["D"] + ids
        idx = [0] + [x + 1 for x in r]
        dm = DistanceMatrix({(a, b): p.km[ia][ib] for a, ia in zip(nodes, idx) for b, ib in zip(nodes, idx) if a != b and p.km[ia][ib] != INF})
        distant += len(summarize_route(ids, dm, AppSettings().pricing, depot="D").distant_ids)
    return {
        "livreurs": len(routes), "distance_km": km_total, "duree_totale_min": sum(durations), "attente_min": wait_total,
        "contraintes_violees": violations, "desequilibre_min": (max(durations) - min(durations)) if durations else 0.0,
        "trajet_moyen_km": (sum(mean_legs) / len(mean_legs)) if mean_legs else 0.0, "adresses_eloignees": distant,
    }


def compare(result: PlanResult, app: AppSettings) -> dict[str, dict]:
    """Compare la solution retenue aux méthodes simples, à nombre de livreurs égal."""
    assert result.problem is not None and result.solution is not None
    p = result.problem
    k = max(1, len(result.solution.used))
    coords = [(s.lat, s.lon) for s in result.stops]
    depot = (app.depot_lat, app.depot_lon)
    out = {name: free_metrics(p, routes) for name, routes in baseline_routes(p, coords, depot, k).items()}
    out["optimisé"] = free_metrics(p, result.solution.used)
    return out


def run_benchmark(n: int = 40, seeds: int = 5, time_limit_s: float = 4.0) -> dict[str, dict]:
    """Moyenne sur plusieurs instances fictives (mode estimation : le benchmark compare des méthodes, pas des routes réelles)."""
    app = AppSettings(optimizer=OptimizerSettings(time_limit_s=time_limit_s))
    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for seed in range(1, seeds + 1):
        result = run_plan(synthetic_rows(n, seed), EstimateProvider(), app)
        if result.problem is None or result.solution is None:
            continue
        for name, metrics in compare(result, app).items():
            for key, value in metrics.items():
                acc[name][key] += value / seeds
    return {name: dict(m) for name, m in acc.items()}


def format_table(results: dict[str, dict]) -> str:
    cols = [("livreurs", "Livreurs"), ("distance_km", "Distance (km)"), ("duree_totale_min", "Durée totale (min)"),
            ("attente_min", "Attente (min)"), ("contraintes_violees", "Contraintes violées"),
            ("desequilibre_min", "Déséquilibre (min)"), ("trajet_moyen_km", "Trajet moyen (km)"), ("adresses_eloignees", "Adresses éloignées")]
    lines = ["| Méthode | " + " | ".join(c[1] for c in cols) + " |", "|---|" + "---|" * len(cols)]
    for name, m in results.items():
        lines.append(f"| {name} | " + " | ".join(f"{m[key]:.1f}" for key, _ in cols) + " |")
    return "\n".join(lines)
