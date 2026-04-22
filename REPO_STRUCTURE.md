# Recommended Repository Structure

## Root-level essentials

- `README.md`
- `LICENSE`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `.gitignore`
- `.github/` (templates + workflows)

## Code layout

- `app/` for backend source
- `tests/` for automated tests
- `data/` for runtime data (ignored)
- `models/` for model artifacts (ignored)

## Upload strategy

- Keep only source code and lightweight config in Git
- Avoid committing databases, large models, and generated media
