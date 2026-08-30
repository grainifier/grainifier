#!/usr/bin/env python3
"""Pack the per-frame statistics caches into a Zenodo-ready dataset archive.

    python tools/make_dataset.py [--frames data/frames] [--out dist] [--version 2026.08]

Produces dist/grainifier-frame-stats-<version>.tar.gz containing:
    frames/<profile>/<roll>/<frame>.npz      per-frame statistics (no image content)
    profiles/*.json                          the aggregated profiles built from them
    README.md, LICENSE (CC BY 4.0), MANIFEST.json (sha256 per file), zenodo-metadata.json
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
import time
from pathlib import Path

import numpy as np

PER_PATCH = ("mean_d", "mean_rgb", "var", "cov", "lowfrac", "skew", "kurt", "sel")


def anonymise_frame(data: bytes, seed: int) -> bytes:
    """Shuffle the per-patch arrays (same permutation for all) so the file no longer holds a
    thumbnail of the negative. Aggregation never uses patch position, so profiles are unchanged."""
    with np.load(io.BytesIO(data), allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    n = len(d["mean_d"])
    perm = np.random.default_rng(seed).permutation(n)
    for k in PER_PATCH:
        if k in d:
            d[k] = d[k][perm]
    buf = io.BytesIO()
    np.savez_compressed(buf, **d)
    return buf.getvalue()


def public_roll_name(roll: str, profile: str) -> str:
    """'1022 - Ilford HP5 Push 1600 Simon Yuna' -> '1022-hp5-1600' (roll number + profile only)."""
    m = re.match(r"\s*(\d{4})", roll)
    return f"{m.group(1)}-{profile}" if m else profile

ROOT = Path(__file__).resolve().parent.parent

DATASET_README = """# grainifier frame statistics dataset

Per-frame grain statistics measured from linear film scans with `grainifier frame`
(https://github.com/grainifier/grainifier), and the aggregated grain profiles built from them.

Each `frames/<profile>/<roll>/<frame>.npz` holds, for one 35 mm negative scanned on a Nikon
Coolscan V ED at 4000 dpi (VueScan RAW DNG, linear transmittance): per 32×32-px patch the
mean negative density, plane-detrended variance per channel, R/G/B covariances, low-frequency
power fraction, skewness and kurtosis; plus the green-channel power spectrum summed per
0.1-D density bin, a density histogram, scanner metadata and the patch-selection threshold.
The per-patch arrays are stored in a shuffled order (positions discarded), so the files hold
no image content and cannot be turned back into a picture; rolls are identified by number and
stock only.

Rebuild a profile: `grainifier aggregate frames/<profile> -o out.json --plots plots/`.
Field definitions: `grainifier/stats.py` and `grainifier/profile.py` in the repository.

Profiles (aggregated JSON) are in `profiles/`. Stocks, exposure indices, development and
scanning details are in each profile's metadata and in the repository's `docs/`.

License: CC BY 4.0. Please cite the dataset DOI and the software; the software's
`CITATION.cff` lists the papers it builds on.
"""

CC_BY = """Creative Commons Attribution 4.0 International (CC BY 4.0)
https://creativecommons.org/licenses/by/4.0/legalcode
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=str(ROOT / "data/frames"))
    ap.add_argument("--profiles", default=str(ROOT / "grainifier/profiles"))
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--version", default=time.strftime("%Y.%m"))
    a = ap.parse_args()

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"grainifier-frame-stats-{a.version}.tar.gz"
    manifest = {}
    n = 0

    def add_bytes(tf: tarfile.TarFile, name: str, data: bytes):
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mtime = int(time.time())
        tf.addfile(info, io.BytesIO(data))
        manifest[name] = hashlib.sha256(data).hexdigest()

    with tarfile.open(archive, "w:gz", compresslevel=6) as tf:
        top = f"grainifier-frame-stats-{a.version}"
        for f in sorted(Path(a.frames).rglob("*.npz")):
            rel = f.relative_to(a.frames)
            profile, roll = rel.parts[0], rel.parts[1]
            public = f"{top}/frames/{profile}/{public_roll_name(roll, profile)}/{f.name}"
            data = anonymise_frame(f.read_bytes(), seed=int(hashlib.sha256(public.encode()).hexdigest()[:8], 16))
            add_bytes(tf, public, data)
            n += 1
        for f in sorted(Path(a.profiles).glob("*.json")):
            add_bytes(tf, f"{top}/profiles/{f.name}", f.read_bytes())
        add_bytes(tf, f"{top}/README.md", DATASET_README.encode())
        add_bytes(tf, f"{top}/LICENSE", CC_BY.encode())
        meta = {
            "title": f"grainifier frame statistics dataset {a.version}",
            "upload_type": "dataset",
            "description": DATASET_README.split("\n\n", 1)[1].replace("\n", " "),
            "creators": [{"name": "Fyhr, Pontus", "orcid": "0009-0009-8733-214X"}],
            "license": "CC-BY-4.0",
            "access_right": "open",
            "keywords": ["film grain", "photographic emulsion", "noise power spectrum", "Ilford HP5 Plus", "Kodak Double-X 5222", "film scanning"],
            "related_identifiers": [
                {"identifier": "https://github.com/grainifier/grainifier", "relation": "isSupplementTo", "scheme": "url"}
            ],
            "version": a.version,
            "n_frames": n,
        }
        add_bytes(tf, f"{top}/zenodo-metadata.json", json.dumps(meta, indent=1).encode())
        add_bytes(tf, f"{top}/MANIFEST.json", json.dumps(manifest, indent=1).encode())
    (out_dir / f"{archive.stem.replace('.tar', '')}.zenodo.json").write_text(json.dumps(meta, indent=1))
    print(f"{archive}: {n} frames, {archive.stat().st_size / 1e6:.0f} MB")
    print(f"sha256 {hashlib.sha256(archive.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
