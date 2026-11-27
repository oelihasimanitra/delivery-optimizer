"""Colis, adresses (arrêts) et validation des données d'entrée.

Un colis est un objet à livrer ; un arrêt est une adresse (plusieurs colis à la même adresse
= un seul arrêt, un seul tarif). Aucune donnée n'est supprimée silencieusement : tout colis
écarté apparaît dans la liste `rejected` avec un code et un message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

INF = float("inf")
PRIORITIES = {"normale": 1, "elevee": 2, "urgente": 3}
# Madagascar (boîte englobante large) : filtre les coordonnées manifestement fausses.
LAT_RANGE = (-26.0, -11.0)
LON_RANGE = (43.0, 51.0)
_TIME_RE = re.compile(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{0,2})\s*$")


def parse_time(value) -> int | None:
    """'10:00', '10h', '10h30' -> minutes depuis minuit. Vide -> None. Invalide -> ValueError."""
    if value is None or str(value).strip() == "":
        return None
    match = _TIME_RE.match(str(value))
    if not match:
        raise ValueError(f"Heure invalide : {value!r} (format attendu HH:MM)")
    hours, minutes = int(match.group(1)), int(match.group(2) or 0)
    if hours > 23 or minutes > 59:
        raise ValueError(f"Heure invalide : {value!r}")
    return hours * 60 + minutes


def fmt_time(minutes: float | None) -> str:
    if minutes is None or minutes == INF:
        return "--:--"
    m = int(round(minutes))
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def normalize_priority(value) -> int:
    text = str(value or "normale").strip().lower()
    text = text.replace("é", "e").replace("è", "e")
    if text in ("", "normal"):
        text = "normale"
    if text not in PRIORITIES:
        raise ValueError(f"Priorité invalide : {value!r} (normale, élevée ou urgente)")
    return PRIORITIES[text]


@dataclass
class Parcel:
    id: str
    address: str
    lat: float | None = None
    lon: float | None = None
    earliest: int | None = None  # heure minimale (minutes)
    latest: int | None = None  # heure limite (minutes)
    desired: int | None = None  # heure souhaitée (minutes)
    priority: int = 1
    service_min: float | None = None
    after: str | None = None  # id du colis qui doit être livré avant celui-ci
    note: str = ""


@dataclass
class Stop:
    id: str
    address: str
    lat: float
    lon: float
    parcel_ids: list[str]
    earliest: float
    latest: float
    desired: float | None
    service_min: float
    priority: int
    after: set[str] = field(default_factory=set)  # arrêts qui doivent précéder celui-ci


@dataclass
class Rejected:
    parcel_id: str
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"parcel_id": self.parcel_id, "code": self.code, "message": self.message}


def _num(value, name: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        raise ValueError(f"{name} invalide : {value!r}") from None


def parse_parcels(rows: list[dict]) -> tuple[list[Parcel], list[Rejected]]:
    """Valide les lignes brutes (clés françaises). Retourne les colis valides et les rejets."""
    parcels: list[Parcel] = []
    rejected: list[Rejected] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        pid = str(row.get("id_colis", row.get("id", "")) or "").strip()
        label = pid or f"ligne {index}"
        if not pid:
            rejected.append(Rejected(label, "ID_MANQUANT", "Identifiant de colis manquant."))
            continue
        if pid in seen:
            rejected.append(Rejected(pid, "ID_DUPLIQUE", "Identifiant de colis déjà utilisé : colis ignoré."))
            continue
        seen.add(pid)
        try:
            address = str(row.get("adresse", "") or "").strip()
            lat, lon = _num(row.get("latitude"), "Latitude"), _num(row.get("longitude"), "Longitude")
            parcel = Parcel(
                id=pid,
                address=address,
                lat=lat,
                lon=lon,
                earliest=parse_time(row.get("heure_min")),
                latest=parse_time(row.get("heure_max")),
                desired=parse_time(row.get("heure_souhaitee")),
                priority=normalize_priority(row.get("priorite")),
                service_min=_num(row.get("duree_remise_min"), "Durée de remise"),
                after=(str(row.get("apres_colis") or "").strip() or None),
                note=str(row.get("note", "") or "").strip(),
            )
            if parcel.service_min is not None and parcel.service_min < 0:
                raise ValueError("Durée de remise négative")
        except ValueError as error:
            rejected.append(Rejected(pid, "DONNEE_INVALIDE", str(error)))
            continue
        if parcel.lat is None or parcel.lon is None:
            rejected.append(
                Rejected(pid, "ADRESSE_NON_LOCALISEE", "Adresse sans coordonnées : localisez-la (géocodage ou point sur la carte).")
            )
            continue
        if not (LAT_RANGE[0] <= parcel.lat <= LAT_RANGE[1] and LON_RANGE[0] <= parcel.lon <= LON_RANGE[1]):
            rejected.append(Rejected(pid, "COORDONNEES_HORS_MADAGASCAR", "Coordonnées en dehors de Madagascar : adresse incorrecte ?"))
            continue
        if parcel.earliest is not None and parcel.latest is not None and parcel.earliest > parcel.latest:
            rejected.append(Rejected(pid, "FENETRE_VIDE", "L'heure minimale est après l'heure limite."))
            continue
        parcels.append(parcel)
    return parcels, rejected


def _address_key(parcel: Parcel) -> tuple[float, float]:
    return (round(parcel.lat, 5), round(parcel.lon, 5))  # ~1 m : même point = même arrêt


def _find_cycle_members(after: dict[int, set[int]]) -> set[int]:
    """Retourne les arrêts appartenant à un cycle de dépendances."""
    members: set[int] = set()
    state: dict[int, int] = {}
    stack: list[int] = []

    def visit(node: int) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in after.get(node, ()):
            if state.get(nxt, 0) == 0:
                visit(nxt)
            elif state[nxt] == 1:
                members.update(stack[stack.index(nxt):])
        stack.pop()
        state[node] = 2

    for n in list(after):
        if state.get(n, 0) == 0:
            visit(n)
    return members


def build_stops(
    parcels: list[Parcel], default_service_min: float
) -> tuple[list[Stop], list[list[int]], list[Rejected]]:
    """Regroupe les colis par adresse, fusionne les contraintes et écarte ce qui est impossible.

    Retourne (arrêts, groupes de précédence, rejets). Un groupe est un ensemble d'indices d'arrêts
    liés par un ordre imposé, triés dans un ordre valide ; ils doivent rester chez le même livreur.
    """
    rejected: list[Rejected] = []
    active = list(parcels)

    while True:
        ids = {p.id for p in active}
        removed: list[Rejected] = []
        keep: list[Parcel] = []
        for p in active:
            if p.after is not None and p.after == p.id:
                removed.append(Rejected(p.id, "DEPENDANCE_CIRCULAIRE", "Un colis ne peut pas dépendre de lui-même."))
            elif p.after is not None and p.after not in ids:
                removed.append(
                    Rejected(p.id, "DEPENDANCE_INCONNUE", f"Le colis {p.after!r} qui doit être livré avant n'existe pas ou a été écarté.")
                )
            else:
                keep.append(p)
        if removed:
            rejected += removed
            active = keep
            continue

        # Regroupement par adresse
        order: list[tuple[float, float]] = []
        by_key: dict[tuple[float, float], list[Parcel]] = {}
        for p in active:
            key = _address_key(p)
            if key not in by_key:
                by_key[key] = []
                order.append(key)
            by_key[key].append(p)
        parcel_stop = {p.id: i for i, key in enumerate(order) for p in by_key[key]}

        # Fenêtres vides après fusion
        empty: list[Rejected] = []
        for key in order:
            group = by_key[key]
            earliest = max((p.earliest or 0 for p in group), default=0)
            latest = min((p.latest if p.latest is not None else INF for p in group), default=INF)
            if earliest > latest:
                empty += [
                    Rejected(p.id, "FENETRE_VIDE", "Les contraintes horaires des colis de cette adresse sont incompatibles entre elles.")
                    for p in group
                ]
        if empty:
            rejected += empty
            dead = {r.parcel_id for r in empty}
            active = [p for p in active if p.id not in dead]
            continue

        # Dépendances au niveau des arrêts
        after: dict[int, set[int]] = {}
        for p in active:
            if p.after is not None and parcel_stop[p.after] != parcel_stop[p.id]:
                after.setdefault(parcel_stop[p.id], set()).add(parcel_stop[p.after])
        cyc = _find_cycle_members(after)
        if cyc:
            dead = set()
            for i in cyc:
                for p in by_key[order[i]]:
                    dead.add(p.id)
                    rejected.append(Rejected(p.id, "DEPENDANCE_CIRCULAIRE", "Ordre imposé circulaire entre plusieurs colis."))
            active = [p for p in active if p.id not in dead]
            continue
        break

    stops: list[Stop] = []
    for i, key in enumerate(order):
        group = by_key[key]
        desired = [p.desired for p in group if p.desired is not None]
        stops.append(
            Stop(
                id=f"S{i + 1}",
                address=next((p.address for p in group if p.address), f"{key[0]:.5f}, {key[1]:.5f}"),
                lat=key[0],
                lon=key[1],
                parcel_ids=[p.id for p in group],
                earliest=float(max((p.earliest or 0 for p in group), default=0)),
                latest=min((float(p.latest) if p.latest is not None else INF for p in group), default=INF),
                desired=float(min(desired)) if desired else None,
                service_min=sum(p.service_min if p.service_min is not None else default_service_min for p in group),
                priority=max(p.priority for p in group),
                after={f"S{j + 1}" for j in after.get(i, set())},
            )
        )

    # Groupes de précédence : composantes connexes, triées topologiquement
    index = {s.id: i for i, s in enumerate(stops)}
    neighbours: dict[int, set[int]] = {i: set() for i in range(len(stops))}
    for i, s in enumerate(stops):
        for a in s.after:
            neighbours[i].add(index[a])
            neighbours[index[a]].add(i)
    seen: set[int] = set()
    groups: list[list[int]] = []
    for i in range(len(stops)):
        if i in seen or not neighbours[i]:
            continue
        comp, todo = [], [i]
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            comp.append(n)
            todo.extend(neighbours[n] - seen)
        placed: list[int] = []
        remaining = sorted(comp)
        while remaining:
            for n in remaining:
                if all(index[a] in placed for a in stops[n].after):
                    placed.append(n)
                    remaining.remove(n)
                    break
        groups.append(placed)
    return stops, groups, rejected
