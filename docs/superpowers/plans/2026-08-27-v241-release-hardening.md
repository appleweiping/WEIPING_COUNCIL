# v2.4.1 Release Hardening Plan

## Objective

Close the final persistence, observability, default-provider, and release-gate gaps found
by independent adversarial review before replacing the public default-branch history.

## Work

1. Make every protocol's real `SessionResult` pass the bounded artifact schema and add
   end-to-end protocol-to-store/API coverage.
2. Render every protocol-specific stage field through safe Markdown in the UI and safe
   terminal text in verbose CLI output.
3. Use current provider-qualified OpenRouter defaults without forcing one global model.
4. Extend the public-source scanner for common credential forms, private credential files,
   and alternative package-manager locks.
5. Synchronize version 2.4.1 across Python, frontend, documentation, and release notes.
6. Run the complete local/CI-equivalent gate, independent review, fresh-history audit,
   and remote post-push verification.

## Release Gates

- Python tests, Ruff, release scan, `pip check`, and `pip-audit` pass.
- Frontend tests, production build, and official-registry audit pass.
- Every named protocol can be serialized and loaded by `SessionStore`.
- Action workflows and tracked history contain no blocked credentials or private paths.
- Independent review reports no release blocker.
