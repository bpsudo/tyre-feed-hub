# Ajouter un fournisseur

Ajouter un fournisseur, c'est écrire un fichier de mapping (`config/suppliers/<code>.toml`), pas du code.
Il y a deux façons de le faire.

## Avec la page « Nouveau fournisseur »

C'est la voie normale pour un fichier CSV, XML ou JSON.

1. Récupérer un fichier d'exemple du fournisseur, de quelques dizaines à quelques centaines de lignes
   (500 Ko au plus).
2. Ouvrir l'écran (`feedhub serve`), menu « Nouveau fournisseur ».
3. Donner un code (2 à 10 lettres majuscules ou chiffres, par exemple `SUD`), le nom, et le fichier.
4. Vérifier ce que la page a reconnu : format, encodage, séparateur, fichiers attendus.
5. Vérifier la correspondance des colonnes. Chaque champ a un pourcentage de confiance. En dessous de 80 %,
   regarder les exemples de valeurs de la colonne choisie. Corriger avec les listes si besoin, puis
   « Vérifier avec ces colonnes ».
6. Regarder l'import à blanc : le taux de rejet doit être proche de 0 sur un fichier d'exemple propre. Les
   premières erreurs indiquent souvent une transformation oubliée (virgule décimale, centimes).
7. Si une valeur de saison ou de type de véhicule n'est pas reconnue, la page le signale. Il faudra l'ajouter
   à la main dans le fichier (étape suivante).
8. « Enregistrer le fournisseur » écrit :
   - `config/suppliers/<code>.toml` ;
   - `docs/fournisseurs/<code>.md`, la fiche, avec des lignes « à compléter ».
9. Déposer les fichiers du fournisseur dans `data/generated/<code>` et lancer
   `feedhub import --supplier <CODE>`.
10. Compléter la fiche (contact, heure d'envoi, particularités) et commiter les deux fichiers.

Exemple complet avec le fichier `data/samples/sud/export_20260115.csv` : les 5 colonnes sont trouvées,
dont la dimension cachée dans la désignation (`PNEU KESTRA AERO 3 205/55R16 91V`).

## À la main

Pour un accès SFTP ou API, ou un format que la page ne sait pas lire, partir d'un fichier existant :

| Cas | Modèle |
|---|---|
| Fichier CSV sur un serveur SFTP | `config/suppliers/nord.toml` |
| Fichier XML déposé dans un dossier | `config/suppliers/euro.toml` |
| API REST avec clé et pagination | `config/suppliers/reif.toml` |

Le fichier contient :

```toml
code = "SUD"                    # en majuscules, unique
name = "Pneus Sud Import"
protocol = "file"               # file, sftp ou rest_api
format = "csv"                  # csv, xml ou json

[source]                        # où trouver les fichiers
local_dir = "data/generated/sud"
file_pattern = "export_*.csv"   # la date du nom de fichier sert à détecter un retard

[file]                          # comment lire le fichier
encoding = "cp1252"
delimiter = ","                 # CSV ; pour XML et JSON : records = "chemin"

[columns]                       # champ normalisé = colonne du fournisseur
ean = "CodeBarre"
brand = "Fabricant"
size = "Désignation"
price_eur = "PU_HT"
stock = "Qté"

[transforms]                    # seulement si besoin
size = "extract_size_from_text"

[season_map]                    # valeur du fournisseur = summer, winter ou all_season
"Été" = "summer"
```

Champs obligatoires : `ean`, `brand`, `price_eur`, `stock`, et la dimension (`size`, ou `width`,
`aspect_ratio` et `rim_diameter`).

Transformations disponibles :

| Nom | Effet |
|---|---|
| `decimal_comma` | `59,90` → `59.90` |
| `cents_to_eur` | `5990` → `59.90` |
| `size_combined` | une colonne `205/55R16 91V` → largeur, série, jante, indices |
| `extract_size_from_text` | trouve la dimension au milieu d'un texte |

Accès à un serveur : jamais de mot de passe ni de clé dans le `.toml`, qui est versionné. Le fichier donne
seulement le nom de la variable d'environnement (`password_env = "SUD_SFTP_PASSWORD"`), et la valeur va dans
`.env` (non versionné) ou dans l'environnement du serveur.

Vérifier ensuite :

```
feedhub import --supplier SUD
feedhub report 5 --supplier SUD    # taux de rejet
```

Puis écrire la fiche `docs/fournisseurs/<code>.md` en suivant une fiche existante.

## Quand faut-il écrire du code ?

Seulement pour un nouveau protocole (FTP, e-mail...) ou un format vraiment différent : valeurs dans des
attributs XML, objets imbriqués en JSON, fichier Excel. Il faut alors un connecteur dans
`src/feedhub/connectors/` ou un lecteur dans `src/feedhub/readers.py`. Le reste (contrôles, chargement,
écran) ne change pas.
