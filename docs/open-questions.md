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

## Distribution (release Windows)
- **Licence du dépôt public** : tranchée le 28/11/2026, MIT (fichier `LICENSE`, titulaire « Oely », 2026). Les données de la carte restent sous ODbL.
- **Signature de code** : sans certificat, Windows SmartScreen avertit à chaque nouvelle version. À décider : acheter un certificat ou garder la consigne « Exécuter quand même ».
- **Zone de la carte (décision prise : région d'Antananarivo).** La carte livrée couvre ≈ 65 × 65 km autour de la capitale (latitude -19,20 à -18,60 ; longitude 47,20 à 47,80), car Madagascar entier ne se prépare pas sur un PC de 8 Go. À confirmer avec les vraies adresses : cette zone suffit-elle (périphérie, aéroport d'Ivato inclus) ? Faut-il refuser un dépôt hors zone dans l'application ?
- **Cartes pour d'autres régions** : non prévues. Pour une autre zone, modifier `$MapBbox` dans `scripts/common.ps1` et reconstruire.
- **Mise à jour automatique** et automatisation de la publication par tag (GitHub Actions) : non faites.
