The project installation package has been uploaded to cloud storage: https://pan.quark.cn/s/5235cf3fda5c, extraction code: MWTv

# Face Check-in Service

Face recognition and geo-fence check-in service based on FastAPI + InsightFace.

## Features

- Face registration, search, and identity matching
- Check-in API with location (geo-fence) validation
- Liveness/anti-spoof related service modules
- Excel export support for check-in data
- REST API with web pages and static assets
- Universal sign-in workflow:
  - Any user can register/login
  - Any logged-in user can publish sign-in sessions
  - Participants scan QR code to complete sign-in
  - Publisher can view session records and statistics

## Project Structure

```text
.
|-- app/                      # FastAPI application package
|   |-- core/                 # settings, logging
|   |-- routers/              # API/page routes
|   |-- services/             # business logic
|   |-- static/               # frontend assets
|   `-- utils/                # helpers
|-- tests/                    # pytest unit tests
|-- checkinexcel/             # Java excel-related submodule
|-- api.py                    # FastAPI entrypoint
|-- requirements*.txt         # dependency groups
|-- start_all.ps1/.bat/.sh    # local startup scripts (Windows/Linux)
`-- stop_all.ps1/.bat/.sh     # local stop scripts (Windows/Linux)
```

## Quick Start

### 1. Environment

- Python 3.10+ recommended
- Windows PowerShell or Linux Bash

### 2. Install dependencies

```bash
pip install -r requirements.required.txt
```

If you need optional vector acceleration:

```bash
pip install -r requirements.optional.txt
```

### 3. Prepare models

- Model package download: `https://pan.quark.cn/s/56dd79fd6e86`, extraction code: `LL6p`
- After downloading, extract/place the model files under the project root `models/` directory.
- InsightFace model files are stored under `models/` (first run may auto-download `buffalo_l`).
- Strict liveness uses an anti-spoof ONNX model.
- Put model file at `models/anti_spoof/anti_spoof.onnx`, or set:

```powershell
$env:FACE_SERVICE_ANTISPOOF_MODEL_PATH = "D:\path\to\anti_spoof.onnx"
```

- If `FACE_SERVICE_ANTISPOOF_REQUIRED=true` and model file is missing, `/checkins/liveness/verify` will fail.

### 4. Run service (recommended)

Use the script-first workflow:

Windows:

1. Double-click `start_all.bat` in project root (or run `.\start_all.bat`).
2. Wait a few seconds for startup.
3. Open status file `.run/services.json`.
4. Use URLs from that file:
   - `home_url`
   - `checkin_url`
   - `analysis_url`
   - `docs_url`

Linux:

1. Ensure scripts are executable:
   - `chmod +x start_all.sh stop_all.sh`
2. Start service:
   - `./start_all.sh`
3. Wait a few seconds for startup.
4. Open status file `.run/services.json`.
5. Use URLs from that file:
   - `home_url`
   - `checkin_url`
   - `analysis_url`
   - `docs_url`

The startup script auto-selects an available port (default range `8000-8010`), so check `.run/services.json` first.

You can also pass public base URL explicitly (for QR links):

- Windows: `start_all.bat http://<server-ip>`
- Linux: `./start_all.sh --public-base-url http://<server-ip>`

Optional manual mode (debug only):

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Access

- Prefer URLs from `.run/services.json` after script startup.
- Default root `/` now redirects to `/app/login`.
- New universal check-in console:
  - Login/Register: `/app/login`
  - Dashboard (publish/view): `/app/dashboard`
  - QR scan page pattern: `/s/{token}`
  - Default demo account: `teacher / teacher123`
- Legacy page is still available at `/checkin-ui`.
- If QR links are opened by phones on LAN/internet, set:
  - `FACE_SERVICE_PUBLIC_BASE_URL=http://<server-ip>:<port>`
  - Then restart service and re-publish the session so QR uses the reachable address (not localhost).
- Stop service:
  - Windows: `.\stop_all.bat` or `.\stop_all.ps1`
  - Linux: `./stop_all.sh`

### 6. Strict liveness flow

Recommended secure sequence:

1. Call `POST /checkins/liveness/challenge` to get a one-time challenge.
2. Client performs action challenge and prepares:
   - `proof` (JSON string),
   - `key_image` (key frame),
   - `key_image_hash` (SHA256 hex of key frame),
   - optional `evidence_frames` (short frame sequence).
3. Call `POST /checkins/liveness/verify` and get `liveness_ticket`.
4. Call `POST /checkin` with attendance image + location + `liveness_ticket`.

Important behavior:

- If `FACE_SERVICE_STRICT_LIVENESS_REQUIRED=true`, `/checkin` without `liveness_ticket` is rejected.
- Ticket is one-time and time-limited.
- Session binding includes key-image hash and face similarity check.

Recommended env vars:

- `FACE_SERVICE_STRICT_LIVENESS_REQUIRED=true`
- `FACE_SERVICE_ANTISPOOF_REQUIRED=true`
- `FACE_SERVICE_ANTISPOOF_MIN_LIVE_SCORE=0.60`
- `FACE_SERVICE_LIVENESS_SIGNING_KEY=<strong-random-secret>`
- `FACE_SERVICE_LIVENESS_TICKET_TTL_SECONDS=180`
- `FACE_SERVICE_LIVENESS_SESSION_FACE_MIN_SIMILARITY=0.62`

For full details, see `STRICT_LIVENESS.md`.

## Testing

```bash
pytest -q
```

## GitHub Ready Files

This repository now includes common GitHub community and collaboration files:

- `.github/ISSUE_TEMPLATE/`
- `.github/pull_request_template.md`
- `.github/workflows/ci.yml`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `LICENSE`

## Notes Before Public Upload

- Current `.gitignore` excludes runtime data (`*.db`, `data/`, media, model artifacts).
- Check whether any private dataset or credential-like files are still present before pushing.
- Update author/team name in `LICENSE` if needed.
