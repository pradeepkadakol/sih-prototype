# VeriSight — inspection demo

VeriSight is a **fictional hackathon prototype** for Smart India Hackathon 2026 problem **SIH26095**, “Smart Real-Time Monitoring & Inspection Mobile App.” It demonstrates a case moving from reviewer assignment through inspector check-in, checklist, finding, evidence, submission, review, and follow-up. **Demo mode** and simulated features are labelled in the UI. This is not a production integration.

## Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer with npm
- A Supabase project with a PostgreSQL database and a private Storage bucket
- For local development, two terminals and internet access for the API, database, and evidence uploads

## Configure Supabase

1. In your chosen Supabase project, create a **private** Storage bucket named `verisight-evidence`. Set its maximum file size to **3 MB** and allowed MIME types to `image/png`, `image/jpeg`, and `image/webp`. The bucket must exist before uploads work.
2. Run `Copy-Item .env.example .env` at the repository root. Paste the **PostgreSQL connection string** from the Supabase **Connect** dialog into `DATABASE_URL`. Use the session pooler for a long-running local API if direct IPv6 is unavailable; use the transaction pooler for a serverless API. The backend requires TLS and disables prepared statements for transaction pooler connections.
3. Set `SUPABASE_URL` to the project's URL and `SUPABASE_SERVICE_ROLE_KEY` to the server-only legacy `service_role` JWT from **Project Settings → API Keys**. Keep this key in backend environment settings only. Never put it in `VITE_` variables or frontend code. Set `SUPABASE_STORAGE_BUCKET` if you chose a different bucket name.
4. Run `python -m app.init_db` from `backend` after installing its dependencies. This creates the isolated `verisight` PostgreSQL schema, enables row-level security on its tables, and seeds fictional accounts and cases. The script is safe to run again; it does not reset existing demo records. Leave `verisight` out of Supabase's exposed API schemas.

The app uses SQLAlchemy over a PostgreSQL connection for records and the Supabase Storage API for evidence. The frontend still calls FastAPI; it does not connect directly to Supabase.

For the single-project Vercel deployment below, leave `VITE_API_URL` empty. The browser calls `/api` on the same origin. The Vite `/api` proxy only applies during local development.

## Vercel Deployment

One Vercel project serves the Vite frontend and the FastAPI function. Supabase supplies PostgreSQL and the private evidence bucket; it does not host this application's API or UI.

1. Create your own Supabase project. Create the **private** `verisight-evidence` Storage bucket with a **3 MB** maximum and allowed MIME types `image/png`, `image/jpeg`, `image/webp`.
2. In Supabase **Connect**, copy the **Transaction pooler** PostgreSQL URL (port `6543`). URL-encode any special characters in its password. Get the project URL and the server-only legacy `service_role` key from **Project Settings → API Keys**.
3. Import this GitHub repository into **one** Vercel project. Set **Root Directory** to the repository root (`.`), not `frontend/`. Keep the root `vercel.json` settings: Framework Preset **Vite**, install `cd frontend && npm ci`, build `cd frontend && npm run build`, output `frontend/dist`. Do not set a separate backend URL or override these settings with old project values.
4. Add the environment variables below in Vercel **Project Settings → Environment Variables** for Production and any Preview environments you intend to use. Redeploy after changing build-time variables.

   | Variable | Visibility | Value |
   | --- | --- | --- |
   | `DATABASE_URL` | Server only | Supabase Transaction pooler PostgreSQL URL, port `6543` |
   | `SUPABASE_URL` | Server only | `https://<project-ref>.supabase.co` |
   | `SUPABASE_SERVICE_ROLE_KEY` | Server only | Supabase legacy `service_role` key; never use a `VITE_` prefix |
   | `SUPABASE_STORAGE_BUCKET` | Server only | `verisight-evidence` |
   | `GEOFENCE_RADIUS_METERS` | Server only | `250` |
   | `FRONTEND_ORIGINS` | Server only | `http://127.0.0.1:5173,http://localhost:5173`; append the deployed site origin if cross-origin calls are needed |
   | `VITE_API_URL` | Browser-visible | Leave unset or empty so requests use the same Vercel origin |

5. Install backend dependencies locally and initialize the Supabase database **once** before logging in. From the repository root in PowerShell:

   ```powershell
   Copy-Item .env.example .env
   # Fill DATABASE_URL, SUPABASE_URL, and SUPABASE_SERVICE_ROLE_KEY in .env.
   cd backend
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m app.init_db
   cd ..
   ```

   This command creates the `verisight` schema and fictional demo records; Vercel never runs it automatically. Keep that schema out of Supabase's exposed API schemas.
6. Deploy from Vercel. Open `https://<your-vercel-domain>/docs` to confirm FastAPI, then open `/` and sign in as `reviewer` with `demo1234`. The browser's `POST /api/login` should return JSON, and the reviewer and inspector workflows should use the same domain. `/reviewer` and `/inspections` serve the frontend shell if opened directly; this UI currently uses in-page state rather than URL-based React routes.

If an existing Vercel project was created with `frontend/` as its Root Directory, change it to the repository root and redeploy. Otherwise Vercel cannot see `api/index.py`, `vercel.json`, or the root Python requirements, and `/api/login` will return a static 404.

## Start locally (PowerShell)

In terminal 1, from the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.init_db
.\.venv\Scripts\python.exe -m uvicorn app.main:app --factory --host 127.0.0.1 --port 8000 --reload
```

In terminal 2, from the repository root:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open **http://127.0.0.1:5173**. The API docs are at **http://127.0.0.1:8000/docs**. PostgreSQL tables and fictional records are initialized by the explicit `app.init_db` command; evidence files go to your private Supabase bucket. Existing local `backend/verisight.db` and `backend/uploads/` files are not migrated automatically.

Keep **both terminals running** while using the app. If Vite prints `http proxy error: /api/login` with `ECONNREFUSED 127.0.0.1:8000`, the FastAPI backend is not running. Start the terminal 1 command above and wait for `Uvicorn running on http://127.0.0.1:8000`, then retry login. You can check the backend directly at **http://127.0.0.1:8000/docs**.

On Unix-like shells, use `python3 -m venv .venv`, `.venv/bin/python` and `npm` in place of the PowerShell commands. The Vite development server proxies `/api` to the local FastAPI server.

## Demo accounts

All seeded accounts use the password **`demo1234`**.

| Account | Role | Use |
| --- | --- | --- |
| `reviewer` | Reviewer / official | Dashboard, case creation, assignment, reviews, follow-ups |
| `inspector.arya` | Inspector | Assigned cases and field workflow |
| `inspector.kiran` | Inspector | Assigned cases and field workflow |
| `inspector.meera` | Inspector | Assigned cases and field workflow |

The seeded assignment uses a fresh random seed when the database is first initialized, so the assigned inspector for a given seeded case may vary. Sign in as the inspector shown on that case. An unavailable seeded inspector is excluded from draws.

## Five-minute walkthrough

1. Sign in as `reviewer`. View totals, coverage, site markers, recent findings, overdue follow-ups, and activity.
2. Open **Inspection cases**, choose a pending case, and select **Assign eligible inspector**. The case shows the ordered eligible IDs, weights, event number, algorithm version, selected inspector, and SHA-256 commitment.
3. Select **Reveal demo seed & verify**. The browser hashes the revealed seed and reruns the recorded weighted draw. Both checks must show a match. For reassignment, enter a reason; the earlier event remains in the history.
4. Sign out, choose the selected inspector, and open the assigned case. Use browser location if at the fictional site, or **Use demo override** on a seeded case. The override and location trust limits are visible in the record.
5. Answer required checklist items, add a finding, and upload an image or use the built-in sample. Select **Sync checklist now**. The local draft survives refresh or a failed sync until the server confirms it.
6. Open **Final review**, then submit. Sign back in as `reviewer`, open the same case, review the finding with a note, and create a follow-up action. Updated dashboard and queue counts reflect the work.
7. Optionally record **Remote verification (simulated)**. CCTV is explicitly unavailable in this MVP.

A shorter presentation script is in [docs/demo-script.md](docs/demo-script.md).

## Architecture and data

- **Frontend:** React, TypeScript, Vite, Leaflet with OpenStreetMap tiles and an always-visible site list fallback. Responsive inspector controls support a phone-sized viewport.
- **Backend:** FastAPI REST API with automatic OpenAPI docs and server-side role checks.
- **Storage:** Supabase PostgreSQL through SQLAlchemy, plus a private Supabase Storage bucket for evidence. App tables live in the `verisight` schema, outside the exposed Data API. Tables include users, sites, cases, append-only assignment events, inspections, checklist responses, findings, evidence, follow-up actions, audit events, remote verification events, and demo sessions. Foreign keys and indexes cover key lookups.
- **Demo authentication:** Seeded passwords are PBKDF2 hashed. Logins produce random 12-hour bearer sessions stored as token hashes. This is only a local demo and lacks production account controls.
- **Evidence:** The server accepts base64 encoded PNG/JPEG/WebP through `POST /api/inspections/{id}/evidence`, checks a 3 MB limit and file signature, uploads under a random key in the private bucket, then records SHA-256 of the received bytes and a server timestamp in PostgreSQL. Original filenames are retained only as display metadata. Optional capture time and coordinates are labelled client-reported. The 3 MB limit keeps the base64 JSON request under Vercel's 4.5 MB function body limit.
- **Offline drafts:** Checklist answers and notes are saved in browser `localStorage` per demo user and case. They can be manually synced, and a pending draft retries on the browser `online` event. The UI does not claim encryption or a successful submission until the server confirms it.

### Assignment verification algorithm

For each event, the server filters out inactive, unavailable, or case-excluded inspectors and sorts eligible IDs ascending. Every eligible inspector gets weight `1`; for a high-risk site, qualified inspectors get weight `4`. This preserves a chance for every eligible inspector. The server creates a fresh 32-byte cryptographic random seed and stores it privately. The public commitment is `SHA-256(seed)`.

For counter `0, 1, …`, the server computes `HMAC-SHA256(seed, message)`. `message` is UTF-8 JSON with **no whitespace** and keys in this order: `case_id`, `candidates`, `event_number`, `counter`; each candidate has keys `id`, `weight`. Treat the digest as an unsigned 256-bit big-endian integer `n`. Let `total` be the sum of weights and `limit = 2^256 - (2^256 mod total)`. Reject and increment the counter if `n >= limit`. Otherwise use `n mod total` to walk the ordered cumulative weights and pick an ID. This rejection step removes modulo bias. The algorithm identifier is `hmac-sha256-rejection-v1`.

The browser uses Web Crypto to verify the commitment and rerun the draw after a reviewer reveals the seed. Unrevealed seeds are never returned. A reveal adds an audit record; an assignment event is not edited. Reassignment requires a reason and appends a new numbered event. **This proves reproducibility of the local draw, not independent randomness or an audited beacon.**

### Transparent priority rules

The dashboard and case detail show plain-language flags for high-risk sites; open cases older than five days; check-ins without a verified geofence result; client-reported accuracy worse than 100 m; submissions within five minutes; failed checklist answers with no evidence; and two or more high-severity findings at the same site. These are deterministic triage rules on synthetic data, not a predictive model.

## API

The full interactive schema is at `/docs`. Main endpoints:

| Method | Path | Role |
| --- | --- | --- |
| `POST` | `/api/login` | Public demo login |
| `GET` | `/api/dashboard/summary` | Reviewer |
| `GET`, `POST` | `/api/inspections` | Both for listing; reviewer for creation |
| `GET` | `/api/inspections/{id}` | Reviewer or assigned inspector |
| `POST` | `/api/inspections/{id}/assign` | Reviewer |
| `GET` | `/api/inspections/{id}/assignment-history` | Reviewer or assigned inspector |
| `POST` | `/api/assignments/{id}/reveal-seed` | Reviewer |
| `POST` | `/api/inspections/{id}/check-in` | Assigned inspector |
| `PUT` | `/api/inspections/{id}/checklist` | Assigned inspector |
| `POST` | `/api/inspections/{id}/findings`, `/evidence`, `/submit` | Assigned inspector |
| `POST` | `/api/findings/{id}/review`, `/follow-ups` | Reviewer |
| `PUT` | `/api/follow-ups/{id}` | Reviewer |
| `POST` | `/api/remote-verification/simulate` | Reviewer |

Use `Authorization: Bearer <demo token>` after login. Input validation errors use HTTP 422; forbidden actions use 403; invalid workflow transitions use 409. Case listing supports `region`, `site` (site or organization text), `risk`, `status`, and `created_after` filters.

## Checks

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp=.pytest_tmp
```

From `frontend`:

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

The backend suite covers assignment eligibility and history, deterministic selection and commitment, geofence distance, required checklist submission, evidence hashing and MIME checks, reviewer role enforcement, and follow-up creation.

## Limitations and future adapters

This prototype uses fictional people, organizations, sites, and dates. It has no real agency directory, GIS boundary service, device attestation, video stream, offline encryption, independent randomness beacon, or production identity system. Browser geolocation and capture metadata can be spoofed. Evidence hashing detects later byte changes only when compared with a trusted record; it does not establish capture time, place, or authenticity. The demo password and browser bearer storage are not appropriate for real deployment. Supabase persistence does not turn this demo into a production system. Real use requires a security, privacy, legal, accessibility, and operational review, including retention rules and independent audit controls.

Future adapters could connect an agency identity provider, authoritative site registry, and WebRTC or RTSP/ONVIF remote verification. CCTV is unavailable in this MVP; no video is presented as live.
