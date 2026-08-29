# What we can do with the existing scans (before any calibration roll)

Scope decision (2026-08-29): **B&W silver only** for now. Colour (Portra/Gold/Vision3) is deferred — dye clouds per layer, inter-layer crosstalk and scanner channel mixing make it a separate project.

The calibration roll (see `calibration-roll.md`) has a ~1 month turnaround. Everything below works on the ~960 raw B&W DNGs already on diskdatorn and gets us a usable v0 profile for HP5+@1600, HP5+ (+1/+2), BWXX, Tri-X and FP4+.

## 1. Grain amplitude vs density — σ_D(D) — from natural images
This is the classic "noise level function from a single image" problem (Liu, Freeman, Szeliski & Kang 2008; Chen, Zhu & Heng ICCV 2015 PCA-based estimator). We don't need flat fields: with hundreds of frames per stock we can
- work in density D = −log10(T) from the linear VueScan DNG (green channel, or the R/G/B mean);
- tile into small patches (16–32 px), remove a local plane (or a low-order polynomial), and keep only *weakly textured* patches by a gradient/eigenvalue criterion (not by "lowest σ", which biases σ downward);
- bin by patch mean density (0.05 D bins) and take a robust estimate (median of the weak-texture patches) per bin;
- pool across all frames of one stock+push+developer (folder names carry push; home-dev rolls are labelled).

Sanity checks: Selwyn-scaled σ_D at 48 µm should land near published RMS granularity (HP5+ ≈ 10–12, Double-X 5222 = 16, ×1000).

## 2. Scanner noise separation — three substitutes for the calibration roll
1. **Cross-channel covariance.** Silver grain is common to R, G and B (measured correlation 0.92–0.96 in midtones); LS-50 CCD/readout noise is channel-independent. So `cov(D_R, D_G)` in a patch estimates grain variance, and `var(D_G) − cov(D_R, D_G)` estimates scanner noise. Gives σ_scanner(D) for free from every frame.
2. **Re-scan an existing negative N times.** We own the scanner and the negatives: scan 3–4 chosen frames (one thin, one normal, one dense per stock) 8× each with identical settings. Grain is fixed between scans, scanner noise is not → the per-pixel variance across scans is scanner noise exactly; the mean across scans is a near-noise-free grain image for spectrum estimation. An afternoon, not a month.
3. **Rebate / sprocket area / blown highlights.** Unexposed film edge (base+fog, Dmin) and fully blown areas (Dmax) are uniform fields already present in many scans — they give the scanner noise floor and the grain at the two density extremes.

## 3. Grain spatial structure — power spectrum / autocorrelation per density
From the same weak-texture patches (or the re-scan means): 2-D autocorrelation out to ~8 px, averaged per density bin. Preliminary numbers: lag-1 ≈ 0.7–0.8, lag-2 ≈ 0.2–0.45, ~0 by lag 4, anisotropic (scanner MTF). Store the 2-D NPS per density bin rather than assuming isotropy. Also collect skewness/kurtosis per bin — if they stay ≈ 0/3, correlated-Gaussian synthesis is enough and no learned generator is needed.

## 4. Tone curve — use the datasheet as a prior
The scans can't give density-vs-exposure without a known target, but the renderer needs it only to map a digital image onto the negative density axis, and the user's exposure choice is creative anyway. Use published characteristic curves (Ilford HP5+ datasheet incl. push in ID-11/Microphen; Kodak 5222 datasheet in D-96/D-76) as the v0 curve; refine with the calibration roll later. The scan histograms give the *density range actually used* per stock/push, which constrains where the curve should place typical scenes.

## 5. Parametric fit (optional, physically meaningful controls)
Fit the Zhang/Wang/Tian/Pappas 2023 closed-form Boolean-model statistics (grain radius, density) to the measured σ_D(D)+NPS per stock. Gives "grain radius in µm" as a user control and a bridge to the Newson model at high zoom.

## 6. Output of this phase
`profiles/<stock>-<push>-<dev>.json`: σ_D(D) table, σ_scanner(D) table, 2-D NPS per density bin, tone curve reference, scanner metadata (LS-50, 4000 dpi, 6.35 µm/px). The renderer consumes only this file.

## Deliverables in order
1. `grainifier profile` over all raw DNGs of one stock (start: HP5+@1600, 494 frames) → JSON + plots.
2. Re-scan experiment (item 2.2) on 3 frames → validate scanner-noise split.
3. `grainifier render`: image → linear → tone curve → density → spectrally-shaped Gaussian noise with σ_D(D) → invert → 16-bit output; grain size in µm, scaled by output pixel pitch/format.
4. Side-by-side with real scans at 100% and with the Newson reference (eval/).
