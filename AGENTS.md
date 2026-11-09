## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (`JoravarSinghPunia/arkanine-ai`) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Branching

Never commit to `main`. Put every change on a new branch named `<type>/<issue-number>-<short-kebab-slug>`, where `<type>` is `feat`, `fix`, `docs`, `chore` or `refactor` (e.g. `feat/2-walking-skeleton-test-harness`). Branch from an up-to-date `main`, and reference the issue (`#<n>`) in commit messages and the PR.
