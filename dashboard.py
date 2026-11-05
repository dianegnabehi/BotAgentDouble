import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv(override=True)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

st.set_page_config(
    page_title="Pilotage Prospection Alternance",
    page_icon="🎯",
    layout="wide",
)


@st.cache_resource
def init_clients() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("⚠️ SUPABASE_URL et SUPABASE_KEY doivent être configurés dans votre fichier `.env`.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def charger_prospects(supabase: Client) -> list[dict]:
    res = (
        supabase.table("prospection_alternance")
        .select("*")
        .order("updated_at", desc=True)
        .execute()
    )
    return res.data or []


def maj_prospect(supabase: Client, prospect_id: str, **fields):
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    supabase.table("prospection_alternance").update(fields).eq("id", prospect_id).execute()


def calculer_jours_sans_reponse(row: dict) -> int | None:
    ref_str = row.get("date_derniere_relance") or row.get("date_envoi")
    if not ref_str:
        return None
    ref_dt = datetime.fromisoformat(ref_str.replace("Z", "+00:00"))
    return max(0, (datetime.now(timezone.utc) - ref_dt).days)


def main():
    supabase = init_clients()
    st.title("🎯 Pilotage Central — Prospection Alternance Tech")
    st.caption(
        "Tableau de bord Supabase : validation des pitchs, suivi des envois et relances automatiques J+7 (max 2 relances, puis clôture à Refus)."
    )

    prospects = charger_prospects(supabase)

    # --- 1. KPIs en haut de page ---
    total = len(prospects)
    a_valider = sum(1 for p in prospects if p.get("statut") in ("En attente de validation", "Enrichi", "Prêt à envoyer"))
    en_cours_relance = sum(1 for p in prospects if p.get("statut") in ("Envoyé", "Relancé"))
    entretiens = sum(1 for p in prospects if p.get("statut") == "Entretien")
    refus = sum(1 for p in prospects if p.get("statut") == "Refus")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("🏢 Total Entreprises", total)
    col2.metric("📝 À valider / Prêts", a_valider)
    col3.metric("⏳ En suivi J+7 (Envoyé/Relancé)", en_cours_relance)
    col4.metric("🎉 Entretiens décrochés", entretiens)
    col5.metric("❌ Refus / Clôturés (2 relances)", refus)

    st.divider()

    tab_validation, tab_relances, tab_pipeline = st.tabs(
        [
            "✅ 1. Validation des Envois",
            "🔄 2. Suivi des Relances J+7 (Max 2)",
            "📊 3. Vue Globale Supabase",
        ]
    )

    # --- ONGLET 1 : VALIDATION DES ENVOIS ---
    with tab_validation:
        st.subheader("Pitchs en attente de validation avant envoi")
        candidats_validation = [
            p
            for p in prospects
            if p.get("statut") in ("En attente de validation", "En cours d'édition", "Prêt à envoyer")
        ]

        if not candidats_validation:
            st.info("Aucun pitch en attente de validation pour le moment.")
        else:
            for p in candidats_validation:
                with st.expander(
                    f"🏢 {p['entreprise']} ({p.get('localisation') or 'IDF'}) — 👤 {p.get('nom_contact') or 'N/A'} ({p.get('poste_contact') or 'N/A'}) — [{p['statut']}]",
                    expanded=True,
                ):
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        new_pitch = st.text_area(
                            "Pitch généré (éditable avant validation) :",
                            value=p.get("pitch_genere") or "",
                            height=150,
                            key=f"pitch_{p['id']}",
                        )
                    with c2:
                        st.markdown(f"**Email cible :** `{p.get('email_contact') or 'Non renseigné'}`")
                        st.markdown(f"**Site web :** {p.get('site_web') or 'N/A'}")
                        st.markdown(f"**Contexte :** {p.get('contexte') or 'N/A'}")

                        b1, b2 = st.columns(2)
                        if b1.button("✅ Valider (Prêt à envoyer)", key=f"val_{p['id']}", use_container_width=True):
                            maj_prospect(
                                supabase,
                                p["id"],
                                pitch_genere=new_pitch,
                                statut="Prêt à envoyer",
                                edit_mode=None,
                            )
                            st.success(f"{p['entreprise']} marqué 'Prêt à envoyer' (n8n expédiera l'email).")
                            st.rerun()

                        if b2.button("❌ Refuser", key=f"ref_{p['id']}", use_container_width=True):
                            maj_prospect(supabase, p["id"], statut="Refus", edit_mode=None)
                            st.warning(f"{p['entreprise']} passé en 'Refus'.")
                            st.rerun()

    # --- ONGLET 2 : SUIVI DES RELANCES AUTOMATIQUES J+7 ---
    with tab_relances:
        st.subheader("Suivi des candidatures envoyées & Relances automatiques J+7")
        st.markdown(
            "> **Règle métier active dans n8n :** Sans retour d'un contact à **J+7**, une relance est envoyée automatiquement "
            "(maximum **2 relances**). À **J+7 après la 2e relance** sans réponse, le contact est automatiquement clôturé à **`Refus`**."
        )

        actifs = [p for p in prospects if p.get("statut") in ("Envoyé", "Relancé")]
        if not actifs:
            st.info("Aucune candidature actuellement en attente de réponse ('Envoyé' ou 'Relancé').")
        else:
            for p in actifs:
                jours = calculer_jours_sans_reponse(p)
                nb_rel = p.get("nb_relances") or 0
                ref_str = p.get("date_derniere_relance") or p.get("date_envoi")
                echeance_str = "N/A"
                if ref_str:
                    echeance_dt = datetime.fromisoformat(ref_str.replace("Z", "+00:00")) + timedelta(days=7)
                    echeance_str = echeance_dt.strftime("%d/%m/%Y")

                if jours is not None and jours >= 7:
                    badge = (
                        f"🔴 Échéance J+7 atteinte ({jours}j) — "
                        + ("Prochaine action auto : Clôture Refus" if nb_rel >= 2 else f"Prochaine action auto : Relance #{nb_rel + 1}/2")
                    )
                else:
                    badge = f"🟢 J+{jours or 0}/7 (Prochaine échéance : {echeance_str})"

                with st.container(border=True):
                    col_info, col_relance, col_actions = st.columns([2, 2, 2])
                    with col_info:
                        st.markdown(f"### {p['entreprise']} ({p.get('localisation') or 'IDF'})")
                        st.markdown(
                            f"👤 **{p.get('nom_contact') or 'N/A'}** ({p.get('poste_contact') or 'N/A'})  \n"
                            f"📧 `{p.get('email_contact') or 'N/A'}`"
                        )
                    with col_relance:
                        st.markdown(f"**Statut actuel :** `{p['statut']}`")
                        st.markdown(f"**Relances effectuées :** `{nb_rel} / 2`")
                        st.markdown(f"**Suivi J+7 :** {badge}")
                    with col_actions:
                        st.write("Un retour du contact ? Stoppez les relances auto :")
                        a1, a2 = st.columns(2)
                        if a1.button("🎉 Entretien décroché", key=f"ent_{p['id']}", use_container_width=True):
                            maj_prospect(supabase, p["id"], statut="Entretien")
                            st.rerun()
                        if a2.button("🛑 Clôturer (Refus)", key=f"clo_{p['id']}", use_container_width=True):
                            maj_prospect(supabase, p["id"], statut="Refus")
                            st.rerun()

    # --- ONGLET 3 : VUE GLOBALE SUPABASE ---
    with tab_pipeline:
        st.subheader("Base complète `prospection_alternance`")
        filtre_statut = st.multiselect(
            "Filtrer par statut :",
            options=[
                "À enrichir",
                "Enrichi",
                "En attente de validation",
                "En cours d'édition",
                "Prêt à envoyer",
                "Envoyé",
                "Relancé",
                "Entretien",
                "Refus",
            ],
            default=[],
        )

        rows = [p for p in prospects if not filtre_statut or p.get("statut") in filtre_statut]
        if rows:
            df = pd.DataFrame(rows)
            colonnes_affichees = [
                c
                for c in [
                    "entreprise",
                    "localisation",
                    "nom_contact",
                    "poste_contact",
                    "email_contact",
                    "statut",
                    "nb_relances",
                    "date_envoi",
                    "date_derniere_relance",
                ]
                if c in df.columns
            ]
            st.dataframe(df[colonnes_affichees], use_container_width=True, hide_index=True)
        else:
            st.info("Aucune ligne ne correspond aux filtres sélectionnés.")


if __name__ == "__main__":
    main()
