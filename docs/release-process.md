# Release process

MOEX Fair Price follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## Source of truth

- `main` is the only release branch.
- `VERSION` contains the canonical application version without the leading `v`.
- Release notes live in `.release/vMAJOR.MINOR.PATCH.md`.
- Git tags and GitHub Releases use `vMAJOR.MINOR.PATCH` and must point to a commit already merged into `main`.

## Version rules

- `PATCH` — backward-compatible bug fixes and reliability fixes.
- `MINOR` — backward-compatible functionality.
- `MAJOR` — incompatible behavior, API or data-contract changes.
- Every release changes `VERSION` exactly once to the version being published.
- The release notes filename must match `VERSION` exactly.
- Versions are never reused or moved after publication.

## Documentation rule

Every application change that can affect users, operators, deployment, data semantics, external integrations or troubleshooting must be documented in the same pull request. At minimum, the release notes for the target version must describe the change. README or dedicated documentation must also be updated when operational behavior, configuration, architecture or user-facing semantics change.

## Release flow

1. Create a focused branch from current `main`.
2. Implement the change and tests.
3. Update the relevant documentation and `.release/vX.Y.Z.md`.
4. Set `VERSION` to `X.Y.Z`.
5. Open a pull request into `main` and require green CI.
6. Merge the pull request into `main`.
7. Release automation validates that the release-note version matches `VERSION` and publishes the GitHub Release from the `main` commit.
8. Deploy that immutable tag to production and verify health checks and the changed behavior.

Do not publish releases from feature, hotfix or temporary branches.
