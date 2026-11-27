# Tests

```
pip install pytest           # + playwright et Chrome pour tests/test_ui.py (ignoré sinon)
pytest                       # 461 tests, environ 45 s
```

| Fichier | Contenu |
|---|---|
| `test_pricing`, `test_distances`, `test_route_metrics`, `test_properties` | Tarifs (5 km → 6 000 Ar, 10 km → 11 000 Ar, continuité à 3 km), distance manquante = erreur, adresses éloignées, 300 tournées aléatoires |
| `test_models` | Validation des colis, fusion par adresse, fenêtres, dépendances (inconnue, circulaire) |
| `test_routing_geocoding` | OSRM (faux serveur), découpage de la matrice, erreurs, Nominatim (User-Agent, Madagascar, approximatif) |
| `test_scenarios` | Scénarios A à J du cahier des charges, capacité stricte, fin de journée, mode estimation, 12 instances aléatoires vérifiées par le vérificateur indépendant, détection de plans falsifiés, benchmark |
| `test_storage_auth` | SQLite, hachage, jetons, blocage après échecs |
| `test_server` | API réelle : droits, origine, JSON, cycle d'un plan, export CSV, fichiers statiques et traversée de chemin, XSS, injection CSV, connexions persistantes, concurrence, fuites de trace |
| `test_cli` | Commandes, fabrique de fournisseurs, vrai processus serveur |
| `test_ui` | Chrome réel, réseau externe bloqué : connexion, parcours complet, explications, export, historique, XSS non exécuté, clic carte, import CSV, paramètres, comptes |

Limites : voir `limitations.md`. Les tests d'interface valident le fonctionnement, pas l'ergonomie sur mobile ni sur d'autres navigateurs.
