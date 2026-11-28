# delivery-optimizer

Application open source d'organisation des tournées de livraison de colis à moto à Antananarivo : regroupement, nombre de livreurs, ordre des arrêts, horaires, tarifs clients, alertes et explications chiffrées de chaque décision.

## État (version 0.3.0)
Application complète et testée localement : moteur d'optimisation, tarification, serveur multi-utilisateurs, interface web, export CSV, historique. **Non validée** sur de vraies données : OSRM, Nominatim, Leaflet et Docker n'ont pas pu être essayés (pas d'Internet dans l'environnement de développement). Voir `docs/limitations.md`.

## Installation en un clic (Windows, utilisateurs non techniques)
Télécharger le ZIP de la dernière *release*, l'extraire, double-cliquer sur `lancer.bat`. Python, OSRM, les bibliothèques et la carte routière de la région d'Antananarivo (≈ 65 × 65 km) sont dans le ZIP (≈ 38 Mo) : rien à télécharger ni à calculer, fonctionne hors ligne. Mode d'emploi destiné aux utilisateurs : `LISEZMOI.txt`.
**Essayé de bout en bout sur un seul PC Windows (27/11/2026), pas encore sur un Windows vierge ; Madagascar entier n'est pas couvert (voir `docs/limitations.md`).**

Fabriquer le ZIP (développeurs, sous Windows) : `powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1` → `dist\delivery-optimizer-v<version>-windows.zip`. Détails : `docs/deployment.md`.

## Démarrage depuis le code (Python 3.11+, aucune installation)
```
python run.py create-user admin --role admin
python run.py serve          # http://127.0.0.1:8000
python run.py plan src/deliveryopt/static/demo.csv      # sans serveur, en ligne de commande
python run.py benchmark      # compare le moteur à 3 méthodes simples
```
Sans OSRM, les distances sont estimées (vol d'oiseau × 1,4) et clairement signalées comme **non facturables**. Pour des distances routières réelles : `docs/deployment.md`.

## Tests
```
pip install pytest playwright   # playwright et Chrome : seulement pour tests/test_ui.py (ignoré sinon)
pytest
```
Règles tarifaires, modèles, routage, optimiseur et scénarios A à J, serveur, sécurité, CLI, interface dans un vrai navigateur. Dernier résultat mesuré (27/11/2026, Windows, Python 3.15, sans Playwright) : 454 réussis, 1 ignoré (test navigateur).

## Licence
Code sous licence MIT (voir `LICENSE`). Les données cartographiques livrées avec la version Windows sont © contributeurs d'OpenStreetMap, sous licence ODbL (voir `THIRD-PARTY-NOTICES.txt`).

## Documentation
- `docs/user-guide.md` : utilisation
- `docs/deployment.md` : installation, OSRM, sauvegarde, sécurité
- `docs/business-rules.md` : règles métier validées
- `docs/architecture.md` : modules et flux
- `docs/open-questions.md` : décisions encore attendues
- `docs/limitations.md` : limites connues, à lire avant tout usage réel
- `docs/testing.md` : tests
- `DECISIONS.md`, `TASKS.md`, `AGENTS.md` : journal, suivi, règles de travail
