# Publishing on Zenodo

Two records, two purposes:

## 1. Software DOI (per release) — GitHub ↔ Zenodo integration
- Log in to https://zenodo.org with GitHub, go to *GitHub* in the account menu, flip the switch for `grainifier/grainifier` (the org must exist first and you must be its admin).
- `.zenodo.json` in the repo root provides title, creators, license, keywords and the cited papers; Zenodo reads it at release time.
- Each GitHub release gets its own DOI plus a concept DOI that always resolves to the latest version. v0.1.0 (2026-08-30): record https://zenodo.org/records/22171276, DOI 10.5281/zenodo.22171276, concept DOI 10.5281/zenodo.22171275 (used in the README badge and `CITATION.cff`). Later releases: `gh release create vX.Y.Z --notes ...` after bumping `pyproject.toml`, `grainifier/__init__.py`, `CITATION.cff`; nothing else to do.

## 2. Frame-statistics dataset — published 2026-08-30
Record https://zenodo.org/record/22170495, DOI 10.5281/zenodo.22170495 (version 2026.08), concept DOI 10.5281/zenodo.22170494. New stocks → `python tools/zenodo_upload.py <tarball> --metadata <json> --new-version 22170495`, review, `--deposition <new id> --publish`.
```
python tools/make_dataset.py --version 2026.08      # → dist/grainifier-frame-stats-2026.08.tar.gz (+ .zenodo.json)
```
- On zenodo.org: *New upload* → type *Dataset* → upload the tarball → copy the fields from `dist/*.zenodo.json` (title, description, creators, CC BY 4.0, keywords, related identifier "is supplement to" the GitHub repo). Reserve the DOI before publishing and put it in the repository README under *Profiles*.
- New versions: *New version* on the same record — Zenodo keeps one concept DOI across versions.
- Or with the uploader (token from `~/.config/zenodo/token` or `$ZENODO_TOKEN`; scopes `deposit:write` + `deposit:actions`, created at zenodo.org → Applications → Personal access tokens):
  ```
  python tools/zenodo_upload.py dist/grainifier-frame-stats-2026.08.tar.gz --metadata dist/grainifier-frame-stats-2026.08.zenodo.json            # draft + reserved DOI
  python tools/zenodo_upload.py ... --publish                                                                                                     # irreversible
  python tools/zenodo_upload.py ... --new-version <record id>                                                                                     # later versions
  ```
  `--sandbox` runs the same flow on https://sandbox.zenodo.org (separate account and token, `~/.config/zenodo/sandbox-token`).

What is in the dataset and what is not: per-patch statistics and per-bin spectra only — no image content, not invertible to pictures. The raw scans are not published.
