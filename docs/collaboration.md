# Collaboration Workflow

This project should use GitHub as the shared source of truth. Each person works on their own branch, opens a pull request, and merges only after the app builds and the other person can review the change.

## Daily Flow

1. Start from the latest `main`.

```powershell
git switch main
git pull
```

2. Create a branch for one focused change.

```powershell
git switch -c feature/rule-bulk-apply
```

3. Make changes locally and test them.

```powershell
.\run.ps1
```

4. Commit with a short message that says what changed.

```powershell
git add .
git commit -m "Add bulk rule application"
```

5. Push the branch and open a GitHub pull request.

```powershell
git push -u origin feature/rule-bulk-apply
```

## Pull Requests

A pull request is the main place your co-worker will see notes about a change.

- The PR title should say the user-facing outcome.
- The PR description should explain what changed, how to test it, and any risks.
- Screenshots are helpful for UI changes.
- Review comments can be left on specific lines of code.
- After merging, both people should pull `main` again.

## Keeping Each Other Updated

GitHub does not automatically show detailed notes just because a commit exists. Your co-worker will see commit messages, changed files, and pull request descriptions. The best shared notes live in:

- pull request descriptions
- pull request comments
- GitHub Issues for planned work or bugs
- docs files in this repo for durable decisions

## Recommended Rules

- Keep `main` stable and runnable.
- Use one branch per feature or bug fix.
- Pull the latest `main` before starting new work.
- Do not commit local database files, bank CSVs, exports, backups, passwords, or `.env` files.
- Put product decisions in `docs/` when they should outlive a chat or pull request.
- Prefer small pull requests. They are easier to review and less likely to conflict.

## Suggested PR Template

```markdown
## What changed

## How to test

## Notes or risks
```
