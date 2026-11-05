-- Table Supabase unifiée pour le sourcing, l'enrichissement, le pilotage et les relances J+7
CREATE TABLE IF NOT EXISTS public.prospection_alternance (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
  entreprise TEXT NOT NULL UNIQUE,
  site_web TEXT,
  localisation TEXT, -- Paris, La Défense, Vincennes, Montreuil (93)
  contexte TEXT,     -- Signaux de recrutement, stack technique, équipe ciblée
  nom_contact TEXT,
  email_contact TEXT,
  poste_contact TEXT, -- Ex: CTO, Head of AI, Lead Data, Talent Acquisition
  statut TEXT NOT NULL DEFAULT 'À enrichir' CHECK (
    statut IN (
      'À enrichir',
      'Enrichi',
      'En attente de validation',
      'En cours d''édition',
      'Prêt à envoyer',
      'Envoyé',
      'Relancé',
      'Entretien',
      'Refus'
    )
  ),
  edit_mode TEXT CHECK (edit_mode IN ('direct', 'ai')),
  telegram_message_id BIGINT,
  pitch_genere TEXT,
  date_envoi TIMESTAMP WITH TIME ZONE,
  -- Suivi des relances automatiques à J+7 (max 2 relances, puis clôture à 'Refus')
  nb_relances INTEGER NOT NULL DEFAULT 0 CHECK (nb_relances BETWEEN 0 AND 2),
  date_derniere_relance TIMESTAMP WITH TIME ZONE,
  dernier_message_relance TEXT
);

-- Migration douce si la table existe déjà
ALTER TABLE public.prospection_alternance
  ADD COLUMN IF NOT EXISTS nb_relances INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS date_derniere_relance TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS dernier_message_relance TEXT;

-- Index pour accélérer les requêtes de n8n et du tableau de bord
CREATE INDEX IF NOT EXISTS idx_prospection_alternance_statut
  ON public.prospection_alternance(statut);

-- Vue de Pilotage Central dans Supabase (suivi des validations et échéances J+7)
CREATE OR REPLACE VIEW public.vue_pilotage_alternance AS
SELECT
  id,
  entreprise,
  localisation,
  nom_contact,
  poste_contact,
  email_contact,
  statut,
  nb_relances,
  date_envoi,
  date_derniere_relance,
  COALESCE(date_derniere_relance, date_envoi) AS date_dernier_contact,
  CASE
    WHEN statut IN ('Envoyé', 'Relancé') AND COALESCE(date_derniere_relance, date_envoi) IS NOT NULL
    THEN COALESCE(date_derniere_relance, date_envoi) + INTERVAL '7 days'
    ELSE NULL
  END AS prochaine_echeance_j7,
  CASE
    WHEN statut IN ('Envoyé', 'Relancé') AND COALESCE(date_derniere_relance, date_envoi) IS NOT NULL
    THEN EXTRACT(DAY FROM (timezone('utc'::text, now()) - COALESCE(date_derniere_relance, date_envoi)))::INT
    ELSE NULL
  END AS jours_sans_reponse,
  CASE
    WHEN statut = 'En attente de validation' THEN 'À valider (Dashboard ou Telegram)'
    WHEN statut IN ('Envoyé', 'Relancé')
         AND COALESCE(date_derniere_relance, date_envoi) <= timezone('utc'::text, now()) - INTERVAL '7 days'
         AND nb_relances < 2
    THEN 'À relancer maintenant (Relance #' || (nb_relances + 1) || '/2)'
    WHEN statut IN ('Envoyé', 'Relancé')
         AND COALESCE(date_derniere_relance, date_envoi) <= timezone('utc'::text, now()) - INTERVAL '7 days'
         AND nb_relances >= 2
    THEN 'À clôturer en Refus (2 relances J+7 sans retour)'
    WHEN statut IN ('Envoyé', 'Relancé')
    THEN 'En attente de retour (' || nb_relances || '/2 relances)'
    ELSE statut
  END AS action_pilotage,
  pitch_genere,
  dernier_message_relance
FROM public.prospection_alternance
ORDER BY updated_at DESC;

-- Droits d'accès API Supabase (PostgREST) pour service_role, authenticated et anon
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON TABLE public.prospection_alternance TO anon, authenticated, service_role;
GRANT ALL ON TABLE public.vue_pilotage_alternance TO anon, authenticated, service_role;

