# AutoApply AI — Phase 1 Starter

Phase 1 implements the foundation:
- FastAPI API
- Local resume upload for PDF/DOCX
- Basic text extraction and profile draft
- Job URL intake and duplicate detection
- SQLAlchemy persistence
- Simple health endpoint

It does **not** automate browser submissions yet. Browser navigation, ATS adapters, review UI, and approval-before-submit are Phase 2+.

## Requirements
- Python 3.11+
- Optional: PostgreSQL and Redis for a more production-like setup

## Quick start (SQLite)
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env  # Windows; on macOS/Linux use: cp .env.example .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000/docs

By default, the app uses SQLite for local development. Set `DATABASE_URL` in `.env` to PostgreSQL when ready.

## API
- `GET /health`
- `POST /api/v1/resumes` — multipart form field `file`
- `GET /api/v1/resumes/{resume_id}` — parsed resume metadata and extracted text preview
- `POST /api/v1/jobs` — JSON `{"url":"https://..."}`
- `GET /api/v1/jobs` — list submitted job URLs

## Example
```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"url":"https://jobs.example.com/role/123"}'
```

## Security notes before deployment
- This is a local MVP, not production-hardened.
- Add authentication/authorization before exposing it publicly.
- Keep `.env`, uploaded resumes, and database files out of Git.
- Add malware scanning, strict upload limits, rate limits, and retention/deletion controls before accepting untrusted uploads at scale.
- Don't store portal passwords or session cookies in plaintext.
- Only automate portals and interactions permitted by their terms; don't bypass CAPTCHA, MFA, or access controls.
- Final application submission will require a human review/approval checkpoint in the selected workflow.


## Phase 2.1: salary normalization and screenshots

- Salary JSON-LD is preserved in `salary_text` and normalized into `salary_min`, `salary_max`, `salary_currency`, and `salary_period` when available.
- Each inspection stores a full-page job-description screenshot under `data/screenshots/`.
- The inspector attempts to open a clearly labelled **Apply** control (never a submit/finalize control), inventories visible application fields, and saves an application-step screenshot when accessible.
- Screenshot paths are returned by the inspection API and stored as relative local paths. Keep `data/` out of version control.
- The startup performs additive SQLite column migration only; it does not delete existing records.

For a fresh browser installation: `python -m playwright install chromium`. Run with `python -m uvicorn app.main:app`.
