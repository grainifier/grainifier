# grainifier

Real film grain, measured from real scans, applied to digital images. Open source (MIT).

Most "film grain" tools either overlay a scanned grain texture (which ignores that grain
*is* the image) or synthesise a procedural pattern with hand-tuned parameters. grainifier
instead **measures** how a specific stock/developer/scanner combination actually behaves —
grain amplitude versus negative density, its 2-D noise power spectrum, its higher-order
statistics — and renders that behaviour onto a digital image in the domain where it
physically happens: negative density.

Status (2026-08): **profiler** and **renderer v0** work end to end. Bundled profiles: Ilford
HP5+ @ EI 1600 and Kodak Double-X 5222, each with a clean single-pass reference. B&W silver
stocks only; colour negative is a later project.

## Pipeline

```
digital image → place each tone at its negative density D (scan curve; or film curve for scene-linear input)
             → add grain with measured σ_D(D), skew(D) and NPS(D) → back to the positive → output
```

## Install

```
git clone https://github.com/grainifier/grainifier && cd grainifier
pip install -e .          # numpy + pillow; add [plots] for matplotlib
grainifier profiles       # lists the profiles bundled with the package
```

## Usage: rendering

```
grainifier render photo.jpg out.png --profile hp5-plus-ei1600-1pass
```

| option | default | meaning |
|---|---|---|
| `--profile` | — | bundled profile name (`grainifier profiles`) or path to a profile JSON |
| `--film-width-mm` | 36 | film frame width mapped onto the image's long side (36 = 35 mm full frame, 17 = half-frame, 56 = 6×6). This sets the physical grain size. |
| `--tone` | positive | `positive`: the input is a finished image; its tones are placed on the negative through the inverse scan curve (black point, white point, gamma). `scene`: the input is scene-linear (from a RAW); the film H&D curve and `--exposure` decide the density |
| `--print-gamma --black-point --white-point` | 1.25 / =fog / 2.5 | the scan curve: positive = ((D − D_bp)/(D_wp − D_bp))^γ. Measured on a VueScan/Negative Lab Pro workflow; higher γ = contrastier print |
| `--fog --dmax --gamma --mid-density` | 0.1 / 2.6 / 0.8 / 0.9 | placeholder logistic H&D curve, used with `--tone scene` |
| `--exposure` | 0 | stops of exposure offset (`--tone scene`) |
| `--grain-scale` | 1 | multiplier on σ_D (artistic control; 1 = as measured) |
| `--softness-um` | 0 | anisotropic Gaussian blur of the grain in µm (`0.5`, or `y x`); a 3-pass Coolscan scan ≈ `3.2 2.7` |
| `--negative` | off | write the negative's linear transmittance (16-bit) instead of a positive, for 100 % comparison with real scans |
| `--linear-input` | off | treat input as linear rather than sRGB |
| `--seed`, `--bits` | random, 16 | reproducibility; 8- or 16-bit output |

Input: PNG/JPEG/TIFF, 8- or 16-bit, colour or grey (colour is reduced to luminance — it is
a B&W film). Output: greyscale PNG/TIFF. A 24-MP image takes a few seconds (numpy FFT).

How it works: the image is mapped onto a film frame, each tone is placed at the negative
density it would have come from (through the scan curve, or the film curve for scene-linear
input), and grain is synthesised **in density space** at the profile's scanner pitch
(6.35 µm): white noise filtered by the measured 2-D noise-power-spectrum kernel, given the
measured amplitude σ_D(D) and skewness(D) pixel by pixel, then area-averaged onto the output
grid and brought back to the positive with the scan curve's slope, so the mean tone is
preserved exactly and highlights get gentler grain than midtones, as in real scans. A 24-MP
image on 35 mm therefore shows the grain
of a 4000-dpi scan; a half-frame gets coarser grain; a 1000-px web image gets almost none —
as a real scan downsized would. Closed-loop check: rendered flat fields re-measured with the
profiler reproduce σ_D within 1 %, skewness within 0.01 and the autocorrelation within a few
per cent (`eval/render/`). Against a real HP5@1600 scan, a rendered digital photo at the same
pixel pitch shows grain within 10–25 % at every tone from deep shadow to highlight
(`docs/research-notes.md`).

## Usage: profiling your own scans

Requirements: linear 16-bit scans of B&W negatives. VueScan RAW DNG (uncompressed, RGB or
grey) is what is supported today; other linear TIFF/DNG sources need a reader in
`grainifier/dng.py`. Processed, inverted or sharpened scans are useless for this — the
statistics must be measured on the transmittance the scanner actually saw. Prefer single-pass
scans (multi-pass averaging on a Coolscan blurs the grain by ~0.5 px).

```
grainifier frame scan.dng -o frame.npz          # one local frame (~1 s per 23 MP)

# a whole archive on another machine, streamed over ssh, one npz per frame, resumable
printf '%s\n' "/mnt/photos/2025/1022 - HP5 1600" "/mnt/photos/2025/1297 - HP5 1600" > rolls.txt
grainifier run --host nas --list rolls.txt --out data/frames/hp5-1600 --workers 3

grainifier aggregate data/frames/hp5-1600 -o my-hp5.json --plots plots/my-hp5 \
        --stock "Ilford HP5 Plus" --ei 1600 --developer "ID-11 1+1, 13 min" \
        [--software 9.8.46] [--rolls 1022 1297] [--dpi 4000]
grainifier render photo.jpg out.png --profile my-hp5.json
```

Per frame (`stats.py`): density D = −log10(T); 32-px patches, plane-detrended; per patch the
variance and R/G/B covariances (silver grain is common to the channels, scanner noise is
not — the "three-cornered hat" separates them), a low-frequency power fraction that rejects
patches containing image texture, skewness/kurtosis, and the green-channel power spectrum
accumulated per 0.1 D. `aggregate` pools the frames into σ_D(D), σ_scanner(D), 2-D NPS and
autocorrelation per density bin, Gaussianity checks, per-roll consistency and scan-sharpness
diagnostics, plus plots. Thresholds live in the aggregation step, so a profile can be rebuilt
from cached frames with different choices in seconds. Hundreds of ordinary pictures are
enough — flat fields are not required — but a calibration roll (`docs/calibration-roll.md`)
turns the placeholder curve into a measured one.

## Profiles

Bundled in `grainifier/profiles/` (JSON, ~0.5 MB each, self-describing):

| name | stock | EI | scans | frames | note |
|---|---|---|---|---|---|
| `hp5-plus-ei1600-1pass` | Ilford HP5 Plus | 1600 (+2) | single-pass | 114 | **reference** |
| `bwxx-1pass` | Kodak Double-X 5222 | 250 | single-pass | 124 | **reference** |
| `hp5-plus-ei1600` | Ilford HP5 Plus | 1600 (+2) | mixed 1/3-pass | 494 | softer grain |
| `bwxx` | Kodak Double-X 5222 | 250 | mixed 1/3-pass | 197 | softer grain |
| `bwxx-push2` | Kodak Double-X 5222 | 1000 (+2) | 3-pass | 37 | small sample |

All from the author's Leica M6 negatives, lab-developed, scanned on a Nikon Coolscan V ED
at 4000 dpi with VueScan (RAW DNG). Per-roll spread and the scan-sharpness caveat are in
`docs/research-notes.md`; plots for each profile are in `profiles/<name>/`.

Profile JSON layout: metadata (`stock`, `exposure_index`, `developer`, `scanner`, `dpi`,
`pixel_pitch_um`); `per_bin[]` with `d_mid`, `n_sel`, `sigma_d` (+ `_p10`, `_p25`,
`_mode`), `sigma_grain_common`, `sigma_scanner_g`, `corr_rg`, `skew`, `kurtosis`,
`autocorr_x/y[0..8]`; `nps_green.spectra` per bin (rfft2 layout, D² per pixel);
`per_roll{}`; `density_histogram`.

The per-frame caches (`data/frames/`, ~1 MB per frame, ~0.6 GB for the current profiles)
are the reproducibility layer: any profile can be rebuilt from them with different
thresholds, and they contain no image content — only patch statistics and spectra. They are
published as a Zenodo dataset (see `docs/zenodo.md`) rather than kept in git; the raw scans
stay private. More stocks (Tri-X, FP4+, Fomapan, the same stocks at box speed) follow as they
are profiled.

## Repository map

- `grainifier/` — the package: `dng.py` (VueScan RAW DNG reader), `stats.py` (per-frame
  statistics), `profile.py` (aggregation and plots), `render.py`, `cli.py`, `profiles/`.
- `profiles/<name>/` — plots for each bundled profile.
- `docs/` — research notes and results, plan for working with existing scans,
  calibration-roll protocol, Zenodo publishing notes; `docs/papers/` (gitignored) holds the
  PDFs.
- `eval/` — third-party implementations (gitignored clones), rendered comparisons, and
  `eval/README.md` with build notes and observations.
- `tools/` — one-off scripts (the original measurement script, dataset packer).
- `branding/` — icon.

## Built on

grainifier is implemented from the published descriptions of these works; please cite them
too if you use it in research (machine-readable list in `CITATION.cff`):

- A. Newson, J. Delon, B. Galerne. *A Stochastic Film Grain Model for Resolution-Independent Rendering.* Computer Graphics Forum 36(8), 2017. doi:10.1111/cgf.13159
- A. Newson, N. Faraj, J. Delon, B. Galerne. *Realistic Film Grain Rendering.* IPOL 7, 2017. doi:10.5201/ipol.2017.192
- K. Zhang, J. Wang, D. Tian, T. N. Pappas. *Film Grain Rendering and Parameter Estimation.* ACM TOG 42(4), 2023. doi:10.1145/3592127
- G. Lesné, Y. Gousseau, S. Ladjal, A. Newson. *Neural Film Grain Rendering.* Computer Graphics Forum 44, 2025. doi:10.1111/cgf.70076
- I. Stephenson, A. Saunders. *Simulating Film Grain using the Noise-Power Spectrum.* TPCG 2007.
- A. Norkin, N. Birkbeck. *Film Grain Synthesis for AV1 Video Codec.* DCC 2018.
- R. Selwyn's granularity law and the Kodak/Ilford RMS-granularity conventions for sanity checks.

## License

MIT — see `LICENSE`. Profiles and the published frame-statistics dataset: CC BY 4.0.
