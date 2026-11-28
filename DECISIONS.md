# Journal des décisions

| Date | Décision | Raison |
|---|---|---|
| 2026-11-23 | Équipe d'agents allégée : orchestrateur, routing + optimisation, backend + frontend, QA indépendant (aux étapes optimiseur et finale) | Éviter que le suivi du processus coûte plus que le développement |
| 2026-11-23 | Un seul paquet Python `deliveryopt` au départ, sous-modules ajoutés au fil des besoins | Pas de dossiers vides ; la séparation `backend/`, `optimizer/`, `routing/` du document d'origine reste possible plus tard |
| 2026-11-23 | Seuil par trajet de 5 km ajouté à la moyenne de 3 km | La moyenne seule ne signale pas un détour isolé (exemple : trajets 1,2 / 2 / 1,5 / 1 / 8 km → moyenne 2,74 km) |
| 2026-11-23 | Éloignés désignés par retrait successif du plus grand détour ; distance facturable depuis l'arrêt du groupe le plus proche | Déterministe, explicable, indépendante de l'ordre des autres éloignés |
| 2026-11-23 | Dépôt → premier arrêt exclu de la moyenne, inclus dans le coût interne | Choix par défaut validé, réglable |
| 2026-11-23 | Le prix facturé n'influence pas l'optimisation | Éviter que le système crée des clients éloignés pour gagner plus |
| 2026-11-23 | 20 colis maximum strict, 7 en cible | Avec moins de 7 colis au total, une tournée de 7 est impossible |
| 2026-11-23 | Ordre imposé : même livreur | Éviter la synchronisation entre livreurs |
| 2026-11-23 | Aucune distance à vol d'oiseau en repli | Exigence du cahier des charges, phase 5 |
| 2026-11-23 | Bibliothèque standard uniquement (http.server, sqlite3, scrypt, dataclasses) au lieu de FastAPI, Pydantic, PostgreSQL, OR-Tools, React | Réseau coupé : rien n'était installable. Frontières conservées pour migrer plus tard ; déploiement sans dépendances |
| 2026-11-23 | Seuil par trajet : ne retire que les arrêts isolés ; sinon alerte TOURNEE_MULTI_ZONES | La règle simple marquait 18 adresses sur 20 comme éloignées sur des tournées de 4 zones |
| 2026-11-23 | Mode estimation explicite (alerte critique, plan non facturable) | Exigence « pas de repli silencieux » conciliée avec un démarrage possible sans OSRM |
| 2026-11-23 | Vérificateur de plan indépendant exécuté sur chaque plan | Détecter une erreur de l'évaluateur de l'optimiseur |
| 2026-11-23 | Corps de requête toujours lu avant le routage | Bug trouvé par le test navigateur : un POST non lu corrompait la requête suivante (connexion persistante) |
| 2026-11-27 | Distribution Windows : ZIP autonome (Python embeddable + binaires OSRM Windows + DLL Visual C++), carte téléchargée au premier lancement | Utilisateurs non techniques, pas de git ni d'administrateur ; Docker (WSL2, droits admin) écarté |
| 2026-11-27 | Plus de serveur OSRM public par défaut dans `lancer.bat` ; en cas d'échec d'OSRM, choix explicite du mode estimation | Les coordonnées des adresses clients ne partent pas chez un tiers sans qu'on le dise ; pas de repli silencieux |
| 2026-11-27 | Test `test_keepalive_connection_…` : `ConnectionAbortedError` ajouté aux coupures acceptées | Échec préexistant sous Windows (WinError 10053) ; la coupure de connexion était déjà prévue par le test |
| 2026-11-27 | Outils OSRM lancés avec des chemins relatifs au dossier de l'application | OSRM rejette un chemin absolu contenant un accent (constaté à l'essai) ; « Téléchargements » est accentué en français |
| 2026-11-27 | Madagascar entier abandonné : carte limitée à la région d'Antananarivo (≈ 65 × 65 km), préparée au build et livrée prête dans le ZIP | `osrm-extract` échoue (« bad allocation ») sur Madagascar entier avec 7,9 Go de RAM ; la région se prépare en ≈ 12 s et le ZIP ne grossit que de ≈ 17 Mo ; aucun téléchargement ni calcul chez l'utilisateur |
| 2026-11-28 | `/api/login` renvoie les mêmes champs que `/api/me` (`session_info`) | Bug trouvé à l'essai : l'interface affichait « MODE ESTIMATION » après connexion même avec OSRM (`billing_reliable` absent de la réponse de login) ; le test existant figeait l'ancien contrat, il est mis à jour et un test de régression est ajouté |
| 2026-11-28 | Licence du code : MIT (titulaire « Oely », 2026) ; zone de carte Antananarivo conservée pour l'instant | Choix du propriétaire ; la carte livrée reste sous ODbL (distinct du code) ; zone à revoir avec les vraies adresses |
