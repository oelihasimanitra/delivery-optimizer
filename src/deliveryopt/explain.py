"""Explications chiffrées des décisions : pourquoi ce groupe, ce livreur, cet ordre.

OR-Tools ou toute heuristique ne justifient pas leurs choix. Les explications sont donc construites
après coup par comparaison avec des alternatives chiffrées (placer l'arrêt ailleurs, échanger deux
arrêts), évaluées avec le même calcul de tournée que l'optimiseur.
"""

from __future__ import annotations

from .models import INF, Stop, fmt_time
from .optimizer import Problem, Solver


def ar(value: float) -> str:
    return f"{round(value):,}".replace(",", " ") + " Ar"


def km(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " km"


def diagnose(p: Problem, stops: list[Stop], route: tuple[int, ...]) -> str | None:
    """Explique en français pourquoi une tournée est infaisable (None si elle est faisable)."""
    s = p.s
    if sum(p.parcels[i] for i in route) > s.max_parcels_per_driver:
        return f"capacité dépassée (plus de {s.max_parcels_per_driver} colis)"
    pos = {x: i for i, x in enumerate(route)}
    for x in route:
        for a in p.after[x]:
            if a in pos and pos[a] > pos[x]:
                return f"ordre imposé non respecté ({stops[a].address} doit précéder {stops[x].address})"
    t, prev = p.day_start, 0
    for x in route:
        node = x + 1
        if p.km[prev][node] == INF:
            return f"aucune route entre deux arrêts ({stops[x].address})"
        arrive = t + p.minutes[prev][node]
        start = max(arrive, p.earliest[x])
        if start > p.latest[x] + 1e-9:
            return f"arrivée à {fmt_time(arrive)} après l'heure limite {fmt_time(p.latest[x])} ({stops[x].address})"
        t, prev = start + p.service[x], node
    if t > p.day_end + 1e-9:
        return f"fin de journée dépassée ({fmt_time(t)} après {fmt_time(p.day_end)})"
    return None


def why_cannot_insert(p: Problem, stops: list[Stop], route: tuple[int, ...], group: tuple[int, ...]) -> str:
    """Raison la plus fréquente pour laquelle un groupe ne peut entrer dans une tournée."""
    counts: dict[str, int] = {}
    for stop in group:
        for pos in range(len(route) + 1):
            reason = diagnose(p, stops, route[:pos] + (stop,) + route[pos:])
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return "contraintes incompatibles"
    return max(counts, key=lambda r: (counts[r], r))


def explain_assignment(solver: Solver, stops: list[Stop], routes: list[tuple[int, ...]], ri: int, position: int) -> list[str]:
    p = solver.p
    route = routes[ri]
    stop = route[position]
    group = p.group_of[stop]
    lines: list[str] = []

    prev_node = route[position - 1] + 1 if position > 0 else 0
    here = stop + 1
    before = p.km[prev_node][here]
    if position == 0:
        lines.append(f"Premier arrêt de la tournée : {km(before)} depuis le dépôt.")
    else:
        lines.append(f"Enchaîné après {stops[route[position - 1]].address} ({km(before)}).")
    if position + 1 < len(route):
        lines.append(f"Suivi de {stops[route[position + 1]].address} ({km(p.km[here][route[position + 1] + 1])}).")

    full = solver.ev.eval(route)
    without = solver.ev.eval(tuple(x for x in route if x not in group))
    # Retirer l'arrêt peut rendre le reste infaisable (ex. tronçon bloqué entre ses voisins) : pas de gain chiffrable.
    saving = full.cost - without.cost if without is not None else None
    if saving is None:
        saving_text = "rendrait le reste de la tournée irréalisable (tronçon impraticable ou ordre imposé)"
    elif saving < 0:
        saving_text = f"augmenterait le coût de la tournée de {ar(-saving)} (attentes, détour)"
    else:
        saving_text = f"économiserait {ar(saving)}"
    options = []
    for rj, other in enumerate(routes):
        if rj == ri or not other:
            continue
        cand = solver.insert_group(other, group)
        if cand is None:
            options.append((INF, f"Chez le livreur {rj + 1} : impossible ({why_cannot_insert(p, stops, other, group)})."))
        else:
            e_old, e_new = solver.ev.eval(other), solver.ev.eval(cand)
            delta = e_new.cost - e_old.cost
            options.append((delta, f"Chez le livreur {rj + 1} : +{ar(delta)} (+{km(e_new.km - e_old.km)})."))
    if options:
        lines.append(f"Retirer cet arrêt de cette tournée {saving_text}. Alternatives :")
        lines.extend(text for _, text in sorted(options, key=lambda o: o[0])[:3])
    else:
        lines.append(f"Aucune autre tournée en cours : retirer cet arrêt {saving_text}, mais le colis ne serait plus livré.")
    return lines


def explain_order(solver: Solver, stops: list[Stop], route: tuple[int, ...], position: int) -> list[str]:
    p = solver.p
    stop = route[position]
    s = stops[stop]
    e = solver.ev.eval(route)
    arrive, start, depart = e.times[position]
    lines: list[str] = []

    for a in sorted(p.after[stop]):
        lines.append(f"Ordre imposé : doit être livré après {stops[a].address}.")
    for other in route:
        if stop in p.after[other]:
            lines.append(f"Ordre imposé : doit être livré avant {stops[other].address}.")
    if start - arrive > 0.5:
        lines.append(
            f"Arrivée à {fmt_time(arrive)}, heure minimale {fmt_time(p.earliest[stop])} : attente de {round(start - arrive)} min."
        )
    elif p.latest[stop] < INF or p.earliest[stop] > 0:
        if p.latest[stop] < INF and p.earliest[stop] > 0:
            window = f"{fmt_time(p.earliest[stop])}–{fmt_time(p.latest[stop])}"
        elif p.latest[stop] < INF:
            window = f"avant {fmt_time(p.latest[stop])}"
        else:
            window = f"à partir de {fmt_time(p.earliest[stop])}"
        lines.append(f"Contrainte horaire {window} respectée (remise à {fmt_time(start)}).")
    if p.desired[stop] is not None:
        lines.append(f"Heure souhaitée {fmt_time(p.desired[stop])} : remise à {fmt_time(start)} (écart {round(abs(start - p.desired[stop]))} min).")
    if position + 1 < len(route):
        swapped = route[:position] + (route[position + 1], route[position]) + route[position + 2:]
        e2 = solver.ev.eval(swapped)
        nxt = stops[route[position + 1]].address
        if e2 is None:
            lines.append(f"Inverser avec {nxt} est impossible ({diagnose(p, stops, swapped)}).")
        else:
            lines.append(f"Inverser avec {nxt} coûterait {'+' if e2.cost >= e.cost else ''}{ar(e2.cost - e.cost)}.")
    if not lines:
        lines.append("Ordre qui minimise le trajet total de la tournée.")
    return lines
