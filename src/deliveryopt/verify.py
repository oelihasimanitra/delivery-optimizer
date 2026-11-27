"""Vérificateur indépendant d'un plan.

Il ne réutilise NI l'optimiseur NI le calcul des tournées : il repart des colis d'entrée et du
plan produit, recalcule les horaires, les capacités, l'ordre imposé, la couverture des colis et
les tarifs, et retourne la liste des écarts (liste vide = plan cohérent).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from .config import AppSettings

_T = re.compile(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{0,2})\s*$")


def _minutes(value) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    m = _T.match(str(value))
    return int(m.group(1)) * 60 + int(m.group(2) or 0) if m else None


def _price_distant(km: float, s) -> int:
    step = Decimal(str(s.km_round_step))
    rounding = "ROUND_HALF_UP" if s.km_round_mode == "half_up" else "ROUND_CEILING"
    q = (Decimal(repr(float(km))) / step).to_integral_value(rounding=rounding) * step
    return int((q * s.distant_price_per_km_ar).to_integral_value(rounding=ROUND_HALF_UP)) + s.distant_waiting_fee_ar


def verify_plan(plan: dict, rows: list[dict], app: AppSettings, tol_min: float = 1.01) -> list[str]:
    errors: list[str] = []
    opt, pricing = app.optimizer, app.pricing
    raw = {str(r.get("id_colis", r.get("id", ""))).strip(): r for r in rows if str(r.get("id_colis", r.get("id", ""))).strip()}
    day_start, day_end = _minutes(opt.day_start), _minutes(opt.day_end)

    # 1. Couverture : chaque colis apparaît une fois et une seule (planifié, non attribué ou écarté).
    seen: dict[str, str] = {}

    def mark(pid: str, where: str) -> None:
        if pid in seen:
            errors.append(f"Colis {pid} présent deux fois ({seen[pid]} et {where})")
        seen[pid] = where

    where_route: dict[str, tuple[int, int]] = {}
    for r in plan["routes"]:
        for s in r["stops"]:
            for pid in s["parcel_ids"]:
                mark(pid, f"livreur {r['driver']}")
                where_route[pid] = (r["driver"], s["order"])
    for u in plan["unassigned"]:
        for pid in u["parcel_ids"]:
            mark(pid, "non attribué")
    for rej in plan["rejected"]:
        if rej["parcel_id"] in raw:
            mark(rej["parcel_id"], "écarté")
    for pid in raw:
        if pid not in seen:
            errors.append(f"Colis {pid} a disparu (ni planifié, ni non attribué, ni écarté)")
    for pid in seen:
        if pid not in raw:
            errors.append(f"Colis {pid} inconnu dans l'entrée")

    # 2. Tournées : capacité, horaires, fenêtres, tarifs.
    total_rev = total_cost = 0
    for r in plan["routes"]:
        n = sum(len(s["parcel_ids"]) for s in r["stops"])
        if n != r["parcel_count"]:
            errors.append(f"Livreur {r['driver']} : parcel_count incohérent")
        if n > opt.max_parcels_per_driver:
            errors.append(f"Livreur {r['driver']} : {n} colis, capacité {opt.max_parcels_per_driver} dépassée")
        t = day_start
        km_sum = 0.0
        for s in r["stops"]:
            ps = [raw[pid] for pid in s["parcel_ids"] if pid in raw]
            earliest = max([_minutes(p.get("heure_min")) or 0 for p in ps] or [0])
            latest = min([_minutes(p.get("heure_max")) if _minutes(p.get("heure_max")) is not None else 10**9 for p in ps] or [10**9])
            arrive = t + s["travel_min"]
            start = max(arrive, earliest)
            if abs(_minutes(s["arrival"]) - arrive) > tol_min or abs(_minutes(s["service_start"]) - start) > tol_min:
                errors.append(f"Livreur {r['driver']} arrêt {s['order']} : horaires recalculés différents ({s['arrival']}/{s['service_start']})")
            if start > latest + tol_min:
                errors.append(f"Livreur {r['driver']} arrêt {s['order']} : livré à {s['service_start']} après l'heure limite")
            if _minutes(s["service_start"]) < earliest - tol_min:
                errors.append(f"Livreur {r['driver']} arrêt {s['order']} : livré avant l'heure minimale")
            t = start + s["service_min"]
            km_sum += s["leg_km"]
            if s["leg_km"] < 0 or s["travel_min"] < 0:
                errors.append(f"Livreur {r['driver']} arrêt {s['order']} : distance ou durée négative")
            expected = _price_distant(s["billable_km"], pricing) if s["is_distant"] else pricing.flat_price_ar
            if s["price_ar"] != expected:
                errors.append(f"Livreur {r['driver']} arrêt {s['order']} : prix {s['price_ar']} Ar, attendu {expected} Ar")
        if t > day_end + tol_min:
            errors.append(f"Livreur {r['driver']} : fin de journée dépassée")
        if abs(km_sum - r["distance_km"]) > 0.02 * max(1, len(r["stops"])):
            errors.append(f"Livreur {r['driver']} : distance totale incohérente ({km_sum:.2f} vs {r['distance_km']})")
        if abs(r["cost_ar"] - r["distance_km"] * pricing.cost_per_km_ar) > 10 + 5 * len(r["stops"]):
            errors.append(f"Livreur {r['driver']} : coût incohérent avec la distance")
        if r["revenue_ar"] != sum(s["price_ar"] for s in r["stops"]):
            errors.append(f"Livreur {r['driver']} : total des tarifs incohérent")
        if r["margin_ar"] != r["revenue_ar"] - r["cost_ar"]:
            errors.append(f"Livreur {r['driver']} : marge incohérente")
        legs = [s["leg_km"] for s in r["stops"][1:]]
        if legs and r["mean_leg_km"] is not None and abs(sum(legs) / len(legs) - r["mean_leg_km"]) > 0.02:
            errors.append(f"Livreur {r['driver']} : moyenne des trajets incohérente")
        total_rev += r["revenue_ar"]
        total_cost += r["cost_ar"]

    # 3. Ordre imposé : le prérequis doit être livré avant, chez le même livreur.
    for pid, row in raw.items():
        before = str(row.get("apres_colis") or "").strip()
        if not before or pid not in where_route:
            continue
        if before not in where_route:
            errors.append(f"Colis {pid} planifié alors que son prérequis {before} ne l'est pas")
            continue
        (d1, o1), (d2, o2) = where_route[before], where_route[pid]
        if d1 != d2 or o1 > o2:
            errors.append(f"Ordre imposé non respecté : {before} doit précéder {pid}")

    # 4. Totaux et cohérence du mode de routing.
    if plan["totals"]["revenue_ar"] != total_rev or plan["totals"]["cost_ar"] != total_cost:
        errors.append("Totaux du plan incohérents avec les tournées")
    if plan["routing_mode"] != "osrm" and (plan["billing_reliable"] or not any(a["code"] == "DISTANCES_ESTIMEES" for a in plan["alerts"])):
        errors.append("Distances estimées non signalées comme telles")
    return errors
