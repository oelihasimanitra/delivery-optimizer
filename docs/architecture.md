# Architecture

Application serveur multi-utilisateurs, **bibliothèque standard Python uniquement** (le réseau étant coupé pendant le développement, FastAPI, Pydantic, PostgreSQL, OR-Tools et React n'étaient pas installables ; voir `DECISIONS.md`). Chaque module a une interface minimale.

| Module | Rôle |
|---|---|
| `config` | Paramètres métier et de planification, validés, sérialisables |
| `distances` | Matrice dirigée ; distance absente → erreur explicite |
| `pricing` | Tarifs clients |
| `route_metrics` | Moyenne, adresses éloignées, tarifs, coût, marge, alertes, explications de prix |
| `models` | Lecture et validation des colis, fusion par adresse, fenêtres, dépendances |
| `routing` | `OSRMProvider` (distances routières), `EstimateProvider` (explicite, non fiable) |
| `geocoding` | Client Nominatim, restriction à Madagascar, point approximatif signalé |
| `optimizer` | Insertion la moins chère + recherche locale (déplacements, 2-opt, échanges), plusieurs nombres de livreurs |
| `explain` | Raisons chiffrées par comparaison avec des alternatives (post-hoc) |
| `planner` | Orchestration : validation, matrice, rejets motivés, optimisation, assemblage du plan JSON |
| `verify` | Vérificateur indépendant : recalcule couverture, capacité, horaires, ordre, prix et totaux à partir du plan |
| `benchmark` | Comparaison avec ordre initial, plus proche voisin, regroupement simple |
| `storage`, `auth`, `server`, `cli` | SQLite, mots de passe/sessions, API HTTP et fichiers statiques, commandes |
| `static/` | Interface (HTML/CSS/JS sans framework, Leaflet ou plan SVG) |

## Flux
CSV/saisie → `models` (rejets motivés) → `routing` (matrice) → rejets d'inaccessibles → `optimizer` (nombre de livreurs, groupes, ordre) → `route_metrics` par tournée → `explain` → plan JSON → `verify` → stockage et affichage.

## Principes
- Un seul évaluateur (`Evaluator`) calcule horaires et coûts : l'optimiseur et les explications ne peuvent pas diverger.
- Le vérificateur ne partage pas ce code : il détecte une erreur de l'évaluateur.
- Aucun repli silencieux sur le vol d'oiseau : le mode estimation est explicite et marque le plan non facturable.
- Le prix facturé n'influence pas l'optimisation.
- Passage possible plus tard à FastAPI/PostgreSQL/OR-Tools : les frontières (`provider.matrix`, `Storage`, `optimize`) restent les mêmes.
