import os
import re
import logging
import argparse
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("pitch_generator")

# --- Configuration ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GROQ_API_KEY = (os.environ.get("GROQ_API_KEY") or os.environ.get("MISTRAL_API_KEY") or "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL") or "qwen/qwen3.8-27b"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_CHAT_ID = int(os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "0"))

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL et SUPABASE_KEY doivent être définis dans .env")
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your-"):
        raise RuntimeError("GROQ_API_KEY doit être défini dans .env")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN et TELEGRAM_ADMIN_CHAT_ID doivent être définis dans .env")

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
        return GROQ_MODEL

    models = [m["id"] for m in resp.json().get("data", []) if isinstance(m, dict) and "id" in m]
    if GROQ_MODEL in models:
        return GROQ_MODEL

    excluded = ("whisper", "tts", "guard", "safeguard", "embed", "orpheus", "playai")
    chat_models = [m for m in models if not any(x in m.lower() for x in excluded)]

    preferred_keywords = ("llama-4", "llama-3.3-70b", "llama-3.1-70b", "qwen", "deepseek", "llama", "gemma", "mixtral")
    for kw in preferred_keywords:
        for m in chat_models:
            if kw in m.lower():
                logger.info("Modèle Groq actif sélectionné automatiquement : '%s'", m)
                return m

    return chat_models[0] if chat_models else GROQ_MODEL


SYSTEM_PROMPT_FR = (
    "Tu es un ingénieur / candidat français en alternance Tech, IA & Data au style rédactionnel irréprochable.\n"
    "RÈGLES LINGUISTIQUES ET RÉDACTIONNELLES STRICTES :\n"
    "1. Rédige exclusivement dans un français professionnel, fluide, naturel et sans aucune faute d'orthographe, de grammaire ni d'accord.\n"
    "2. INTERDICTION ABSOLUE d'utiliser des mots espagnols, portugais ou inventés (ex: n'écris JAMAIS 'foco', écris 'priorité' ou 'orientation' ; n'écris JAMAIS 'idéeaux', écris 'idéaux').\n"
    "3. Bannir les formules creuses ou robotiques ('J'espère que vous allez bien', 'Je me permets de vous contacter', 'Passionné par').\n"
    "4. Structure l'email en 3 paragraphes courts (90 à 115 mots maximum au total) :\n"
    "   - Paragraphe 1 : Accroche directe et précise sur l'entreprise, sa stack ou ses projets Tech/IA.\n"
    "   - Paragraphe 2 : Ce que tu apportes opérationnellement en alternance (développement Python/IA, automatisation, pipelines de données, mise en production).\n"
    "   - Paragraphe 3 : Proposition sobre d'un court échange de 10 minutes.\n"
    "5. Relis attentivement chaque mot avant de répondre pour garantir zéro faute d'orthographe.\n"
    "6. Réponds UNIQUEMENT avec le corps du message (sans objet, sans balises, sans commentaire autour)."
)


def generate_pitch(prospect: dict) -> str:
    """Appelle Groq pour rédiger un pitch d'approche directe en français irréprochable pour une alternance Tech."""
    nom_contact = (prospect.get("nom_contact") or "").strip()
    salutation_hint = (
        f"Commence par 'Bonjour {nom_contact},'"
        if nom_contact and nom_contact.lower() not in ("équipe tech", "equipe tech", "non renseigné", "n/a")
        else "Commence par 'Bonjour,'"
    )
    prompt = (
        f"Rédige un email d'approche directe personnalisé pour une alternance Tech / IA / Data destiné à :\n"
        f"- Destinataire : {nom_contact or 'Décideur Tech'} ({prospect.get('poste_contact') or 'CTO / Responsable Tech'})\n"
        f"- Entreprise : {prospect.get('entreprise')} ({prospect.get('site_web') or 'N/A'})\n"
        f"- Localisation : {prospect.get('localisation') or 'Île-de-France'}\n"
        f"- Contexte & signaux techniques : {prospect.get('contexte') or 'Développement Tech & IA'}\n\n"
        f"Consignes :\n"
        f"- {salutation_hint}\n"
        f"- Vérifie scrupuleusement l'orthographe française de chaque mot (aucun mot étranger comme 'foco' ni faute d'accord).\n"
        f"- Reste concis (maximum 115 mots), concret et humain."
    )
    with httpx.Client(timeout=30.0) as client:
        active_model = resolve_groq_model(client)
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
                    {"role": "system", "content": SYSTEM_PROMPT_FR},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.25,
            },
        )
        if resp.status_code >= 400:
            logger.error("Détail de l'erreur Groq (%s) : %s", resp.status_code, resp.text)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Filet de sécurité contre les fautes fréquentes de tokenisation Qwen
        cleaned = re.sub(r"\bfoco\b", "focus", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bidéeaux\b", "idéaux", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bidéeales\b", "idéales", cleaned, flags=re.IGNORECASE)
        return cleaned


def build_review_keyboard(pitch_id: str) -> dict:
    """Clavier inline Telegram intercepté par le Webhook n8n."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Valider & Envoyer Email", "callback_data": f"approve:{pitch_id}"},
                {"text": "❌ Refuser", "callback_data": f"reject:{pitch_id}"},
            ],
            [
                {"text": "✏️ Éditer (texte)", "callback_data": f"edit_direct:{pitch_id}"},
                {"text": "🤖 Éditer via IA", "callback_data": f"edit_ai:{pitch_id}"},
            ],
        ]
    }


def format_telegram_card(prospect: dict, pitch_text: str) -> str:
    return (
        f"🎯 Candidature Alternance à valider\n\n"
        f"🏢 Entreprise : {prospect.get('entreprise')} ({prospect.get('localisation') or 'IDF'})\n"
        f"🌐 Site : {prospect.get('site_web') or 'N/A'}\n"
        f"👤 Contact : {prospect.get('nom_contact') or 'Non renseigné'} — {prospect.get('poste_contact') or 'N/A'}\n"
        f"📧 Email : {prospect.get('email_contact') or 'Non trouvé'}\n\n"
        f"💬 Pitch généré :\n"
        f"--------------------\n"
        f"{pitch_text}\n"
        f"--------------------"
    )


def send_pitch_to_telegram(prospect: dict, pitch_text: str) -> int:
    """Envoie le pitch sur Telegram et retourne le message_id."""
    text = format_telegram_card(prospect, pitch_text)
    reply_markup = build_review_keyboard(prospect["id"])

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{TELEGRAM_API_BASE}/sendMessage",
            json={
                "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                "text": text,
                "reply_markup": reply_markup,
            },
        )
        if resp.status_code >= 400:
            logger.error("Détail de l'erreur Telegram (%s) : %s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]


def run_batch(limit: int = 5):
    supabase = get_supabase_client()

    res = (
        supabase.table("prospection_alternance")
        .select("*")
        .eq("statut", "Enrichi")
        .neq("email_contact", "")
        .not_.is_("email_contact", "null")
        .limit(limit)
        .execute()
    )
    prospects = [p for p in (res.data or []) if "@" in (p.get("email_contact") or "")]

    if not prospects:
        logger.info("Aucun prospect enrichi avec email valide trouvé dans prospection_alternance.")
        return

    logger.info("%d prospect(s) qualifié(s) à traiter...", len(prospects))

    for prospect in prospects:
        pitch_id = prospect["id"]
        logger.info(
            "Génération du pitch via Groq pour %s — Contact: %s (%s)...",
            prospect["entreprise"],
            prospect.get("nom_contact"),
            prospect.get("email_contact"),
        )

        pitch_text = generate_pitch(prospect)
        msg_id = send_pitch_to_telegram(prospect, pitch_text)

        supabase.table("prospection_alternance").update(
            {
                "pitch_genere": pitch_text,
                "statut": "En attente de validation",
                "telegram_message_id": msg_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", pitch_id).execute()

        logger.info("Pitch %s envoyé sur Telegram (message_id=%s).", pitch_id, msg_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère les pitchs des contacts enrichis et les envoie sur Telegram.")
    parser.add_argument("--limit", type=int, default=5, help="Nombre max de prospects à traiter")
    args = parser.parse_args()
    run_batch(limit=args.limit)
