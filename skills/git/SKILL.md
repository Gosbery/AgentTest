---
name: git
description: Git workflow helpers and best practices
tags: vcs, workflow, collaboration
---

# Git Workflow

## Commit Message Convention
- Format: `<type>(<scope>): <subject>`
- Types: feat, fix, docs, style, refactor, test, chore
- Subject line: max 50 chars, imperative mood
- Body: wrap at 72 chars, explain WHAT and WHY

## Branch Naming
- `feature/<description>` - new features
- `fix/<description>` - bug fixes
- `refactor/<description>` - code refactoring
- `docs/<description>` - documentation changes

## Workflow Steps
1. Check current status: `git status`
2. Create feature branch: `git checkout -b feature/name`
3. Make changes and stage: `git add <files>`
4. Commit with descriptive message: `git commit -m "type: description"`
5. Push and create PR: `git push -u origin feature/name`

## Best Practices
- Small, focused commits (one logical change per commit)
- Commit early and often, then squash if needed
- Always pull rebase before pushing: `git pull --rebase`
- Never force push to main/master
