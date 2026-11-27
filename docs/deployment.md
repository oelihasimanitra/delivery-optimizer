# Déploiement

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
