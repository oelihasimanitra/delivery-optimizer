# Guide d'utilisation

## Se connecter
Ouvrez l'adresse de l'application, saisissez identifiant et mot de passe. Le compte administrateur crée les autres comptes (onglet **Compte**) et seul lui modifie les **Paramètres**.

## Préparer les colis (onglet Colis)
- **Charger la démonstration** : 18 colis fictifs pour essayer.
- **Importer un fichier CSV** : colonnes obligatoires `id_colis` et `adresse`; facultatives : `latitude`, `longitude`, `heure_min`, `heure_max`, `heure_souhaitee` (HH:MM), `priorite` (normale, elevee, urgente), `duree_remise_min`, `apres_colis`, `note`. Séparateur `;` ou `,`.
- **Coordonnées** : saisies à la main, trouvées par **Localiser** (si le géocodage est configuré, vérifiez le point proposé) ou posées avec **Placer sur la carte** puis un clic.
- **Après colis** : indiquez l'identifiant du colis qui doit être livré avant. Les deux colis seront chez le même livreur, dans cet ordre.
- Plusieurs colis aux mêmes coordonnées = un seul arrêt, un seul tarif.

## Lancer l'optimisation
Le bouton calcule le nombre de livreurs, les groupes et l'ordre des arrêts (quelques secondes). Le résultat s'ouvre dans l'onglet **Résultats** et est enregistré dans l'**Historique**.

## Lire le résultat
- Bandeau vert : le vérificateur indépendant a recalculé couverture, capacité, horaires, ordre, tarifs : tout concorde. Bandeau rouge : incohérence détectée, ne pas utiliser le plan.
- Bandeau « Distances estimées » : mode estimation, **ne pas facturer**.
- Chaque livreur : arrêts dans l'ordre, heure de remise, attente, trajet, prix. Cliquez sur un arrêt : *pourquoi ce livreur*, *pourquoi cet ordre*, *pourquoi ce prix*, avec les chiffres.
- **Adresse éloignée** : marquée « éloignée », tarif = km facturables × 1 000 Ar + 1 000 Ar d'attente.
- **Colis non attribués** : raison et pistes (autre horaire, autre priorité, plus de livreurs…).
- **Colis écartés** : adresse introuvable, hors Madagascar, route inaccessible, heure limite impossible, donnée invalide : à corriger puis relancer.
- **Exporter en CSV** : ouvrable dans Excel (séparateur `;`).

## Paramètres (administrateur)
Tarifs, seuils (3 km de moyenne, 5 km par trajet), nombre maximum de livreurs, capacité (20), cible (7), heures de journée, et poids de l'objectif. **Les valeurs de planification et de poids sont provisoires** : à régler avec vos vraies tournées (voir `docs/open-questions.md`).
