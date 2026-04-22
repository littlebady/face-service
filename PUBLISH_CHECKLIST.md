# Publish Checklist

## 1. Local cleanup

- Confirm `.gitignore` excludes runtime artifacts
- Remove private datasets and temporary output files
- Confirm `README.md` is readable and up to date

## 2. Git initialization (if needed)

```bash
git init
git add .
git commit -m "chore: initial GitHub-ready project structure"
```

## 3. Create remote and push

```bash
git remote add origin <your-github-repo-url>
git branch -M main
git push -u origin main
```

## 4. Repository settings

- Add repository description/topics
- Verify license and visibility
- Enable branch protection for `main`
