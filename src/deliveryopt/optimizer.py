"""Moteur d'optimisation des tournées (Python pur, sans dépendance).

Problème : plusieurs livreurs partant d'un dépôt unique (sans retour), des arrêts avec fenêtres
horaires, durées de remise, priorités, ordre imposé et capacité. Méthode : insertion au moindre
coût, puis recherche locale (déplacement, 2-opt, échange entre tournées) avec plusieurs
redémarrages, pour chaque nombre de livreurs candidat ; on garde le moins coûteux.

Le calcul d'une tournée (`Evaluator`) est la seule source de vérité des horaires et des coûts.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Iterator, NamedTuple

from .config import OptimizerSettings
from .models import INF

EPS = 1e-9


@dataclass
class Problem:
    """Données numériques du problème. Nœud 0 = dépôt ; l'arrêt i correspond au nœud i + 1."""

    km: list[list[float]]  # INF = aucune route
    minutes: list[list[float]]  # déjà multipliées par duration_factor
    earliest: list[float]
    latest: list[float]
    desired: list[float | None]
    service: list[float]
    parcels: list[int]
    weight: list[int]  # priorité 1 à 3
    after: list[set[int]]  # indices d'arrêts qui doivent précéder
    groups: list[list[int]]  # groupes d'ordre imposé (indices, triés topologiquement)
    cost_per_km: float
    mean_threshold_km: float
    s: OptimizerSettings
    day_start: float
    day_end: float
    group_of: dict[int, tuple[int, ...]] = field(init=False)

    def __post_init__(self) -> None:
        self.group_of = {i: (i,) for i in range(len(self.earliest))}
        for g in self.groups:
            for i in g:
                self.group_of[i] = tuple(g)

    @property
    def n(self) -> int:
        return len(self.earliest)


class RouteEval(NamedTuple):
    cost: float
    km: float
    wait: float
    end: float  # heure de fin de la dernière remise
    parcels: int
    times: tuple  # (arrivée, début de remise, départ) par arrêt


_EMPTY = RouteEval(0.0, 0.0, 0.0, 0.0, 0, ())


class Evaluator:
    def __init__(self, p: Problem):
        self.p = p
        self._cache: dict[tuple[int, ...], RouteEval | None] = {}

    def eval(self, route: tuple[int, ...]) -> RouteEval | None:
        if not route:
            return _EMPTY
        try:
            return self._cache[route]
        except KeyError:
            result = self._cache[route] = self._eval(route)
            return result

    def _eval(self, route: tuple[int, ...]) -> RouteEval | None:
        p, s = self.p, self.p.s
        if sum(p.parcels[i] for i in route) > s.max_parcels_per_driver:
            return None
        pos = {x: i for i, x in enumerate(route)}
        for x in route:
            for a in p.after[x]:
                j = pos.get(a)
                if j is not None and j > pos[x]:
                    return None
        t, prev, km, wait, penalty, first_leg = p.day_start, 0, 0.0, 0.0, 0.0, 0.0
        times = []
        for idx, x in enumerate(route):
            node = x + 1
            d = p.km[prev][node]
            if d == INF:
                return None
            arrive = t + p.minutes[prev][node]
            start = max(arrive, p.earliest[x])
            if start > p.latest[x] + EPS:
                return None
            wait += start - arrive
            desired = p.desired[x]
            if desired is not None:
                excess = abs(start - desired) - s.desired_tolerance_min
                if excess > 0:
                    penalty += excess * s.desired_deviation_cost_ar_per_min
            depart = start + p.service[x]
            times.append((arrive, start, depart))
            if idx == 0:
                first_leg = d
            km += d
            t, prev = depart, node
        if t > p.day_end + EPS:
            return None
        legs = len(route) - 1
        excess_km = max(0.0, (km - first_leg) - p.mean_threshold_km * legs) if legs else 0.0
        cost = (
            km * p.cost_per_km
            + wait * s.wait_cost_ar_per_min
            + penalty
            + excess_km * s.mean_excess_cost_ar_per_km
        )
        return RouteEval(cost, km, wait, t, sum(p.parcels[i] for i in route), tuple(times))


@dataclass
class Solution:
    routes: list[tuple[int, ...]]
    unassigned: list[int]
    cost: float
    k: int  # nombre de livreurs autorisés pour cette solution

    @property
    def used(self) -> list[tuple[int, ...]]:
        return [r for r in self.routes if r]


class Solver:
    def __init__(self, p: Problem):
        self.p = p
        self.ev = Evaluator(p)

    # ---- objectif global -------------------------------------------------
    def plan_cost(self, routes: list[tuple[int, ...]], unassigned: list[int]) -> float:
        p, s = self.p, self.p.s
        evals = []
        for r in routes:
            e = self.ev.eval(r)
            if e is None:
                return INF
            evals.append((r, e))
        used = [(r, e) for r, e in evals if r]
        cost = sum(e.cost for _, e in used) + s.driver_fixed_cost_ar * len(used)
        cost += sum(s.unassigned_penalty_ar * p.weight[i] * p.parcels[i] for i in unassigned)
        if len(used) >= 2:
            durations = [e.end - p.day_start for _, e in used]
            cost += s.balance_cost_ar_per_min * (max(durations) - min(durations))
        if used and s.target_min_parcels > 0:
            assigned = sum(e.parcels for _, e in used)
            target = min(s.target_min_parcels, assigned // len(used))
            cost += s.under_target_cost_ar_per_parcel * sum(max(0, target - e.parcels) for _, e in used)
        return cost

    # ---- insertion -------------------------------------------------------
    def best_insertion(self, route: tuple[int, ...], stop: int) -> tuple[int, ...] | None:
        best, best_cost = None, INF
        for pos in range(len(route) + 1):
            cand = route[:pos] + (stop,) + route[pos:]
            e = self.ev.eval(cand)
            if e is not None and e.cost < best_cost - EPS:
                best, best_cost = cand, e.cost
        return best

    def insert_group(self, route: tuple[int, ...], group: tuple[int, ...]) -> tuple[int, ...] | None:
        cur = route
        for stop in group:
            cur = self.best_insertion(cur, stop)
            if cur is None:
                return None
        return cur

    # ---- construction ----------------------------------------------------
    def construct(self, order: list[tuple[int, ...]], k: int) -> tuple[list[tuple[int, ...]], list[int]]:
        routes: list[tuple[int, ...]] = [()] * k
        unassigned: list[int] = []
        for group in order:
            best, best_delta = None, INF
            for ri in range(k):
                cand = self.insert_group(routes[ri], group)
                if cand is None:
                    continue
                delta = self.ev.eval(cand).cost - self.ev.eval(routes[ri]).cost
                if not routes[ri]:
                    delta += self.p.s.driver_fixed_cost_ar
                if delta < best_delta - EPS:
                    best, best_delta = (ri, cand), delta
            if best is None:
                unassigned.extend(group)
            else:
                routes[best[0]] = best[1]
        return routes, unassigned

    # ---- recherche locale ------------------------------------------------
    def _neighbours(self, routes: list[tuple[int, ...]], unassigned: list[int]) -> Iterator[tuple[list[tuple[int, ...]], list[int]]]:
        p = self.p
        k = len(routes)

        def with_changes(changes: dict[int, tuple[int, ...]], un: list[int]):
            new = list(routes)
            for i, r in changes.items():
                new[i] = r
            return new, un

        # 0. insérer des arrêts non attribués
        done: set[tuple[int, ...]] = set()
        for s in unassigned:
            g = p.group_of[s]
            if g in done:
                continue
            done.add(g)
            remaining = [x for x in unassigned if x not in g]
            for ri in range(k):
                cand = self.insert_group(routes[ri], g)
                if cand is not None:
                    yield with_changes({ri: cand}, remaining)
        for ri, r in enumerate(routes):
            # 1. déplacement dans la tournée
            for i in range(len(r)):
                rest = r[:i] + r[i + 1:]
                for pos in range(len(rest) + 1):
                    if pos != i:
                        yield with_changes({ri: rest[:pos] + (r[i],) + rest[pos:]}, unassigned)
            # 2. 2-opt
            for i in range(len(r) - 1):
                for j in range(i + 1, len(r)):
                    yield with_changes({ri: r[:i] + tuple(reversed(r[i:j + 1])) + r[j + 1:]}, unassigned)
        # 3. déplacement d'un groupe vers une autre tournée
        for ri, r in enumerate(routes):
            seen: set[tuple[int, ...]] = set()
            for s in r:
                g = p.group_of[s]
                if g in seen or not set(g) <= set(r):
                    continue
                seen.add(g)
                rest = tuple(x for x in r if x not in g)
                for rj in range(k):
                    if rj == ri:
                        continue
                    cand = self.insert_group(routes[rj], g)
                    if cand is not None:
                        yield with_changes({ri: rest, rj: cand}, unassigned)
        # 4. échange de deux arrêts isolés entre tournées
        for ri in range(k):
            for rj in range(ri + 1, k):
                a_route, b_route = routes[ri], routes[rj]
                for i, a in enumerate(a_route):
                    if len(p.group_of[a]) > 1:
                        continue
                    for j, b in enumerate(b_route):
                        if len(p.group_of[b]) > 1:
                            continue
                        yield with_changes(
                            {ri: a_route[:i] + (b,) + a_route[i + 1:], rj: b_route[:j] + (a,) + b_route[j + 1:]}, unassigned
                        )

    def local_search(self, routes, unassigned, deadline: float):
        cost = self.plan_cost(routes, unassigned)
        while time.monotonic() < deadline:
            for new_routes, new_un in self._neighbours(routes, unassigned):
                new_cost = self.plan_cost(new_routes, new_un)
                if new_cost < cost - 1e-6:
                    routes, unassigned, cost = new_routes, new_un, new_cost
                    break
            else:
                break
        return routes, unassigned, cost

    def _start_orders(self, rng: random.Random, restarts: int) -> list[list[tuple[int, ...]]]:
        p = self.p
        groups: list[tuple[int, ...]] = []
        seen: set[tuple[int, ...]] = set()
        for i in range(p.n):
            g = p.group_of[i]
            if g not in seen:
                seen.add(g)
                groups.append(g)

        def tightest(g):
            return min(p.latest[i] for i in g)

        def far(g):
            return -max(p.km[0][i + 1] for i in g)

        orders = [
            sorted(groups, key=lambda g: (tightest(g), -max(p.weight[i] for i in g), far(g))),
            sorted(groups, key=lambda g: (far(g), tightest(g))),
            sorted(groups, key=lambda g: (-max(p.weight[i] for i in g), tightest(g), far(g))),
        ]
        while len(orders) < restarts:
            shuffled = groups[:]
            rng.shuffle(shuffled)
            orders.append(shuffled)
        return orders[:restarts]

    def solve(self, k: int, deadline: float) -> Solution:
        rng = random.Random(self.p.s.seed + k)
        best: Solution | None = None
        for order in self._start_orders(rng, self.p.s.restarts):
            routes, unassigned = self.construct(order, k)
            routes, unassigned, cost = self.local_search(routes, unassigned, deadline)
            if best is None or cost < best.cost - 1e-6:
                best = Solution(routes, unassigned, cost, k)
            if time.monotonic() >= deadline:
                break
        assert best is not None
        return best


def driver_candidates(n_parcels: int, s: OptimizerSettings) -> list[int]:
    """Nombres de livreurs à essayer : de la capacité minimale jusqu'à la cible de 7 colis en moyenne."""
    if s.max_drivers == 0 or n_parcels == 0:
        return []
    k_min = max(1, math.ceil(n_parcels / s.max_parcels_per_driver))
    k_max = max(k_min, n_parcels // s.target_min_parcels if s.target_min_parcels > 0 else k_min)
    if k_min > s.max_drivers:
        return [s.max_drivers]
    return list(range(k_min, min(k_max, s.max_drivers) + 1))


@dataclass
class Candidate:
    k: int
    drivers_used: int
    cost: float
    km: float
    unassigned: int


def optimize(p: Problem) -> tuple[Solution | None, list[Candidate], Solver]:
    """Optimise pour chaque nombre de livreurs candidat et retourne la meilleure solution."""
    solver = Solver(p)
    s = p.s
    n_parcels = sum(p.parcels)
    candidates = driver_candidates(n_parcels, s)
    if not candidates:
        return None, [], solver
    budget = max(0.3, s.time_limit_s / max(1, len(candidates)))
    solutions: list[Solution] = []

    def run(k: int) -> Solution:
        sol = solver.solve(k, time.monotonic() + budget)
        solutions.append(sol)
        return sol

    for k in candidates:
        run(k)

    def pick() -> Solution:
        return min(solutions, key=lambda x: (x.cost, len(x.used), x.k))

    # Des colis non attribués malgré tout : on essaie des livreurs supplémentaires (dans la limite disponible).
    k = max(candidates)
    while pick().unassigned and k < s.max_drivers:
        k += 1
        run(k)
    best = pick()
    table = [
        Candidate(sol.k, len(sol.used), sol.cost, sum(solver.ev.eval(r).km for r in sol.used), len(sol.unassigned))
        for sol in sorted(solutions, key=lambda x: x.k)
    ]
    return best, table, solver
