# Règles métier (validées le 23/11/2026)

Sources : cahier des charges V2, conversation d'origine, réponses de l'utilisateur.
En cas de contradiction, la V2 et les réponses les plus récentes l'emportent.
Les valeurs chiffrées sont des paramètres de `Settings` (`src/deliveryopt/config.py`), pas des constantes.

## 1. Contexte
- Ville : Antananarivo. Véhicule : moto. Un dépôt fixe, point de départ de toutes les tournées.
- Retour au dépôt non obligatoire.
- 7 à 20 colis par livreur : 20 est un maximum strict, 7 est une cible (alerte en dessous, sauf si le nombre total de colis ne le permet pas).
- Le système calcule le nombre de livreurs (voir `open-questions.md`, point E).
- Planification sur une journée.
- Coût interne : 1 000 Ar par km parcouru (dépôt → premier arrêt inclus).

## 2. Définitions
- **Adresse** : unité d'arrêt et de facturation. Plusieurs colis à la même adresse = un seul arrêt, un seul tarif.
- **Tournée / groupe** : suite ordonnée d'arrêts pris en charge par un même livreur en une fois.
- **Distance moyenne** : somme des distances routières entre arrêts successifs / nombre de transitions. Le trajet dépôt → premier arrêt est exclu par défaut. Une tournée à un seul arrêt n'a pas de moyenne.
- **Adresse éloignée** : adresse dont la présence fait dépasser un seuil à la tournée :
  - la moyenne des trajets dépasse 3 km (définition de l'utilisateur) ;
  - ou un trajet dépasse 5 km (seuil par trajet, réglable, ajouté car la moyenne seule laisse passer un détour isolé dans une longue tournée).
- **Désignation** : tant que la moyenne dépasse 3 km, on retire l'arrêt dont le retrait raccourcit le plus la tournée. Les arrêts retirés sont les adresses éloignées, ceux qui restent forment le groupe. En cas d'égalité, on retire l'arrêt le plus tardif.
  - **Seuil par trajet (5 km)** : il ne retire un arrêt que s'il est *isolé*, c'est-à-dire si son retrait réduit le nombre de trajets au-dessus du seuil. Une tournée qui traverse plusieurs zones distinctes (nombreux trajets longs) n'est pas transformée en adresses éloignées : elle déclenche l'alerte `TOURNEE_MULTI_ZONES` (à séparer entre livreurs). Correction faite après avoir constaté qu'une règle plus simple marquait 18 adresses sur 20 comme éloignées.
- **Tournée dispersée** : plus de la moitié des arrêts sont éloignés → alerte.

## 3. Tarification
- Adresse du groupe : 4 000 Ar par adresse.
- Adresse éloignée : distance facturable (km) × 1 000 Ar + 1 000 Ar de frais d'attente fixes.
- Distance facturable : aller simple, distance routière depuis l'arrêt du groupe le plus proche.
- Arrondi : distance au 0,1 km (au plus proche), prix à l'Ar entier. Mode « supérieur » et pas d'un km disponibles.
- Exemples : 5 km → 6 000 Ar ; 10 km → 11 000 Ar. À 3 km, le prix éloigné vaut exactement le forfait.
- Le prix facturé n'influence pas l'optimisation : celle-ci minimise le coût interne.

## 4. Contraintes temporelles (par colis)
Types : libre ; avant une heure ; après une heure ; fenêtre ; heure souhaitée ; ordre imposé ; priorité (normale, élevée, urgente).
- Heure limite, heure minimale, fenêtre : contraintes dures.
- Heure souhaitée : contrainte souple, tolérance ±15 min puis pénalité croissante.
- Ordre imposé (B après A) : les deux colis chez le même livreur.
- Priorité : poids de pénalité en cas de colis non livré ou en retard. Elle ne réordonne pas les arrêts d'office.
- Le moteur tient compte du départ, du trajet, de l'arrivée, de l'attente, de la remise et du départ vers l'arrêt suivant.
- Attente du livreur : pénalisée par l'optimisation, non facturée au client (hors frais fixes des adresses éloignées).
- Contraintes incompatibles : conflit signalé avec alternatives (autre livreur, autre tournée, changement d'horaire, livraison séparée, changement de priorité).

## 5. Optimisation
1. Obligatoire : heures limites, fenêtres, ordre imposé, 20 colis max par livreur, chaque colis attribué ou signalé non attribué, jamais livré deux fois.
2. Objectif : minimiser le coût interne, les attentes, les détours.
3. Préférences : moyenne ≤ 3 km, 7 colis minimum, équilibre des charges, heure souhaitée, regroupement par quartier.

## 6. Alertes
Par tournée : `MOYENNE_SUPERIEURE_AU_SEUIL`, `CLIENT_ELOIGNE:<adresse>`, `TOURNEE_DISPERSEE`, `TOURNEE_MULTI_ZONES`, `SEUIL_NON_RESPECTE`, `ATTENTE_IMPORTANTE`. Sur le plan : `DISTANCES_ESTIMEES`, `SOUS_CIBLE`, `TOURNEES_DESEQUILIBREES`, `COLIS_NON_ATTRIBUES`, `COLIS_ECARTES`, `AUCUN_LIVREUR`, `AUCUNE_SOLUTION`. Colis écartés avec motif : `ID_MANQUANT`, `ID_DUPLIQUE`, `DONNEE_INVALIDE`, `ADRESSE_NON_LOCALISEE`, `COORDONNEES_HORS_MADAGASCAR`, `FENETRE_VIDE`, `ROUTE_INACCESSIBLE`, `CONTRAINTE_IMPOSSIBLE`, `DEPENDANCE_INCONNUE`, `DEPENDANCE_CIRCULAIRE`, `DEPENDANCE_REJETEE`.

## 7. Distances
Distances routières uniquement. Si une distance est absente ou une route inaccessible, le système lève une erreur : aucun repli silencieux sur le vol d'oiseau. Sans OSRM configuré, le **mode estimation** (vol d'oiseau × 1,4, 20 km/h) est explicite : alerte critique, bannière, plan marqué non facturable.
