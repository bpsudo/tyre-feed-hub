# Reifen Handel GmbH (REIF)

Grossiste allemand. Fournisseur fictif du projet de démonstration.

## Accès

- Protocole : API REST
- Fichiers attendus : `offers_*.json`
- Dossier local : `data/generated/reif`
- Variable d'environnement : `REIF_API_URL`
- Variable d'environnement : `REIF_API_KEY`
- API de test : `uvicorn mock_supplier_api.app:app --port 8001`, clé `demo-key`. Sans `REIF_API_URL`, les fichiers sont lus dans le dossier local.
- Contact technique : api-support@reifen-handel.example (fictif)
- Envoi habituel : un export par jour, disponible dans l'API dès 5 h

## Lecture du fichier

- format JSON, encodage utf-8, enregistrements dans `artikel`
- Fichier de mapping : `config/suppliers/reif.toml`

## Correspondance des colonnes

| Champ | Colonne du fournisseur | Transformation |
|---|---|---|
| EAN | `EAN` |  |
| Marque | `Hersteller` |  |
| Modèle | `Modell` |  |
| Largeur | `Breite` |  |
| Série | `Querschnitt` |  |
| Jante | `Felge` |  |
| Indice de charge | `Lastindex` |  |
| Indice de vitesse | `Geschwindigkeitsindex` |  |
| Saison | `Saison` |  |
| Type de véhicule | `Fahrzeugtyp` |  |
| Bruit (dB) | `Rollgeraeusch_dB` |  |
| Classe énergie | `Kraftstoffeffizienz` |  |
| Adhérence sol mouillé | `Nasshaftung` |  |
| Prix d'achat HT | `Preis` |  |
| Stock | `Bestand` |  |
| Délai (jours) | `Lieferzeit_Tage` |  |

## Valeurs de « Saison »

| Fournisseur | Valeur retenue |
|---|---|
| `Sommer` | summer |
| `Winter` | winter |
| `Ganzjahr` | all_season |

## Valeurs de « Type de véhicule »

| Fournisseur | Valeur retenue |
|---|---|
| `PKW` | car |
| `SUV` | suv |
| `Transporter` | van |

## Particularités connues

- API REST : `GET /api/v1/exports` donne la liste des jours, puis `GET /api/v1/exports/<date>/artikel?page=1&per_page=100` les pneus, page par page.
- La clé API passe dans l'en-tête `X-API-Key`. Une clé fausse donne HTTP 401 : import en échec.
- Limite de débit : l'API répond parfois HTTP 429 avec `Retry-After`. Le connecteur attend et réessaie 3 fois.
- Champs en allemand, nombres en vrais nombres JSON (pas de transformation).
- Tous les exports nouveaux sont téléchargés avant d'être importés : si un téléchargement échoue, aucun n'est importé et tout est repris au lancement suivant.

## Historique

- 2026-11-18 : intégration du fournisseur (fichier de mapping écrit à la main).
