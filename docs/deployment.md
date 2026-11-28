# Déploiement

## 0. Windows, sans rien installer (version ZIP)
Pour les utilisateurs qui ne veulent rien installer : ZIP de la *release*, voir `LISEZMOI.txt`.
- **Contenu du ZIP** (≈ 38 Mo) : l'application, Python « embeddable » 3.13.17, les binaires OSRM v26.11.0 pour Windows (`osrm-routed`, `osrm-extract`, `osrm-partition`, `osrm-customize`) avec leurs profils, les DLL Visual C++ (`MSVCP140.dll`… absentes d'un Windows vierge), **la carte routière déjà préparée** de la région d'Antananarivo (`osrm-data\`), `LISEZMOI.txt`, `THIRD-PARTY-NOTICES.txt`.
- **Zone couverte** : rectangle latitude -19,20 à -18,60, longitude 47,20 à 47,80 (≈ 65 × 65 km autour de la capitale). Réglable dans `scripts/common.ps1` (`$MapBbox`). Un colis hors zone est signalé par l'alerte `POINT_LOIN_DE_ROUTE`.
- **Pourquoi pas tout Madagascar** : sur un PC de 7,9 Go de RAM, `osrm-extract` échoue (« bad allocation ») sur la carte entière (essai du 27/11/2026). La région d'Antananarivo se prépare en ≈ 12 s.
- **Première utilisation** (`lancer.bat` → `scripts/launcher.ps1`) : demande un compte administrateur, démarre `osrm-routed` sur `127.0.0.1:5055` puis l'application sur `127.0.0.1:8000`, ouvre le navigateur. Fermer la fenêtre arrête tout. Journaux dans `logs\`. Aucun téléchargement ni calcul chez l'utilisateur ; fonctionne hors ligne.
- **Si OSRM est indisponible**, le lanceur le dit et demande s'il faut continuer en mode estimation (non facturable) : jamais de repli silencieux. `DELIVERYOPT_OSRM_URL` défini dans l'environnement = OSRM externe utilisé tel quel.
- **Mises à jour** : le ZIP n'est pas mis à jour automatiquement ; l'utilisateur extrait la nouvelle version (qui contient sa propre carte à jour) et recopie `data\`. La carte est figée à la date du build (`osrm-data\MAP-INFO.txt`).
- **Fabriquer le ZIP** : `powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1` (Windows, Internet, `tar.exe` et les DLL Visual C++ présentes dans System32). Les versions de Python et d'OSRM et leurs SHA-256 sont épinglés dans `scripts/fetch-tools.ps1` ; les profils Lua viennent de l'archive source GitHub du même tag (pas de somme de contrôle épinglée). Les routes sont téléchargées une fois depuis Overpass (API publique d'OpenStreetMap, parfois saturée : le script réessaie ; `dist\cache\antananarivo.osm` sert de cache, `-RefreshMap` pour renouveler), puis préparées avec les outils OSRM embarqués (`scripts/prepare-map.ps1`).
- **Publier** : `gh release create v<version> dist\delivery-optimizer-v<version>-windows.zip dist\SHA256SUMS.txt`.
- **Licence des données** : les fichiers `osrm-data` sont une base dérivée d'OpenStreetMap (ODbL) ; voir `THIRD-PARTY-NOTICES.txt`.

> **Essai du 27/11/2026** (Windows 11, ZIP extrait dans un dossier accentué avec espace) : lancement sans aucune question, OSRM et application démarrés, distances routières réelles (dépôt → Ivato 19,9 km), plan de démonstration calculé dans Chrome sans bandeau « MODE ESTIMATION », total facturable, vérification indépendante cohérente. **Pas encore essayé sur un Windows vierge** (sans Python ni DLL Visual C++) : voir `docs/limitations.md`.

## 1. Démarrage rapide (sans Docker, mode estimation)
Python 3.11 ou plus, rien à installer.
```
python run.py create-user admin --role admin      # demande un mot de passe (8 caractères minimum)
python run.py serve                               # http://127.0.0.1:8000
```
Ou sans question interactive : `DELIVERYOPT_ADMIN_USER=admin DELIVERYOPT_ADMIN_PASSWORD=... python run.py serve` (crée l'administrateur au premier démarrage si la base est vide).

Sans OSRM, l'application fonctionne en **mode estimation** : distances à vol d'oiseau × 1,4. Une bannière rouge s'affiche, chaque plan porte l'alerte `DISTANCES_ESTIMEES` et son total est marqué « non facturable ». C'est utilisable pour essayer l'outil, **pas pour facturer**.

## 2. Mise en production (distances routières réelles)
Prérequis : un serveur Linux avec Docker, Internet pour le téléchargement initial des cartes.
```
cp .env.example .env            # puis éditer : mot de passe administrateur, contact Nominatim
./scripts/prepare-osrm.sh       # télécharge Madagascar (Geofabrik) et prépare OSRM (une fois)
docker compose up -d --build
```
L'application écoute sur le port 8000. Placez-la derrière un proxy HTTPS (Caddy, Nginx) et mettez `DELIVERYOPT_SECURE_COOKIE=1`.

> **Non testé.** Docker n'était pas disponible dans l'environnement de développement : `Dockerfile`, `docker-compose.yml` et `scripts/prepare-osrm.sh` n'ont jamais été exécutés. Le client OSRM, lui, est testé contre un faux serveur OSRM (format de réponse documenté), pas contre un vrai. Premier contrôle à faire : après démarrage, l'en-tête ne doit plus afficher « MODE ESTIMATION » ; sinon `DELIVERYOPT_OSRM_URL` n'est pas pris en compte.

## 3. Variables d'environnement
| Variable | Rôle | Défaut |
|---|---|---|
| `DELIVERYOPT_DB` | fichier SQLite | `data/app.db` |
| `DELIVERYOPT_HOST`, `DELIVERYOPT_PORT` | adresse d'écoute | `127.0.0.1`, `8000` |
| `DELIVERYOPT_OSRM_URL` | service OSRM ; absent = mode estimation | – |
| `DELIVERYOPT_NOMINATIM_URL` | géocodage ; absent = saisie des coordonnées ou clic sur la carte | – |
| `DELIVERYOPT_USER_AGENT` | obligatoire pour le Nominatim public (nom + contact) | – |
| `DELIVERYOPT_ADMIN_USER`, `DELIVERYOPT_ADMIN_PASSWORD` | administrateur créé si la base est vide | – |
| `DELIVERYOPT_SECURE_COOKIE` | `1` derrière HTTPS | `0` |

Le Nominatim public limite à 1 requête par seconde et interdit l'usage intensif : pour un usage quotidien, hébergez votre propre instance.

## 4. Carte (Leaflet)
L'interface charge Leaflet depuis `/static/vendor/` puis, à défaut, depuis unpkg.com. Pour fonctionner sans dépendre d'un site externe : `python run.py vendor-leaflet` (nécessite Internet, à faire une fois). Sans Leaflet, un plan schématique SVG est affiché ; l'application reste utilisable (testé).

## 5. Sauvegarde
Toutes les données (utilisateurs, paramètres, historique des plans) sont dans un seul fichier SQLite : copiez-le (arrêt du service ou `sqlite3 app.db ".backup copie.db"`). Avec Docker, il est dans le volume `app-data`.

## 6. Sécurité : ce qui est en place, ce qui reste à faire
En place : mots de passe hachés (scrypt), jetons de session stockés hachés, cookie `HttpOnly` + `SameSite=Lax`, contrôle de l'en-tête `Origin`, blocage de l'identifiant 60 s après 5 échecs, en-têtes CSP, aucune injection HTML possible depuis les données (affichage en texte), neutralisation des formules dans l'export CSV, aucun secret dans le dépôt.
À faire par l'exploitant : HTTPS, pare-feu (n'exposer que le proxy), sauvegardes, rotation du mot de passe administrateur. Aucun audit de sécurité externe n'a été réalisé.
