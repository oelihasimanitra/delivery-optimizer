"""Orchestration : colis bruts -> plan complet (tournées, horaires, tarifs, alertes, explications)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import AppSettings
from .distances import DistanceMatrix
from .explain import ar, diagnose, explain_assignment, explain_order, km, why_cannot_insert
from .models import INF, Rejected, Stop, build_stops, fmt_time, parse_parcels, parse_time
from .optimizer import Problem, Solution, Solver, optimize
from .route_metrics import summarize_route
from .routing import MatrixResult, Point, RoutingError

MAX_PARCELS = 500
SNAP_WARNING_M = 300.0
LONG_WAIT_MIN = 30.0
UNBALANCED_RATIO = 1.5
SUGGESTIONS = [
    "Ajouter un livreur ou augmenter le nombre maximum de livreurs",
    "Élargir ou déplacer la fenêtre horaire du colis",
    "Avancer l'heure de départ ou repousser la fin de journée",
    "Prévoir une livraison séparée",
]


class PlanningError(RuntimeError):
    """Erreur empêchant de produire un plan (routing indisponible, trop de colis...)."""


@dataclass
class PlanResult:
    plan: dict
    problem: Problem | None
    stops: list[Stop]
    solution: Solution | None
    solver: Solver | None


def _matrix_to_problem(stops, groups, matrix: MatrixResult, index: list[int], app: AppSettings) -> Problem:
    """Sous-matrice (dépôt + arrêts retenus) vers le Problem numérique."""
    nodes = [0] + [i + 1 for i in index]
    factor = app.optimizer.duration_factor
    km_m = [[INF if matrix.km[a][b] is None else matrix.km[a][b] for b in nodes] for a in nodes]
    min_m = [[INF if matrix.minutes[a][b] is None else matrix.minutes[a][b] * factor for b in nodes] for a in nodes]
    s = app.optimizer
    return Problem(
        km=km_m, minutes=min_m,
        earliest=[st.earliest for st in stops], latest=[st.latest for st in stops],
        desired=[st.desired for st in stops], service=[st.service_min for st in stops],
        parcels=[len(st.parcel_ids) for st in stops], weight=[st.priority for st in stops],
        after=[{int(a[1:]) - 1 for a in st.after} for st in stops],
        groups=groups,
        cost_per_km=float(app.pricing.cost_per_km_ar),
        mean_threshold_km=app.pricing.mean_leg_threshold_km,
        s=s, day_start=float(parse_time(s.day_start)), day_end=float(parse_time(s.day_end)),
    )


def _alone_problem(p: Problem, i: int) -> str | None:
    """Raison pour laquelle un arrêt est impossible même seul dans une tournée (None sinon)."""
    s = p.s
    if p.parcels[i] > s.max_parcels_per_driver:
        return f"Plus de {s.max_parcels_per_driver} colis à cette adresse : capacité d'un livreur dépassée."
    arrive = p.day_start + p.minutes[0][i + 1]
    start = max(arrive, p.earliest[i])
    if start > p.latest[i] + 1e-9:
        return (
            f"Impossible même avec un livreur dédié : départ à {fmt_time(p.day_start)}, arrivée au plus tôt à "
            f"{fmt_time(arrive)}, après l'heure limite {fmt_time(p.latest[i])}."
        )
    if start + p.service[i] > p.day_end + 1e-9:
        return f"La remise se terminerait à {fmt_time(start + p.service[i])}, après la fin de journée ({fmt_time(p.day_end)})."
    return None


def run_plan(rows: list[dict], provider, app: AppSettings, date: str | None = None) -> PlanResult:
    if len(rows) > MAX_PARCELS:
        raise PlanningError(f"Trop de colis ({len(rows)}) : maximum {MAX_PARCELS} par plan.")
    started = time.monotonic()
    opt = app.optimizer
    rejected: list[Rejected] = []
    issues: list[dict] = []

    parcels, bad = parse_parcels(rows)
    rejected += bad
    stops, groups, bad = build_stops(parcels, opt.default_service_min)
    rejected += bad

    depot: Point = (app.depot_lat, app.depot_lon)
    matrix = None
    problem = solution = solver = None
    candidates: list = []
    if stops:
        try:
            matrix = provider.matrix([depot] + [(s.lat, s.lon) for s in stops])
        except RoutingError as error:
            raise PlanningError(f"Calcul des distances impossible : {error}") from error

        # Écarter ce qui est impossible AVANT d'optimiser, en le signalant.
        probe = _matrix_to_problem(stops, groups, matrix, list(range(len(stops))), app)
        dead: dict[int, str] = {}
        for i, st in enumerate(stops):
            if probe.km[0][i + 1] == INF:
                dead[i] = "ROUTE_INACCESSIBLE|Aucune route entre le dépôt et cette adresse : le système ne suppose pas qu'une route existe."
            else:
                reason = _alone_problem(probe, i)
                if reason:
                    dead[i] = f"CONTRAINTE_IMPOSSIBLE|{reason}"
            snap = matrix.snap_m[i + 1]
            if snap is not None and snap > SNAP_WARNING_M:
                issues.append({"code": "POINT_LOIN_DE_ROUTE", "stop": st.id, "message": f"{st.address} : le point est à {round(snap)} m de la route la plus proche, vérifiez sa position."})
        for g in groups:  # un groupe d'ordre imposé tombe en entier
            if any(i in dead for i in g):
                for i in g:
                    dead.setdefault(i, "DEPENDANCE_REJETEE|Un colis dont dépend ou qui dépend de celui-ci est impossible à livrer.")
        if dead:
            gone = {pid: dead[i] for i, st in enumerate(stops) if i in dead for pid in st.parcel_ids}
            for pid, text in gone.items():
                code, message = text.split("|", 1)
                rejected.append(Rejected(pid, code, message))
            old_keys = {(round(st.lat, 5), round(st.lon, 5)): i for i, st in enumerate(stops)}
            parcels = [p for p in parcels if p.id not in gone]
            stops, groups, bad = build_stops(parcels, opt.default_service_min)
            rejected += bad
        else:
            old_keys = {(round(st.lat, 5), round(st.lon, 5)): i for i, st in enumerate(stops)}

    if stops:
        index = [old_keys[(round(st.lat, 5), round(st.lon, 5))] for st in stops]
        problem = _matrix_to_problem(stops, groups, matrix, index, app)
        solution, candidates, solver = optimize(problem)

    plan = _assemble(rows, app, date, provider, matrix, stops, problem, solution, solver, candidates, rejected, issues)
    plan["compute_seconds"] = round(time.monotonic() - started, 2)
    return PlanResult(plan, problem, stops, solution, solver)


def _assemble(rows, app, date, provider, matrix, stops, problem, solution, solver, candidates, rejected, issues) -> dict:
    opt, pricing = app.optimizer, app.pricing
    reliable = bool(getattr(provider, "reliable", False))
    alerts: list[dict] = []
    if not reliable:
        alerts.append({"code": "DISTANCES_ESTIMEES", "severity": "critique", "message": "Distances estimées à vol d'oiseau, pas des distances routières : résultats indicatifs, tarifs non facturables."})

    routes_out: list[dict] = []
    unassigned_out: list[dict] = []
    drivers_text = ""
    if solution is not None:
        routes = solution.routes
        used_ids = [ri for ri, r in enumerate(routes) if r]
        rank = {ri: n + 1 for n, ri in enumerate(used_ids)}
        for ri in used_ids:
            route = routes[ri]
            ev = solver.ev.eval(route)
            ids = [stops[i].id for i in route]
            pair_km = {}
            nodes = ["DEPOT"] + ids
            idx = [0] + [i + 1 for i in route]
            for a, ia in zip(nodes, idx):
                for b, ib in zip(nodes, idx):
                    if a != b and problem.km[ia][ib] != INF:
                        pair_km[(a, b)] = problem.km[ia][ib]
            summary = summarize_route(ids, DistanceMatrix(pair_km), pricing, depot="DEPOT")
            route_alerts = [{"code": a.split(":")[0], "severity": "info" if a.startswith("CLIENT_ELOIGNE") else "attention", "message": _alert_text(a, stops, ids)} for a in summary.alerts]
            stops_out = []
            prev_node = 0
            for pos, i in enumerate(route):
                st = stops[i]
                arrive, start, depart = ev.times[pos]
                price = summary.stops[pos]
                stops_out.append({
                    "order": pos + 1, "stop_id": st.id, "address": st.address, "parcel_ids": st.parcel_ids,
                    "lat": st.lat, "lon": st.lon,
                    "arrival": fmt_time(arrive), "service_start": fmt_time(start), "departure": fmt_time(depart),
                    "travel_min": round(problem.minutes[prev_node][i + 1], 2), "wait_min": round(start - arrive, 1), "service_min": st.service_min,
                    "leg_km": round(problem.km[prev_node][i + 1], 3),
                    "window": {"earliest": fmt_time(st.earliest) if st.earliest > 0 else None, "latest": fmt_time(st.latest) if st.latest < INF else None},
                    "desired": fmt_time(st.desired) if st.desired is not None else None,
                    "priority": st.priority,
                    "price_ar": price.price_ar, "is_distant": price.is_distant, "billable_km": None if price.billable_km is None else round(price.billable_km, 3),
                    "price_explanation": price.explanation,
                    "why_assigned": explain_assignment(solver, stops, routes, ri, pos),
                    "why_order": explain_order(solver, stops, route, pos),
                })
                if (start - arrive) > LONG_WAIT_MIN:
                    route_alerts.append({"code": "ATTENTE_IMPORTANTE", "severity": "attention", "message": f"{st.address} : attente de {round(start - arrive)} min avant l'heure minimale."})
                prev_node = i + 1
            if opt.target_min_parcels and ev.parcels < min(opt.target_min_parcels, sum(problem.parcels) // max(1, len(used_ids))):
                route_alerts.append({"code": "SOUS_CIBLE", "severity": "info", "message": f"{ev.parcels} colis, sous la cible de {opt.target_min_parcels}."})
            routes_out.append({
                "driver": rank[ri], "stops": stops_out, "parcel_count": ev.parcels,
                "distance_km": round(summary.total_distance_km, 2), "duration_min": round(ev.end - problem.day_start, 1),
                "end_time": fmt_time(ev.end), "wait_min": round(ev.wait, 1),
                "mean_leg_km": None if summary.raw_mean_km is None else round(summary.raw_mean_km, 2),
                "group_mean_leg_km": None if summary.group_mean_km is None else round(summary.group_mean_km, 2),
                "cost_ar": summary.cost_ar, "revenue_ar": summary.revenue_ar, "margin_ar": summary.margin_ar,
                "alerts": route_alerts,
            })
        durations = [r["duration_min"] for r in routes_out]
        if len(durations) >= 2 and min(durations) > 0 and max(durations) / min(durations) > UNBALANCED_RATIO:
            alerts.append({"code": "TOURNEES_DESEQUILIBREES", "severity": "attention", "message": f"Durées de tournée très inégales : de {round(min(durations))} à {round(max(durations))} min."})

        for s_idx in solution.unassigned:
            st = stops[s_idx]
            group = problem.group_of[s_idx]
            if opt.max_drivers == 0:
                reason = "Aucun livreur disponible."
            else:
                causes = {why_cannot_insert(problem, stops, r, group) for r in routes if r} or {"capacité ou horaires"}
                reason = "Ne peut être inséré dans aucune tournée sans violer une contrainte : " + " ; ".join(sorted(causes)) + "."
                if len(solution.used) >= opt.max_drivers:
                    reason += f" Les {opt.max_drivers} livreurs disponibles sont déjà utilisés."
            unassigned_out.append({"stop_id": st.id, "parcel_ids": st.parcel_ids, "address": st.address, "code": "NON_ATTRIBUE", "reason": reason, "suggestions": SUGGESTIONS})
        if solution.unassigned:
            alerts.append({"code": "COLIS_NON_ATTRIBUES", "severity": "critique", "message": f"{sum(len(stops[i].parcel_ids) for i in solution.unassigned)} colis non attribués (voir détails)."})
        drivers_text = _drivers_text(candidates, solution, problem)
    elif not rejected and not rows:
        alerts.append({"code": "AUCUN_COLIS", "severity": "info", "message": "Aucun colis à planifier."})
    else:
        if opt.max_drivers == 0 and stops:
            for st in stops:
                unassigned_out.append({"stop_id": st.id, "parcel_ids": st.parcel_ids, "address": st.address, "code": "NON_ATTRIBUE", "reason": "Aucun livreur disponible.", "suggestions": SUGGESTIONS[:1]})
            alerts.append({"code": "AUCUN_LIVREUR", "severity": "critique", "message": "Aucun livreur disponible : les colis ne sont pas attribués."})

    if rejected:
        alerts.append({"code": "COLIS_ECARTES", "severity": "critique", "message": f"{len(rejected)} colis écartés (adresse incorrecte, contrainte impossible ou donnée invalide) : voir détails."})
    if rows and not routes_out:
        alerts.append({"code": "AUCUNE_SOLUTION", "severity": "critique", "message": "Aucune solution satisfaisante : aucun colis n'a pu être planifié."})

    totals = {
        "drivers": len(routes_out),
        "parcels_planned": sum(r["parcel_count"] for r in routes_out),
        "distance_km": round(sum(r["distance_km"] for r in routes_out), 2),
        "cost_ar": sum(r["cost_ar"] for r in routes_out),
        "revenue_ar": sum(r["revenue_ar"] for r in routes_out),
        "margin_ar": sum(r["margin_ar"] for r in routes_out),
        "distant_addresses": sum(1 for r in routes_out for s in r["stops"] if s["is_distant"]),
    }
    return {
        "date": date, "routing_mode": getattr(provider, "mode", "unknown"), "billing_reliable": reliable,
        "depot": {"name": app.depot_name, "lat": app.depot_lat, "lon": app.depot_lon},
        "totals": totals, "routes": routes_out, "unassigned": unassigned_out,
        "rejected": [r.to_dict() for r in rejected], "issues": issues, "alerts": alerts,
        "drivers_choice": {"text": drivers_text, "candidates": [{"drivers_allowed": c.k, "drivers_used": c.drivers_used, "cost_ar": round(c.cost), "distance_km": round(c.km, 1), "unassigned_stops": c.unassigned} for c in candidates]},
        "input_parcels": len(rows),
        "settings": app.to_dict(),
    }


def _alert_text(code: str, stops: list[Stop], ids: list[str]) -> str:
    name, _, arg = code.partition(":")
    by_id = {s.id: s for s in stops}
    if name == "CLIENT_ELOIGNE":
        return f"{by_id[arg].address} : adresse éloignée du groupe (tarif à la distance)."
    return {
        "MOYENNE_SUPERIEURE_AU_SEUIL": "Distance moyenne entre arrêts supérieure au seuil.",
        "TOURNEE_DISPERSEE": "Tournée dispersée : plus de la moitié des arrêts sont éloignés.",
        "SEUIL_NON_RESPECTE": "Seuil de distance non respecté même après retrait des adresses éloignées.",
        "TOURNEE_MULTI_ZONES": "La tournée couvre plusieurs zones éloignées les unes des autres : envisager de la séparer entre livreurs.",
    }.get(name, name)


def _drivers_text(candidates, solution: Solution, problem: Problem) -> str:
    used = len(solution.used)
    if not candidates:
        return ""
    lines = [f"{used} livreur(s) retenu(s). Coût total de l'objectif par hypothèse testée :"]
    for c in candidates:
        lines.append(f"- jusqu'à {c.k} livreur(s) : {c.drivers_used} utilisé(s), objectif {ar(c.cost)}, {km(c.km)}, {c.unassigned} arrêt(s) non attribué(s)")
    s = problem.s
    lines.append(
        f"Chaque livreur porte au plus {s.max_parcels_per_driver} colis ; l'objectif combine le coût kilométrique, les attentes, "
        f"l'écart à l'heure souhaitée, l'équilibre des charges et la cible de {s.target_min_parcels} colis."
    )
    return "\n".join(lines)
