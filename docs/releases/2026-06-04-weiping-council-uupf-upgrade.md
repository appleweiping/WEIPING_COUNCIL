# WEIPING_COUNCIL UUPF Upgrade

Recorded: 2026-06-04

## Source Run

The WEIPING_COUNCIL rename and upgrade pass was grounded in an ignored local UUPF
work area. That operator-specific location is deliberately not part of this public
release contract.

Run details:

- Run ID: `2026-06-04T115552Z0000-vipin-council`
- Iterations completed: 108
- Provider mode: offline
- Final score estimate: 6.13
- Release gate: `manual_review_required`
- Workspace and input copies remained in the ignored local audit work area and were
  not published or made runtime dependencies.

Because the UUPF run was offline, this repository records the run as an upgrade audit and planning artifact. It does not claim that the UUPF process alone performed a publishable code rewrite.

## Materialized Changes

This repository materializes the safe rename and public identity portion of the upgrade:

- README identity changed to `WEIPING_COUNCIL`, including banner alt text, clone URL, and neighbor-project relationship language for `WEIPING_COUNCIL` and `WEIPING_LAB`.
- Python package metadata changed from `vipin-council` to `weiping-council`.
- Frontend package metadata changed from `vipin-council-ui` to `weiping-council-ui`, including the package lock root metadata.
- FastAPI title, CLI banner/description/docstrings, start script banner, browser title, and visible UI brand text now use `WEIPING_COUNCIL` or Weiping Council.
- The Codex project skill moved from `.codex/skills/vipin-council/SKILL.md` to `.codex/skills/weiping-council/SKILL.md`, with descriptions updated for the new repository identity.
- Historical references to Vipin Council / `vipin-council` are retained only where needed for compatibility or release-history context.

## Compatibility

The legacy `vc.py` CLI remains the supported command entry point, and the `vc` console script is preserved. Existing local checkouts, session artifacts, and notes may still contain the former Vipin Council / `vipin-council` names; treat them as compatibility aliases unless they appear in historical release notes.

## Boundaries

This pass intentionally did not:

- write, expose, or normalize secrets, API keys, `.env` values, private endpoints, or account state;
- add or strengthen research claims, experiment claims, benchmark claims, dataset claims, or scientific conclusions;
- modify research-facing projects or AGENTIC_SCIENCE release packs outside this repository;
- rename the physical local checkout directory;
- change the GitHub remote, create commits, push branches, or perform the actual GitHub repository rename.

Manual review is still required before treating this as a public release.
