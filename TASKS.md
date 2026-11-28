# Suivi des tâches

Statuts : TODO, IN_PROGRESS, BLOCKED, REVIEW, TESTING, DONE.

| ID | Titre | Responsable | Priorité | Dépend de | Statut | Résultat attendu / tests |
|---|---|---|---|---|---|---|
| T-001 | Structure du dépôt, documentation de base | Orchestrateur | Haute | – | DONE | Dépôt installable, `pytest` fonctionne |
| T-002 | Règles métier validées | Orchestrateur + utilisateur | Haute | – | DONE | `docs/business-rules.md` |
| T-003 | Tarifs, adresses éloignées, coût, alertes | Orchestrateur | Haute | T-002 | REVIEW | 339 tests passent ; audit indépendant à faire |
| T-004 | Modèles de données, fusion par adresse, dépendances | Backend | Haute | T-002 | DONE | `test_models` |
| T-005 | Routing OSRM, matrice, mode estimation explicite | Routing | Haute | T-004 | DONE (non essayé contre un vrai OSRM) | `test_routing_geocoding`, scénario H |
| T-006 | Géocodage Nominatim, cache, point placé sur la carte | Routing | Moyenne | T-004 | DONE (non essayé contre un vrai Nominatim) | `test_routing_geocoding`, `test_server`, `test_ui` |
| T-007 | Optimiseur (insertion + recherche locale) et benchmark | Optimisation | Haute | T-003, T-004 | DONE (paramètres provisoires, question E) | scénarios A à J, benchmark |
| T-008 | Explications chiffrées | Optimisation | Haute | T-007 | DONE | `test_scenarios` |
| T-009 | API, authentification, stockage | Backend | Moyenne | T-004, T-007 | DONE (SQLite) | `test_server`, `test_storage_auth` |
| T-010 | Interface web | Frontend | Moyenne | T-009 | DONE | `test_ui` (Chrome réel) |
| T-011 | Docker, déploiement, documentation | Orchestrateur | Moyenne | T-009 | REVIEW (Docker jamais exécuté) | `docs/deployment.md` |
| T-012 | Audit final indépendant | QA | Haute | tout | TODO | À faire par une personne ou un agent qui n'a pas écrit le code |
| T-013 | Essai sur de vraies données (OSRM, adresses réelles, calibrage des poids et du profil moto) | Utilisateur + orchestrateur | Haute | T-011 | TODO | Réponses aux questions E et G |
| T-014 | Release Windows « un clic » (ZIP, lanceur, build) | Orchestrateur | Haute | T-011 | TESTING | Essai de bout en bout réussi sur 1 PC (27/11/2026, dossier accentué, OSRM réel, Chrome). Reste : essai sur un Windows vierge, décision licence, publication de la release |
