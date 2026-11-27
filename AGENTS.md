# Règles de travail des agents

- Une tâche = un agent responsable. Deux agents ne modifient jamais le même fichier en même temps.
- Une tâche n'est DONE que si : travail fait, tests exécutés et réussis, critères d'acceptation remplis, documentation à jour, limites signalées, vérifié par l'orchestrateur. Composant critique : audit indépendant en plus.
- Ne jamais inventer un résultat de test, ni masquer un problème, ni supprimer un test pour le faire passer.
- Aucune décision métier ambiguë sans la signaler dans `docs/open-questions.md`.
- Distances routières uniquement : pas de repli silencieux sur le vol d'oiseau.
- Pas de secrets dans Git, pas de données clients réelles dans les tests.
- Rapport de fin de tâche : objectif, travail, fichiers créés et modifiés, décisions, tests et résultats, problèmes, limites, risques, tâches restantes, décisions demandées à l'utilisateur.
