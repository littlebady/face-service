# Face Check-in Service
本项目安装包已上传至网盘：https://pan.quark.cn/s/5235cf3fda5c 提取码：MWTv        
- Face recognition and geo-fence check-in service based on FastAPI + InsightFace.

## Features

- Face registration, search, and identity matching
- Check-in API with location (geo-fence) validation
- Liveness/anti-spoof related service modules
- Excel export support for check-in data
- REST API with web pages and static assets

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
|-- start_all.ps1/.bat        # local startup scripts
`-- stop_all.ps1/.bat         # local stop scripts
```

## Quick Start

### 1. Environment

- Python 3.10+ recommended
- Windows PowerShell (scripts provided)

### 2. Install dependencies

```bash
pip install -r requirements.required.txt
```

If you need optional vector acceleration:

```bash
pip install -r requirements.optional.txt
```

### 3. Run service

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Or use scripts:

```bash
./start_all.ps1
```

### 4. Access

- Swagger docs: `http://localhost:8000/docs`
- Related pages are provided by `app/routers/pages.py`

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
