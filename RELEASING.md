# Releasing

HACS treats **GitHub releases as versions**. Without a release, HACS falls back
to the default branch, which means every user silently tracks whatever is on
`main` rather than a version you chose to ship. So: cut a release for anything
you want people to install.

Home Assistant, meanwhile, reads the version from
`custom_components/ica/manifest.json`. Those two numbers must agree, or HACS
offers one version while HA reports another. `.github/workflows/release.yml`
fails the release if they don't.

## Cutting a release

1. Make sure `main` is green (the `Validate` workflow: gates + hassfest + HACS).
2. Bump the version in `custom_components/ica/manifest.json`, e.g. `"version": "0.2.0"`.
3. Commit it:
   ```bash
   git commit -am "chore: release 0.2.0"
   git push
   ```
4. Tag with a leading `v` and push the tag:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

Pushing the tag triggers `release.yml`, which verifies the tag matches the
manifest, re-runs the full gates, and publishes the GitHub release with
generated notes. If the versions disagree the release is not created — fix the
manifest, delete the tag (`git tag -d v0.2.0 && git push --delete origin v0.2.0`),
and tag again.

## Versioning

Semantic versioning, judged from the user's side:

- **patch** (`0.1.1`) — bug fixes, no behaviour change users must adapt to.
- **minor** (`0.2.0`) — new actions, new entities, new options.
- **major** (`1.0.0`) — breaking changes: an action renamed or its response
  fields changed, an entity's `unique_id` changed, config-entry data reshaped
  without a migration.

Renaming an action or changing a response key **is** breaking here: people wire
these into ESPHome devices and automations. If it must change, keep the old
name working for a release and say so in the notes.

## Before the first public release

- The repository must be **public** — HACS cannot install from a private repo.
- The repo needs a **description** and **topics** (HACS's own inclusion criteria
  check for these).
- `hacs.json` and `manifest.json` are already in place and validated by the
  `hacs` and `hassfest` jobs on every push to `main`.
