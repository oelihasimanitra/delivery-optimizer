# Limites connues (à lire avant tout usage réel)

## Non vérifié contre le monde réel
- **OSRM, Nominatim, Leaflet, Docker** : jamais essayés (pas d'Internet). Les clients sont testés contre de faux serveurs reproduisant le format documenté ; un écart de format réel reste possible.
- **Profil moto** : OSRM n'en fournit pas ; le profil voiture sert. Distances routières correctes, **durées approximatives** (sens interdits, vitesse, embouteillages d'Antananarivo non calibrés). Réglage : coefficient de durée dans les paramètres.
- **Couverture des adresses** : la qualité du géocodage OpenStreetMap à Antananarivo n'est pas mesurée ; le point proposé doit toujours être vérifié par l'opérateur.

## Installation Windows en un clic (version 0.3.0)
- **Essai du 27/11/2026** (Windows 11, 7,9 Go de RAM, ZIP extrait dans un dossier à accent et espace) : réussi de bout en bout sur **ce seul PC** (lanceur, Python embeddable, OSRM, plan de démonstration dans Chrome avec distances routières réelles).
- **Jamais essayé sur un Windows vierge** : ce PC a déjà Python et les DLL Visual C++ ; l'absence de ces éléments chez un utilisateur n'a donc pas été testée (le ZIP embarque les DLL et un Python local, mais cela n'est pas prouvé sur une machine nue).
- **Zone couverte limitée** : région d'Antananarivo seulement (≈ 65 × 65 km). Madagascar entier échoue sur 7,9 Go de RAM (`osrm-extract` : « bad allocation » après ≈ 6 min 30). Hors zone, les distances sont fausses et l'alerte `POINT_LOIN_DE_ROUTE` est le seul garde-fou ; le dépôt peut encore être réglé n'importe où à Madagascar.
- **Carte figée** à la date du build (`osrm-data/MAP-INFO.txt`) : routes nouvelles absentes, renouvelée seulement avec une nouvelle release. Elle provient d'Overpass (API publique, parfois saturée) et n'a pas été comparée à une carte Geofabrik complète.
- **Dossier avec accent** (ex. « Téléchargements » en français) : OSRM rejette un chemin absolu accentué ; le lanceur utilise des chemins relatifs. Vérifié dans un dossier accentué.
- **Profil voiture** : durées approximatives pour une moto (voir plus haut).
- **Windows SmartScreen / antivirus** : ZIP, `.bat` et `.exe` non signés ; un avertissement est attendu, un faux positif antivirus possible sur les binaires OSRM (conditionnement Node d'OSRM, pas une distribution officielle des outils).
- **Pas de mise à jour automatique** : voir `docs/deployment.md`.

## Paramètres provisoires
Nombre maximum de livreurs (10), coût fixe par livreur (0), journée 08:00–17:00, remise 5 min, et tous les poids de l'objectif (attente, écart d'heure souhaitée, équilibre…) sont des valeurs par défaut raisonnables **non validées** (questions E de `open-questions.md`). Conséquence observée : avec ces poids, deux livreurs peuvent être jugés moins bons qu'un seul (attentes, équilibre) ; le texte « Pourquoi ce nombre de livreurs ? » donne les chiffres.

## Algorithmes
- Optimiseur heuristique (insertion + recherche locale, Python pur) : bon marché et explicable, **sans garantie d'optimalité**. Mesuré : meilleur que les trois méthodes simples sur les jeux synthétiques du benchmark, pas comparé à un solveur exact ou à OR-Tools. Limite fixée à 500 colis par plan ; le temps de calcul (8 s par défaut) borne la qualité sur les gros volumes.
- Détection des adresses éloignées : heuristique gloutonne déterministe, pas prouvée optimale.
- Explications : construites après coup par comparaison chiffrée avec des alternatives simples (insertion ailleurs, échange avec l'arrêt suivant). Elles décrivent le plan retenu ; elles ne reconstituent pas le raisonnement interne de la recherche.
- Dépendance « B après A » : même livreur, A avant B. Pas de synchronisation entre livreurs.

## Produit
- Pas de vue mobile pour les livreurs, pas de suivi en temps réel, pas de replanification en cours de journée, pas de multi-dépôt.
- Plan sur une seule journée ; l'historique n'est pas modifiable (on recalcule un nouveau plan).
- SQLite : adapté à quelques utilisateurs simultanés, pas à une forte charge.

## Qualité du processus
- Aucun audit indépendant humain ou par un autre agent n'a été fait ; un vérificateur de plan indépendant du moteur est en revanche exécuté sur chaque plan.
- Aucun audit de sécurité externe.
