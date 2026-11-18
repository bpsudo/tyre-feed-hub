# Runbook : que faire quand un fournisseur est rouge

Ce document sert au support. Pour chaque anomalie critique : ce qu'elle veut dire, comment vérifier, quoi
faire. Les seuils sont dans `config/thresholds.toml`.

Point de départ dans tous les cas : le tableau de bord. Cliquer sur l'heure du dernier import pour voir son
détail, ou sur le chiffre rouge de la colonne « Critiques » pour la liste des anomalies critiques.

Commandes utiles :

```
feedhub import --supplier NORD     # relancer l'import d'un fournisseur
feedhub report 5 --supplier NORD   # taux de rejet de chaque import
feedhub report 7 --supplier NORD   # stock total import par import
feedhub report 8 --supplier NORD   # EAN disparus depuis l'import précédent
feedhub report 9                   # fournisseurs sans données récentes
```

## Import en échec (statut « Échec »)

Ce n'est pas une anomalie mais un import qui n'a rien chargé. Le message d'erreur est sur le tableau de bord
et dans le détail de l'import.

| Message | Cause probable | Action |
|---|---|---|
| `folder not found` | dossier local absent ou mal écrit dans le `.toml` | vérifier `local_dir` dans `config/suppliers/<code>.toml` |
| `ConnectionError`, `timed out` | serveur SFTP ou API injoignable | réessayer plus tard ; si ça dure, contacter le fournisseur (contact dans sa fiche) |
| `AuthenticationException`, `401` | mot de passe ou clé API faux ou expiré | vérifier les variables dans `.env` ; demander de nouveaux accès au fournisseur |
| `RateLimitError` | l'API refuse encore après 3 nouvelles tentatives | relancer plus tard ; si fréquent, demander au fournisseur sa limite réelle |
| `UnicodeDecodeError` | le fournisseur a changé d'encodage | ouvrir le fichier, trouver l'encodage, corriger `encoding` dans le `.toml` |
| `ParseError` (XML), `JSONDecodeError` | fichier coupé ou mal formé | voir la taille du fichier ; demander un nouvel envoi |
| `no valid row` | toutes les lignes sont rejetées | regarder les rejets du détail : souvent une colonne renommée par le fournisseur |

Un fichier en échec est retenté automatiquement au prochain `feedhub import`. Les offres de la veille sont
gardées : la recherche continue de les montrer.

## REJECT_RATE_HIGH : trop de lignes rejetées

Plus de 5 % des lignes du fichier ont été rejetées.

Diagnostiquer :
- détail de l'import : la liste des rejets montre la règle, le message et la ligne reçue ;
- regarder si une seule règle domine. Exemples :
  - beaucoup de `PRICE_INVALID` → le format des prix a changé (virgule, centimes) ;
  - beaucoup de `MISSING_FIELD` → une colonne a été renommée ou supprimée ;
  - des rejets variés en petit nombre → saisie de mauvaise qualité chez le fournisseur.

Agir :
- format changé : corriger le `.toml` (colonne, transformation), puis relancer l'import ;
- données fausses : envoyer au fournisseur la liste des EAN rejetés avec la raison (page Anomalies
  filtrée sur le fournisseur et la date, ou détail de l'import).

Les lignes valides du fichier sont chargées malgré tout.

## ROW_COUNT_DROP : fichier probablement coupé

Le fichier a au moins 30 % de lignes en moins que l'import précédent.

Ce que l'outil a déjà fait : il a chargé les lignes valides, mais il n'a pas supprimé les offres absentes du
fichier. Les prix de la veille restent visibles pour ces références.

Diagnostiquer :
- taille du fichier reçu par rapport aux jours précédents ;
- dernière ligne du fichier : une ligne coupée au milieu confirme un transfert interrompu (on voit souvent
  aussi un rejet `MISSING_FIELD` sur la dernière ligne) ;
- `feedhub report 8 --supplier NORD` : liste des références disparues.

Agir :
- demander au fournisseur de renvoyer le fichier du jour ;
- une fois le bon fichier déposé sous un autre nom (par exemple `stock_20261118_bis.csv`), relancer
  `feedhub import --supplier NORD` ;
- si le fournisseur confirme qu'il a vraiment retiré ces références, rien à faire : le prochain fichier
  complet les supprimera.

## STOCK_DROP : stock total divisé par deux

Le stock total du fournisseur a baissé de plus de 50 % depuis l'import précédent.

Diagnostiquer :
- souvent en même temps que `ROW_COUNT_DROP` : c'est alors le même problème (fichier coupé) ;
- seul : `feedhub report 7 --supplier <code>` montre l'évolution import par import ;
  regarder si beaucoup de stocks sont passés à 0 d'un coup.

Agir :
- stocks à 0 en masse sans raison commerciale : problème d'export chez le fournisseur, le contacter ;
- en attendant, prévenir les commerciaux que la disponibilité de ce fournisseur est douteuse.

## FEED_STALE : pas de données récentes

Le dernier import réussi a des données de plus de 24 h (date lue dans le nom du fichier).
Sur la recherche pneu, les offres de ce fournisseur portent la mention « données du jj/mm » en orange.

Diagnostiquer :
- tableau de bord : y a-t-il des imports en échec récents ? Si oui, voir « Import en échec » ;
- aucun import du tout : le fichier n'est pas arrivé. Vérifier le dossier ou le serveur SFTP, ou la liste
  des exports de l'API ;
- vérifier que `feedhub import` tourne bien (tâche planifiée).

Agir :
- contacter le fournisseur avec la date des dernières données reçues ;
- l'anomalie n'est créée qu'une fois pour un même retard ; elle cesse de compter sur le tableau de bord dès
  que des données récentes arrivent.

## Anomalies « warning » : à surveiller, pas d'urgence

| Règle | Ce qu'il faut regarder |
|---|---|
| `PRICE_JUMP` | Prix d'un EAN changé de plus de 30 %. Un ou deux : normal. Des dizaines d'un coup : erreur de prix chez le fournisseur ou changement de devise, de TVA, d'unité. |
| `PRICE_OUTLIER` | Prix à plus de 40 % de la médiane des fournisseurs. Vérifier avant de vendre : erreur de saisie ou vraie promotion. |
| `DUPLICATE_IN_FILE` | Même EAN deux fois : la dernière ligne est gardée. À signaler au fournisseur s'il y en a beaucoup. |
| Rejets de lignes | `EAN_INVALID`, `SIZE_UNPARSABLE`, `PRICE_INVALID`, `STOCK_NEGATIVE`, `MISSING_FIELD`, `VALUE_INVALID` : la ligne n'est pas chargée. À regrouper et envoyer au fournisseur. |
