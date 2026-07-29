# Sentinel implementation control

This directory is the durable source of truth for implementation sequencing,
cross-cutting decisions, and acceptance evidence.

## Merge policy

Every implementation branch must:

1. Own one bounded capability.
2. Include or update tests for its behavior.
3. Pass formatting, linting, type checking, and relevant test suites.
4. Rebase on the latest implementation `main` before integration.
5. Preserve centrally owned domain contracts and migrations.
6. Run the complete regression suite after merge.

The implementation parent resolves conflicts according to domain behavior and
both branches' tests. Feature branches do not independently merge or weaken
shared safety contracts.

## Credential policy

Development and automated acceptance use deterministic fake providers. Live
GitHub, model, and email credentials are requested only after all
credential-independent acceptance checks pass. Secrets must never be committed,
written to traces, or included in screenshots.
