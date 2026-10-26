# Enlighten Me — Backend Architecture & Setup Blueprint

## 1. Directory Structure Specification

The backend is organized as a clean, stateless Python service inside `Enlighten me Backend/`:

```plaintext
Enlighten me Backend/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application factory & ASGI entrypoint
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # Pydantic Settings (ENV variables, secrets)
│   │   ├── security.py             # Supabase JWT authentication & Bearer token verification
│   │   └── logging.py              # Structured application logger
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py               # API v1 central router mount
│   │   ├── endpoints/
│   │   │   ├── __init__.py
│   │   │   ├── health.py           # GET /api/v1/health (health check)
│   │   │   ├── lectures.py         # POST /api/v1/lectures/process (core audio pipeline)
│   │   │   └── webhooks.py         # POST /api/v1/webhooks/revenuecat (subscription sync)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── audio.py                # Audio upload metadata & constraints
│   │   ├── study_guide.py          # Pydantic schemas for Gemini structured outputs & API response
│   │   └── webhook.py              # RevenueCat webhook payload schemas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── groq_transcription.py   # In-memory Groq Whisper Large V3 Turbo transcription
│   │   ├── gemini_structuring.py   # Gemini 2.5 Flash semantic structuring & Quality Gate
│   │   └── quota_service.py        # Supabase FUP quota validation & deduction
│   └── db/
│       ├── __init__.py
│       └── supabase_client.py      # Supabase client singleton (Service Role & User context)
├── sql/
│   └── 001_initial_schema.sql      # Supabase PostgreSQL tables, constraints, RLS policies
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_health.py
│   ├── test_fup_quota.py
│   ├── test_groq_service.py
│   ├── test_gemini_service.py
│   └── test_revenuecat_webhook.py
├── .env.example                    # Template environment variables
├── .gitignore
├── requirements.txt                # Pinned production dependencies
├── pyproject.toml                  # Tooling & linter configuration (Ruff/Black)
└── Caddyfile                       # Hetzner reverse proxy configuration (120s timeouts)
```

---

## 2. Core Dependencies & Environment Configuration

### `requirements.txt`
```text
fastapi>=0.115.0,<1.0.0
uvicorn[standard]>=0.32.0,<1.0.0
pydantic>=2.10.0,<3.0.0
pydantic-settings>=2.7.0,<3.0.0
python-multipart>=0.0.18
supabase>=2.11.0,<3.0.0
groq>=0.13.0,<1.0.0
google-genai>=0.1.1,<1.0.0
httpx>=0.28.0,<1.0.0
python-jose[cryptography]>=3.3.0
pytest>=8.3.0
pytest-asyncio>=0.24.0
```

### `.env.example`
```env
# Server
ENVIRONMENT=development
PORT=8000
DEBUG=True

# Supabase
SUPABASE_URL=https://<your-project-ref>.supabase.co
SUPABASE_KEY=<your-supabase-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<your-supabase-service-role-key>
SUPABASE_JWT_SECRET=<your-supabase-jwt-secret>

# Groq
GROQ_API_KEY=gsk_...

# Google Gemini
GEMINI_API_KEY=AIzaSy...

# RevenueCat
REVENUECAT_WEBHOOK_SECRET=<your-revenuecat-webhook-secret>

# Timeouts & Limits
MAX_AUDIO_BYTES=24000000 # 24 MB limit
ROUTER_TIMEOUT_SECONDS=120
```

---

## 3. Supabase PostgreSQL Schema & Security

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. SUBSCRIPTIONS & FUP TRACKING
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    revenuecat_app_user_id VARCHAR(255) UNIQUE NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'FREE', 
    plan_tier VARCHAR(50) NOT NULL DEFAULT 'FREE_TIER',
    current_period_end TIMESTAMP WITH TIME ZONE,
    fup_seconds_limit INT NOT NULL DEFAULT 10800,  -- 3 hours for Free Tier
    fup_seconds_used INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_fup_usage CHECK (fup_seconds_used >= 0)
);

-- 2. LECTURES METADATA
CREATE TABLE IF NOT EXISTS public.lectures (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL DEFAULT 'Untitled Lecture',
    status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED',
    duration_seconds INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. STUDY NOTES TABLE
CREATE TABLE IF NOT EXISTS public.study_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lecture_id UUID UNIQUE NOT NULL REFERENCES public.lectures(id) ON DELETE CASCADE,
    is_valid_lecture BOOLEAN NOT NULL DEFAULT TRUE,
    warning_banner TEXT,
    overall_summary TEXT NOT NULL,
    timestamped_timeline JSONB NOT NULL,          
    chronological_notes JSONB NOT NULL,           
    action_items JSONB NOT NULL,                  
    whatsapp_share_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Row Level Security (RLS)
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lectures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.study_notes ENABLE ROW LEVEL SECURITY;

-- Policies for Client-Direct Reads
CREATE POLICY "Users can view own subscription" 
    ON public.subscriptions FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can view own lectures" 
    ON public.lectures FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can view own study notes" 
    ON public.study_notes FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.lectures 
            WHERE public.lectures.id = public.study_notes.lecture_id 
              AND public.lectures.user_id = auth.uid()
        )
    );
```

---

## 4. In-Memory AI Processing Pipeline Flow

```plaintext
[ Mobile Client ]
       |
       | 1. POST /api/v1/lectures/process (Multipart: audio_file <= 24MB, duration_seconds)
       v
[ FastAPI Router ]
       |
       | 2. Verify Supabase JWT & validate FUP quota: (fup_seconds_used + duration <= fup_seconds_limit)
       |    If quota exceeded -> Return 403 Forbidden ("FUP_EXCEEDED")
       |    If file > 24MB   -> Return 413 Payload Too Large
       |
       | 3. Read audio_bytes directly into RAM (Zero Disk / Zero S3)
       |
       +-----> [ Groq Whisper Large V3 Turbo ]
       |            Prompt: "This is an Indian university technical lecture. The professor speaks in a mix of English, Hindi, and Marathi (Hinglish/Marathi). Ye topic samajh aaya? Next concept bagha."
       |            Model: whisper-large-v3-turbo, segment timestamps
       |
       |<----- Segments Array (Hinglish/Marathi/English raw text)
       |
       +-----> [ Gemini 2.5 Flash Engine ]
       |            Strict Pydantic Quality Gate & Structured Synthesis
       |            - Evaluates intelligibility (is_valid_lecture, warning_banner)
       |            - Translates & structures into Academic English:
       |                * overall_summary
       |                * timestamped_timeline
       |                * chronological_notes
       |                * action_items (exam_hint, assignment, deadline, reading)
       |                * whatsapp_share_text
       |
       |<----- Validated Pydantic StudyGuide Object
       |
       | 4. Flush audio_bytes from RAM
       | 5. Atomic DB Transaction: Insert lecture, insert study_notes, increment fup_seconds_used
       v
[ 200 OK Response ] -> Returns { lecture_id, remaining_fup_seconds, study_guide } to Client
```

---

## 5. Reverse Proxy & Timeout Boundary (Caddyfile)

```caddyfile
api.enlightenme.app {
    reverse_proxy localhost:8000 {
        # Ensure 120s timeout boundary for 60-min audio inference loops
        transport http {
            read_timeout 120s
            write_timeout 120s
        }
    }
}
```
