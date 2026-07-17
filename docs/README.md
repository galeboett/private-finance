# Documentation index

This index separates current operating guidance from dated design reviews. For implemented behavior, use the current guides and verify material changes against `CHANGELOG.md`. Dated evaluations preserve the reasoning and baseline at the time they were written; they are not a description of the current build.

## Current project status

- [Implementation plan, iteration 3](pf-implementation-plan-iteration-3-7-14-26.md) — active phased plan and latest verification checkpoint.
- [Changelog](../CHANGELOG.md) — chronological record of implemented behavior.
- [User workflow](workflow.md) — importing, reviewing, reporting, reconciliation, recovery, and maintenance.
- [Repository README](../README.md) — setup, configuration, and high-level architecture.

## Data handling and recovery

- [Privacy risks](privacy-risks.md) — point-in-time privacy, retention, and local-security assessment.
- [Threat model](threat-model.md) — concise security boundary and remaining hardening work.
- [Backup and restore](backup-restore.md) — SQLite backups versus JSON app-data exports.
- [Statement ingestion](statement-ingestion.md) — local CSV, OFX/QFX, and PDF behavior.
- [Amount signs](amount-signs.md) — canonical money direction and import normalization.
- [Import preset formats](preset-format.md) — currently recognized import families.

## Contributor guidance

- [Collaboration workflow](collaboration.md) — branches, pull requests, and sensitive-file rules.
- [UX/UI gameplan](ux-ui-gameplan.md) — design direction and open interface cleanup; status is tracked in the active implementation plan.

## Historical evaluations

These documents are retained for decisions, rejected alternatives, and earlier baselines. Their line counts, test counts, defects, and phase statuses are historical.

- [Original remediation evaluation](private-finance-evaluation-and-plan.md)
- [Problems B–E architectural plan](7.12.26-fable-5-private-finance-evaluation-and-plan.md)
- [July 13 critique and gameplan](pf-critique-and-gameplan-7-13-26.md)

The iteration 3 plan supersedes their status reporting while continuing their unfinished phases.
