# Pneus Nord Distribution (NORD)

Grossiste français. Fournisseur fictif du projet de démonstration.

## Accès

- Protocole : SFTP
- Fichiers attendus : `stock_*.csv`
- Dossier local : `data/generated/nord`
- Variable d'environnement : `NORD_SFTP_HOST`
- Variable d'environnement : `NORD_SFTP_USER`
- Variable d'environnement : `NORD_SFTP_PASSWORD`
- Serveur de test : `docker compose up -d` (voir `docker-compose.yml`). Sans `NORD_SFTP_HOST`, les fichiers sont lus dans le dossier local.
- Contact technique : service informatique, sftp@pneus-nord.example (fictif)
- Envoi habituel : un fichier par jour vers 6 h, heure de Paris

## Lecture du fichier

- format CSV, encodage latin-1, séparateur `;`
- Fichier de mapping : `config/suppliers/nord.toml`

## Correspondance des colonnes

| Champ | Colonne du fournisseur | Transformation |
|---|---|---|
| EAN | `EAN` |  |
| Marque | `Marque` |  |
| Modèle | `Modèle` |  |
| Dimension complète | `Dimension` | size_combined |
| Saison | `Saison` |  |
| Type de véhicule | `Catégorie` |  |
| Bruit (dB) | `Bruit (dB)` |  |
| Classe énergie | `Classe énergie` |  |
| Adhérence sol mouillé | `Adhérence sol mouillé` |  |
| Prix d'achat HT | `Prix HT` | decimal_comma |
| Stock | `Stock` |  |
| Délai (jours) | `Délai (jours)` |  |

## Valeurs de « Saison »

| Fournisseur | Valeur retenue |
|---|---|
| `Été` | summer |
| `Hiver` | winter |
| `4 saisons` | all_season |

## Valeurs de « Type de véhicule »

| Fournisseur | Valeur retenue |
|---|---|
| `Tourisme` | car |
| `SUV` | suv |
| `Utilitaire` | van |

## Particularités connues

- Fichier CSV exporté depuis un ERP français : séparateur `;`, virgule décimale (`59,90`), encodage latin-1, fins de ligne Windows.
- En-têtes en français, avec accents (`Modèle`, `Délai (jours)`).
- La dimension est dans une seule colonne, avec les indices : `205/55R16 91V`.
- Il arrive qu'une ligne soit exportée en UTF-8 dans le fichier latin-1 : `Été` devient `Ã‰tÃ©`. La ligne est rejetée en `VALUE_INVALID` ; signaler l'EAN au fournisseur.
- Un fichier coupé pendant le transfert se voit à `ROW_COUNT_DROP` : demander un nouvel envoi (voir le runbook).

## Historique

- 2026-11-18 : intégration du fournisseur (fichier de mapping écrit à la main).
