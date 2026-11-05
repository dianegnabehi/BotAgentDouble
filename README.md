# BotAgentDouble

Système automatisé de prospection d'emploi, d'alternance, stage Tech, IA et Data en approche directe : identification d'entreprises cibles, enrichissement des décideurs, génération de pitchs personnalisés validés sur Telegram et suivi automatique des relances. L'orchestration du projet est conteneurisée avec **Docker** et déployée en production sur une machine virtuelle **Google Cloud Platform (GCP)**. Utilise le concept Human in the loop pour valider avant envoi.

---

## Aperçu

Le projet s'articule autour de quatre composants reliés à une base PostgreSQL (Supabase) et d'une infrastructure cloud hébergée sur une VM GCP :

- **sourcing.py** : identifie des entreprises Tech qui recrutent en Île-de-France (`Paris`, `La Défense`, `Vincennes`, `Montreuil (93)`) via l'API Groq, valide la sortie JSON avec Pydantic et insère les nouvelles cibles au statut `À enrichir`.

- **n8n_telegram_workflow.json** : workflow n8n exécuté dans un conteneur **Docker** sur une **VM Google Cloud Platform (Compute Engine)** derrière un reverse-proxy HTTPS. Il orchestre l'enrichissement hybride toutes les 2 heures (vérification DNS MX, API Hunter.io et recherche web LinkedIn / scraping des pages publiques), intercepte les actions Telegram, envoie les emails via Gmail OAuth2 et assure les relances automatiques à J+7.

- **agent.py** : sélectionne les contacts qualifiés (`Enrichi`), génère un email d'approche directe en français (90 à 115 mots) et envoie une carte interactive de validation sur Telegram :

  | Action Telegram | Statut appliqué | Effet sur la candidature |
  |---|---|---|
  | `✅ Valider & Envoyer Email` | `Envoyé` | Envoi immédiat via Gmail et activation du suivi J+7 |
  | `❌ Refuser` | `Refus` | Écarte la candidature |
  | `✏️ Éditer (texte)` | `En cours d'édition` | Remplace le pitch par le texte saisi sur Telegram |
  | `🤖 Éditer via IA` | `En cours d'édition` | Réécrit le pitch via Groq selon la consigne envoyée |

- **dashboard.py** : interface Streamlit permettant de suivre les indicateurs clés, les échéances de relance (maximum 2 relances à J+7 avant clôture automatique en `Refus`) et de basculer un contact au statut `Entretien` pour stopper les relances.

---

## Prérequis

- Python 3.10 ou supérieur
- Un projet Supabase (PostgreSQL) initialisé avec `schema.sql`
- Une clé API Groq et un bot Telegram configuré
- Une instance n8n déployée sous Docker (VM GCP) pour l'exécution continue des webhooks et des relances

---

## Installation

```bash
git clone git@github.com:dianegnabehi/BotAgentDouble.git
cd BotAgentDouble
pip3 install -r requirements.txt
cp .env.example .env
```

Renseigner les variables d'environnement dans le fichier `.env` (`SUPABASE_URL`, `SUPABASE_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`).

---

## Utilisation

Lancer un sourcing d'entreprises cibles :

```bash
python3 sourcing.py --count 10 --domaine "IA, Data Science, Backend Python"
```

Générer les pitchs des contacts enrichis et envoyer les cartes de validation sur Telegram :

```bash
python3 agent.py --limit 5
```

Lancer le tableau de bord de suivi Streamlit :

```bash
python3 -m streamlit run dashboard.py
```

---

## Structure du projet

```
.
├── sourcing.py                 # Sourcing structuré d'entreprises via Groq et Pydantic
├── agent.py                    # Génération des pitchs et envoi des cartes sur Telegram
├── dashboard.py                # Tableau de bord Streamlit de pilotage des candidatures
├── n8n_telegram_workflow.json  # Workflow n8n (enrichissement, webhook Telegram, relances J+7)
├── schema.sql                  # Schéma PostgreSQL Supabase (table et vue de pilotage)
├── requirements.txt            # Dépendances Python
├── .env.example                # Modèle des variables d'environnement
├── .gitignore                  # Fichiers exclus du dépôt
└── README.md                   # Documentation du projet
```

---

## Fonctions principales

| Fichier | Fonction | Rôle |
|---|---|---|
| sourcing.py | `rechercher_entreprises_tech(domaine, nb_entreprises)` | Interroge Groq en JSON structuré et valide les entreprises avec Pydantic. |
| sourcing.py | `sauvegarder_dans_supabase(supabase, entreprises)` | Insère les nouvelles entreprises au statut `À enrichir` sans doublon. |
| sourcing.py | `run_sourcing(domaine, count)` | Point d'entrée du pipeline de sourcing. |
| agent.py | `generate_pitch(prospect)` | Rédige un email d'approche personnalisé et concis en français via Groq. |
| agent.py | `send_pitch_to_telegram(prospect, pitch_text)` | Envoie la carte de validation avec clavier inline sur Telegram. |
| agent.py | `run_batch(limit)` | Traite un lot de prospects `Enrichi` et met à jour leur statut. |
| dashboard.py | `charger_prospects(supabase)` | Récupère l'ensemble des candidatures triées par date de mise à jour. |
| dashboard.py | `calculer_jours_sans_reponse(row)` | Calcule le délai écoulé depuis le dernier envoi ou la dernière relance. |
| dashboard.py | `main()` | Affiche les KPIs, la validation des pitchs et le suivi des relances J+7. |

---

## Auteur

Diane Gnabehi - projet recherche prospects automatisées

---

## Licence

Ce projet est distribué sous licence MIT.
