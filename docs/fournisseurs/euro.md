# EuroTyre Wholesale (EURO)

Grossiste néerlandais. Fournisseur fictif du projet de démonstration.

## Accès

- Protocole : fichier déposé dans un dossier
- Fichiers attendus : `catalogue_*.xml`
- Dossier local : `data/generated/euro`
- Contact technique : edi@eurotyre.example (fictif)
- Envoi habituel : un catalogue complet par jour, déposé dans le dossier d'échange

## Lecture du fichier

- format XML, enregistrements dans `product`
- Fichier de mapping : `config/suppliers/euro.toml`

## Correspondance des colonnes

| Champ | Colonne du fournisseur | Transformation |
|---|---|---|
| EAN | `ean` |  |
| Marque | `brand` |  |
| Modèle | `model` |  |
| Largeur | `width` |  |
| Série | `profile` |  |
| Jante | `rim` |  |
| Indice de charge | `loadIndex` |  |
| Indice de vitesse | `speedRating` |  |
| Saison | `season` |  |
| Type de véhicule | `vehicle` |  |
| Bruit (dB) | `noise` |  |
| Classe énergie | `fuelClass` |  |
| Adhérence sol mouillé | `wetGrip` |  |
| Prix d'achat HT | `priceCents` | cents_to_eur |
| Stock | `stock` |  |
| Délai (jours) | `leadTimeDays` |  |

## Valeurs de « Saison »

| Fournisseur | Valeur retenue |
|---|---|
| `S` | summer |
| `W` | winter |
| `A` | all_season |

## Valeurs de « Type de véhicule »

| Fournisseur | Valeur retenue |
|---|---|
| `PCR` | car |
| `SUV` | suv |
| `LCV` | van |

## Particularités connues

- Fichier XML, balises en anglais, un élément `<product>` par pneu.
- Prix en centimes (`<priceCents>2848</priceCents>` = 28,48 EUR) : transformation `cents_to_eur`.
- Dimension en trois balises séparées (`width`, `profile`, `rim`).
- Saison codée sur une lettre : `S` été, `W` hiver, `A` toutes saisons. Véhicule : `PCR`, `SUV`, `LCV`.
- Un fichier XML coupé ne peut pas être lu du tout : l'import est en échec (`ParseError`), rien n'est chargé.

## Historique

- 2026-11-18 : intégration du fournisseur (fichier de mapping écrit à la main).
