# delivery-optimizer

Application open source d'organisation des tournées de livraison de colis à moto à Antananarivo : regroupement, nombre de livreurs, ordre des arrêts, horaires, tarifs clients, alertes et explications chiffrées de chaque décision.

## État (version 0.2.0)
Application complète et testée localement : moteur d'optimisation, tarification, serveur multi-utilisateurs, interface web, export CSV, historique. **Non validée** sur de vraies données : OSRM, Nominatim, Leaflet et Docker n'ont pas pu être essayés (pas d'Internet dans l'environnement de développement). Voir `docs/limitations.md`.

## Démarrage (Python 3.11+, aucune installation)
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
461 tests (règles tarifaires, modèles, routage, optimiseur et scénarios A à J, serveur, sécurité, CLI, interface dans un vrai navigateur).

## Documentation
- `docs/user-guide.md` : utilisation
- `docs/deployment.md` : installation, OSRM, sauvegarde, sécurité
- `docs/business-rules.md` : règles métier validées
- `docs/architecture.md` : modules et flux
- `docs/open-questions.md` : décisions encore attendues
- `docs/limitations.md` : limites connues, à lire avant tout usage réel
- `docs/testing.md` : tests
- `DECISIONS.md`, `TASKS.md`, `AGENTS.md` : journal, suivi, règles de travail
