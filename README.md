# Mettre à jour la Base Carbone ADEME (1 fois par an)

Le calculateur lit ses facteurs d'émission dans `data/ademe.js`, fichier **généré** par `scripts/update_ademe.py`.
Les masses volumiques des boissons sont dans `data/densites_boissons.js` (fichier **à la main**, jamais modifié par le script).

## Procédure annuelle (≈ 20 min)

1. **Télécharger le CSV** de la Base Carbone sur data.gouv.fr :
   <https://www.data.gouv.fr/fr/datasets/base-carbone-r-2/> → ressource « Base Carbone » au format CSV.
   Noter le numéro de version affiché (ex. `V23.7`).
2. **Lancer un essai à blanc** (n'écrit rien d'autre que le rapport) :
   ```
   python scripts/update_ademe.py ~/Downloads/base-carbone.csv --version "V23.7" --dry-run
   ```
3. **Lire `scripts/rapport_mise_a_jour.md`**, dans cet ordre :
   - *Boissons sans masse volumique* → compléter `data/densites_boissons.js` (ou `BOISSONS_RESTANT_EN_KG` si c'est une poudre/ingrédient sec) ;
   - *Masses volumiques orphelines* → boisson renommée par l'ADEME : renommer la clé dans `densites_boissons.js` ;
   - *Variations ≥ 20 %* → vérifier que les gros changements sont plausibles (changement de méthode ADEME ?) ;
   - *Lignes rejetées* → unité inconnue = l'ajouter dans `scripts/rubriques.json` (`unites_ademe_vers_saisie`) ; « rubrique impossible à déterminer » = ajouter une règle ;
   - *Supprimés / Ajoutés* → survol.
4. **Lancer pour de vrai** (sans `--dry-run`) : l'ancien fichier est sauvegardé dans `data/archives/`.
5. **Tester** : ouvrir `index.html` (via GitHub Pages ou un serveur local), faire une recherche dans chaque rubrique, ajouter un poste, exporter en Excel. La version ADEME apparaît dans « À propos » et dans l'export.
6. **Publier** : envoyer `data/ademe.js` (+ `densites_boissons.js` si modifié) sur GitHub.

## Garde-fous

- Le script refuse d'écrire si plus de 15 % des facteurs actuels disparaissent (`--max-suppressions-pct` pour forcer).
- Il s'arrête avec un message clair si une colonne du CSV a changé de nom (`colonnes_csv` dans `rubriques.json`).
- Rien n'est jamais deviné : ce qu'il ne sait pas classer est listé dans le rapport.

## ⚠️ Première utilisation

Le script a été écrit **sans pouvoir télécharger le vrai CSV** (accès bloqué depuis l'environnement de développement) ; il a été testé sur un CSV synthétique reconstruit à partir de la base actuelle. La première exécution réelle sert donc aussi de calibrage :
- la base actuellement intégrée est la dernière version ADEME (V23.6) : si vous relancez le script sur ce même millésime, le rapport doit montrer **très peu** de différences. Beaucoup d'écarts = le script classe ou nomme autrement que la conversion d'origine → ajustez `rubriques.json` ;
- si les noms de colonnes, le niveau de catégorie retiré (`categorie_niveaux_a_retirer`) ou les statuts acceptés ne correspondent pas, ajustez `scripts/rubriques.json` et relancez en `--dry-run` jusqu'à ce que le rapport soit cohérent.

## Fichiers

| Fichier | Rôle | Modifié par |
|---|---|---|
| `data/ademe.js` | facteurs d'émission + version | le script |
| `data/densites_boissons.js` | kg → L des boissons | vous |
| `scripts/rubriques.json` | colonnes du CSV, unités, règles de classement par rubrique | vous (si besoin) |
| `scripts/rapport_mise_a_jour.md` | rapport de la dernière exécution | le script |
