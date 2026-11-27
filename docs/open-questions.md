# Questions ouvertes

## Bloquantes pour l'optimiseur
- **E. Nombre de livreurs.** Sans coût fixe par livreur, le système choisirait toujours le minimum permis par la capacité (20 colis). Il faut :
  - nombre maximum de livreurs disponibles ;
  - coût fixe d'un livreur par jour ;
  - durée maximale d'une journée et heure de départ du dépôt ;
  - durée de remise d'un colis (valeur par défaut).
  Valeurs provisoires utilisées en attendant (livreurs max 10, coût fixe 0, journée 08:00–17:00, remise 5 min), toutes modifiables dans l'onglet Paramètres.

## Bloquantes pour l'API et l'interface
- **G. Utilisateurs.** Livré : deux rôles (administrateur, opérateur). Reste à décider : les livreurs consultent-ils leur tournée sur téléphone (vue mobile non faite) ? Où est hébergé le serveur ?

## À confirmer plus tard
- Profil de vitesse moto : à calibrer sur de vraies livraisons (OSRM n'a pas de profil moto).
- Géocodage : couverture d'OpenStreetMap pour les adresses d'Antananarivo à mesurer sur des adresses réelles.
- Durée de remise : fixe ou selon le nombre de colis à l'adresse ?
