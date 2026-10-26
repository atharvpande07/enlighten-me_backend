-- =============================================================================
-- Migration: 001_initial_schema.sql
-- Description: Core database schema for Enlighten Me: Subscriptions (FUP), Lectures, Study Notes, and RLS policies
-- =============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- 1. SUBSCRIPTIONS & FAIR USAGE POLICY (FUP) TRACKING
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    revenuecat_app_user_id VARCHAR(255) UNIQUE NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'FREE', -- 'FREE', 'ACTIVE', 'CANCELED', 'PAST_DUE'
    plan_tier VARCHAR(50) NOT NULL DEFAULT 'FREE_TIER', -- 'FREE_TIER', 'PRO'
    current_period_end TIMESTAMP WITH TIME ZONE,
    fup_seconds_limit INT NOT NULL DEFAULT 10800, -- Free tier: 3 hours = 10,800s; Pro tier: 40 hours = 144,000s
    fup_seconds_used INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_fup_usage CHECK (fup_seconds_used >= 0),
    CONSTRAINT uq_subscriptions_user_id UNIQUE (user_id)
);

-- Index for rapid lookup by user_id
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON public.subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_revenuecat_id ON public.subscriptions(revenuecat_app_user_id);

-- -----------------------------------------------------------------------------
-- 2. LECTURES METADATA
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.lectures (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL DEFAULT 'Untitled Lecture',
    status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED', -- 'RECORDING', 'PROCESSING', 'COMPLETED', 'FAILED'
    duration_seconds INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lectures_user_id ON public.lectures(user_id);
CREATE INDEX IF NOT EXISTS idx_lectures_created_at ON public.lectures(created_at DESC);

-- -----------------------------------------------------------------------------
-- 3. STUDY NOTES (SYNTHESIZED AI STUDY HUB OUTPUT)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.study_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lecture_id UUID UNIQUE NOT NULL REFERENCES public.lectures(id) ON DELETE CASCADE,
    is_valid_lecture BOOLEAN NOT NULL DEFAULT TRUE,
    warning_banner TEXT,
    overall_summary TEXT NOT NULL,
    timestamped_timeline JSONB NOT NULL DEFAULT '[]'::jsonb,
    chronological_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    action_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    whatsapp_share_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_study_notes_lecture_id ON public.study_notes(lecture_id);

-- -----------------------------------------------------------------------------
-- 4. ROW LEVEL SECURITY (RLS) POLICIES
-- -----------------------------------------------------------------------------
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lectures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.study_notes ENABLE ROW LEVEL SECURITY;

-- Subscriptions Policies
DROP POLICY IF EXISTS "Users can view their own subscription" ON public.subscriptions;
CREATE POLICY "Users can view their own subscription"
    ON public.subscriptions
    FOR SELECT
    USING (auth.uid() = user_id);

-- Lectures Policies
DROP POLICY IF EXISTS "Users can view their own lectures" ON public.lectures;
CREATE POLICY "Users can view their own lectures"
    ON public.lectures
    FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own lectures" ON public.lectures;
CREATE POLICY "Users can insert their own lectures"
    ON public.lectures
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update their own lectures" ON public.lectures;
CREATE POLICY "Users can update their own lectures"
    ON public.lectures
    FOR UPDATE
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own lectures" ON public.lectures;
CREATE POLICY "Users can delete their own lectures"
    ON public.lectures
    FOR DELETE
    USING (auth.uid() = user_id);

-- Study Notes Policies (Access scoped via parent lecture ownership)
DROP POLICY IF EXISTS "Users can view study notes for their own lectures" ON public.study_notes;
CREATE POLICY "Users can view study notes for their own lectures"
    ON public.study_notes
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.lectures
            WHERE public.lectures.id = public.study_notes.lecture_id
              AND public.lectures.user_id = auth.uid()
        )
    );

-- -----------------------------------------------------------------------------
-- 5. AUTOMATIC FREE SUBSCRIPTION PROVISIONING TRIGGER (NEW USER SIGNUP)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
    INSERT INTO public.subscriptions (
        user_id,
        revenuecat_app_user_id,
        status,
        plan_tier,
        fup_seconds_limit,
        fup_seconds_used
    ) VALUES (
        NEW.id,
        NEW.id::text,
        'FREE',
        'FREE_TIER',
        10800,  -- 3 hours free quota
        0
    ) ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to execute upon user creation in auth.users
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
