# Enlighten Me — Production Deployment Runbook (Hetzner CX22 + Caddy + Docker)

This guide documents the exact, step-by-step procedure to deploy the Enlighten Me stateless backend service on a **Hetzner CX22 (€3.79 / ~$4.00/month)** instance with automatic Let's Encrypt TLS and 120-second timeout boundaries.

---

## 1. Prerequisites Checklist

- [ ] A Hetzner Cloud CX22 instance (2 vCPU, 4GB RAM, 40GB NVMe) running Ubuntu 24.04 LTS.
- [ ] Domain DNS configured: An `A` record pointing `api.enlightenme.app` to your Hetzner public IPv4.
- [ ] Supabase project credentials (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`).
- [ ] AI API keys: Groq API Key (`GROQ_API_KEY`) and Google Gemini API Key (`GEMINI_API_KEY`).
- [ ] RevenueCat Webhook Secret (`REVENUECAT_WEBHOOK_SECRET`).

---

## 2. Supabase PostgreSQL Schema Setup

Before launching the backend container, apply the database migration:

1. Open your Supabase Dashboard -> **SQL Editor**.
2. Copy and paste the contents of [`sql/001_initial_schema.sql`](./sql/001_initial_schema.sql).
3. Click **Run**.
4. Confirm tables `subscriptions`, `lectures`, and `study_notes` are created with RLS enabled and the trigger `on_auth_user_created` active.

---

## 3. Server Provisioning & Docker Installation (Hetzner CX22)

SSH into your Hetzner server:
```bash
ssh root@<YOUR_HETZNER_IP>
```

Update packages and install Docker with Docker Compose:
```bash
apt-get update && apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg ufw git

# Install Docker engine
curl -fsSL https://get.docker.com | sh

# Configure Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (Let's Encrypt ACME challenge)
ufw allow 443/tcp   # HTTPS
ufw allow 443/udp   # HTTP/3 (QUIC)
ufw --force enable
```

---

## 4. Deploying the Backend Service

Clone the repository into `/opt/enlighten-me-backend`:
```bash
cd /opt
git clone <YOUR_GIT_REPO_URL> enlighten-me-backend
cd enlighten-me-backend/"Enlighten me Backend"
```

Create the production environment file:
```bash
cp .env.example .env
nano .env
```

Populate `.env` with live production secrets:
```env
ENVIRONMENT=production
PORT=8000
DEBUG=False

# Supabase
SUPABASE_URL=https://<your-project-ref>.supabase.co
SUPABASE_KEY=<your-anon-public-key>
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-secret-key>
SUPABASE_JWT_SECRET=<your-supabase-jwt-secret>

# AI API Keys
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIzaSy...

# RevenueCat
REVENUECAT_WEBHOOK_SECRET=<your-webhook-secret>

# Guardrails
MAX_AUDIO_BYTES=24000000
ROUTER_TIMEOUT_SECONDS=120
DOMAIN=api.enlightenme.app
```

Launch containers in the background:
```bash
docker compose up -d --build
```

---

## 5. Live Verification & Diagnostics

Verify containers are running and healthy:
```bash
docker ps
```
Expected output:
- `enlighten_api_backend` (status: `healthy`)
- `enlighten_caddy_proxy` (ports: `80/tcp`, `443/tcp`, `443/udp`)

Run the automated diagnostic suite against the live deployment:
```bash
python3 scripts/verify_deployment.py https://api.enlightenme.app
```

Expected diagnostic output:
```plaintext
>> Running Enlighten Me Deployment Diagnostics against: https://api.enlightenme.app

  [PASS] Root Discovery Endpoint (/) is online
  [PASS] Health Diagnostic (/api/v1/health) verified (v1.0.0, Max Audio: 22.89MB, Timeout: 120s)
  [PASS] JWT Security Dependency properly rejects unauthenticated uploads (401)
  [PASS] Webhook Security Dependency properly rejects unauthenticated calls (401)

-- Diagnostics Summary: 4/4 Checks Passed --
```

---

## 6. Zero-Downtime Rolling Updates

When rolling out updates or new sprints:
```bash
cd /opt/enlighten-me-backend/"Enlighten me Backend"
git pull origin main

# Rebuild backend container without downtime
docker compose build backend
docker compose up -d --no-deps backend
```

---

## 7. Log Inspection & Troubleshooting

Inspect live application logs:
```bash
# FastAPI application logs
docker logs -f enlighten_api_backend

# Caddy TLS & access logs
docker logs -f enlighten_caddy_proxy
```
