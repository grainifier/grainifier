# Publishing on Zenodo

Two records, two purposes:

## 1. Software DOI (per release) — GitHub ↔ Zenodo integration
- Log in to https://zenodo.org with GitHub, go to *GitHub* in the account menu, flip the switch for `grainifier/grainifier` (the org must exist first and you must be its admin).
- `.zenodo.json` in the repo root provides title, creators, license, keywords and the cited papers; Zenodo reads it at release time.
- Each GitHub release (`gh release create v0.1.0 --generate-notes`) then gets its own DOI plus a concept DOI that always resolves to the latest version. Paste the concept DOI badge into the README and `CITATION.cff` (`doi:` field) once it exists.

## 2. Frame-statistics dataset (manual upload, updated when new stocks are profiled)
```
python tools/make_dataset.py --version 2026.08      # → dist/grainifier-frame-stats-2026.08.tar.gz (+ .zenodo.json)
```
- On zenodo.org: *New upload* → type *Dataset* → upload the tarball → copy the fields from `dist/*.zenodo.json` (title, description, creators, CC BY 4.0, keywords, related identifier "is supplement to" the GitHub repo). Reserve the DOI before publishing and put it in the repository README under *Profiles*.
- New versions: *New version* on the same record — Zenodo keeps one concept DOI across versions.
- Alternatively via the REST API with a personal access token (`deposit:write`, `deposit:actions`):
  `curl -H "Authorization: Bearer $ZENODO_TOKEN" https://zenodo.org/api/deposit/depositions -X POST -d @dist/<name>.zenodo.json -H 'Content-Type: application/json'`, then PUT the file to the returned `links.bucket`, then POST `.../actions/publish`. Test the flow on https://sandbox.zenodo.org first (separate account/token).

What is in the dataset and what is not: per-patch statistics and per-bin spectra only — no image content, not invertible to pictures. The raw scans are not published.
