import os
import logging
import argparse
from typing import Literal
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from supabase import create_client, Client

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sourcing_alternance")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GROQ_API_KEY = (os.environ.get("GROQ_API_KEY") or os.environ.get("MISTRAL_API_KEY") or "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL") or "qwen/qwen3.8-27b"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
ZONES_CIBLES = ["Paris", "La Défense", "Vincennes", "Montreuil (93)"]


# --- Schémas Pydantic pour la sortie structurée ---
class EntrepriseCible(BaseModel):
    entreprise: str = Field(description="Nom officiel de l'entreprise")
    site_web: str = Field(description="URL du site web officiel (ex: https://exemple.com)")
    localisation: Literal["Paris", "La Défense", "Vincennes", "Montreuil (93)"] = Field(
        description="Zone géographique des bureaux parmi les 4 zones ciblées"
    )
    poste_contact_suggere: str = Field(
        description="Rôle du décideur idéal à approcher (ex: CTO, Head of AI, VP Engineering, Talent Acquisition)"
    )
    contexte: str = Field(
        description="Pourquoi cette boîte est pertinente : stack tech, secteur, recrutements tech/alternance"
    )


class ResultatSourcing(BaseModel):
    entreprises: list[EntrepriseCible]


def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL et SUPABASE_KEY doivent être définis dans .env")
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your-"):
        raise RuntimeError("GROQ_API_KEY doit être défini dans .env (https://console.groq.com/keys)")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def resolve_groq_model(client: httpx.Client) -> str:
    """Vérifie que le modèle demandé existe sur Groq, sinon sélectionne automatiquement le meilleur modèle actif."""
    resp = client.get(
        GROQ_MODELS_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
    )
    if resp.status_code != 200:
        logger.warning("Impossible de lister les modèles Groq (%s): %s", resp.status_code, resp.text)
        return GROQ_MODEL

    models = [m["id"] for m in resp.json().get("data", []) if isinstance(m, dict) and "id" in m]
    if GROQ_MODEL in models:
        return GROQ_MODEL

    # Exclusion des modèles audio / garde-fous non-chat
    excluded = ("whisper", "tts", "guard", "safeguard", "embed", "orpheus", "playai")
    chat_models = [m for m in models if not any(x in m.lower() for x in excluded)]

    # Ordre de préférence des meilleurs modèles généralistes sur Groq
    preferred_keywords = ("llama-4", "llama-3.3-70b", "llama-3.1-70b", "qwen", "deepseek", "llama", "gemma", "mixtral")
    for kw in preferred_keywords:
        for m in chat_models:
            if kw in m.lower():
                logger.info("Modèle '%s' remplacé automatiquement par le modèle Groq actif : '%s'", GROQ_MODEL, m)
                return m

    chosen = chat_models[0] if chat_models else GROQ_MODEL
    logger.info("Modèle Groq sélectionné automatiquement : '%s'", chosen)
    return chosen


def rechercher_entreprises_tech(
    domaine: str = "IA, Data, Software Engineering, Cloud",
    nb_entreprises: int = 10,
) -> list[EntrepriseCible]:
    """
    Appelle l'API Groq en mode JSON structuré pour lister des entreprises Tech
    qui recrutent sur Paris, La Défense, Vincennes et Montreuil (93).
    """
    zones_str = ", ".join(ZONES_CIBLES)

    prompt = (
        f"Liste {nb_entreprises} vraies entreprises technologiques, scale-ups, ESN innovantes ou grands groupes "
        f"ayant des bureaux à {zones_str} et qui recrutent régulièrement des profils Tech / Alternance "
        f"dans les domaines suivants : {domaine}.\n"
        f"Assure-toi d'inclure un bon équilibre géographique entre Paris, La Défense, Vincennes et Montreuil (93).\n"
        f"Attention : le champ 'localisation' doit valoir EXACTEMENT l'une de ces 4 valeurs : "
        f"'Paris', 'La Défense', 'Vincennes', ou 'Montreuil (93)'.\n"
        f"Réponds UNIQUEMENT avec un objet JSON strictement conforme à ce format :\n"
        f'{{\n'
        f'  "entreprises": [\n'
        f'    {{\n'
        f'      "entreprise": "Nom de la boîte",\n'
        f'      "site_web": "https://...",\n'
        f'      "localisation": "Paris",\n'
        f'      "poste_contact_suggere": "CTO / Head of AI / Talent Acquisition",\n'
        f'      "contexte": "Stack technique, produits et signaux de recrutement"\n'
        f'    }}\n'
        f'  ]\n'
        f'}}'
    )

    with httpx.Client(timeout=30.0) as client:
        active_model = resolve_groq_model(client)
        logger.info("Sourcing structuré via Groq (modèle: %s) sur : %s...", active_model, zones_str)

        resp = client.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            },
            json={
                "model": active_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Tu es un expert en recrutement Tech en Île-de-France. Tu réponds toujours en JSON valide.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
        )
        if resp.status_code >= 400:
            logger.error("Détail de l'erreur Groq (%s) : %s", resp.status_code, resp.text)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

    resultat = ResultatSourcing.model_validate_json(content)
    return resultat.entreprises


def sauvegarder_dans_supabase(supabase: Client, entreprises: list[EntrepriseCible]) -> int:
    """Insère les entreprises sourcées dans `prospection_alternance` sans écraser les prospects déjà traités."""
    ajoutes = 0
    for item in entreprises:
        existing = (
            supabase.table("prospection_alternance")
            .select("id, statut")
            .eq("entreprise", item.entreprise)
            .execute()
        )
        if existing.data:
            logger.info("⏭️ %s est déjà présent dans Supabase (statut: %s).", item.entreprise, existing.data[0]["statut"])
            continue

        payload = {
            "entreprise": item.entreprise,
            "site_web": item.site_web,
            "localisation": item.localisation,
            "poste_contact": item.poste_contact_suggere,
            "contexte": f"[{item.localisation}] {item.contexte}",
            "statut": "À enrichir",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        supabase.table("prospection_alternance").insert(payload).execute()
        logger.info("✅ Ajouté : %s (%s) -> statut 'À enrichir'", item.entreprise, item.localisation)
        ajoutes += 1

    return ajoutes


def run_sourcing(domaine: str, count: int):
    supabase = get_supabase_client()
    entreprises = rechercher_entreprises_tech(domaine=domaine, nb_entreprises=count)
    nb_ajoutes = sauvegarder_dans_supabase(supabase, entreprises)
    logger.info(
        "Sourcing terminé : %d/%d nouvelles entreprises insérées dans 'prospection_alternance' (statut 'À enrichir').",
        nb_ajoutes,
        len(entreprises),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sourcing structuré d'entreprises Tech qui recrutent à Paris, La Défense, Vincennes et Montreuil (93)."
    )
    parser.add_argument(
        "--domaine",
        type=str,
        default="IA, Data Science, Backend Python, Software Engineering",
        help="Domaine technique recherché pour l'alternance",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Nombre d'entreprises à sourcer",
    )
    args = parser.parse_args()
    run_sourcing(domaine=args.domaine, count=args.count)
