#!/usr/bin/env bash
# Prépare les données routières OSRM pour Madagascar (à exécuter une fois, puis à chaque mise à jour des cartes).
# Nécessite Docker et Internet. Durée : quelques minutes, ~1 Go de disque.
# ATTENTION : OSRM ne fournit pas de profil moto ; le profil « car » est utilisé. Les durées sont donc des
# approximations (les distances, elles, suivent le réseau routier). Voir docs/limitations.md.
set -euo pipefail
mkdir -p osrm-data
cd osrm-data
[ -f madagascar-latest.osm.pbf ] || curl -fL -o madagascar-latest.osm.pbf https://download.geofabrik.de/africa/madagascar-latest.osm.pbf
IMG=ghcr.io/project-osrm/osrm-backend:latest
docker run --rm -v "$PWD:/data" "$IMG" osrm-extract -p /opt/car.lua /data/madagascar-latest.osm.pbf
docker run --rm -v "$PWD:/data" "$IMG" osrm-partition /data/madagascar-latest.osrm
docker run --rm -v "$PWD:/data" "$IMG" osrm-customize /data/madagascar-latest.osrm
echo "Terminé. Lancez : docker compose up -d --build"
