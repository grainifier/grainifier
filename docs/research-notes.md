# Grainifier — research notes (2026-08-29)

## Literature

| Work | What it is | Takeaway for us |
|---|---|---|
| Newson, Delon, Galerne — *A Stochastic Film Grain Model for Resolution-Independent Rendering*, CGF 2017; Newson, Faraj, Delon, Galerne — *Realistic Film Grain Rendering*, IPOL 2017 ([pdf](https://www.lirmm.fr/~nfaraj/publications/film_grain_ipol/2017_Newson_film_grain.pdf)) | Inhomogeneous Boolean model: Poisson disks of radius r (const or log-normal), density λ(y)=log(1/(1−ũ))/E[πr²] so coverage matches grey level; output = Gaussian-filtered (σ=0.8 px) binary field, evaluated by Monte Carlo (N≈800). Params: µr, σr/µr, zoom, σ_filter. | The physically-motivated reference model. Slow (40 s / 512² CPU). Limits stated in the paper: dark areas look wrong (few grains), can't do "white-grain" stocks like Delta 3200, grains are B&W only (colour = per channel). Code is **GPLv3** ([CPU](https://github.com/alasdairnewson/film_grain_rendering), [GPU](https://github.com/alasdairnewson/film_grain_rendering_gpu)) — re-implement from the paper rather than derive. |
| Zhang, Wang, Tian, Pappas — *Film Grain Rendering and Parameter Estimation*, ACM TOG / SIGGRAPH 2023 ([doi](https://dl.acm.org/doi/10.1145/3592127)) | Closed-form mean/covariance of the filtered Boolean model → render as correlated Gaussian noise, 10⁶× faster; **formulas to estimate µr, λ from scanned film grain**. Valid "when individual grains are not visible". | This is the regime our 4000-dpi scans are in. Direct template for "fit model parameters to real scans". |
| Lesné, Gousseau, Ladjal, Newson — *Neural Film Grain Rendering*, CGF 2025 ([HAL](https://hal.science/hal-04667141), [code](https://github.com/Gwilherm-LESNE/Neural_Film_Grain_Rendering)) | Small CNN + texture-aware (VGG/Gram) loss, trained on **synthetic** pairs made with Newson's CUDA renderer; grain-size estimator net. Academic-use-only license. | Shows a light CNN can imitate the grain texture; nobody has trained it on real scans. |
| Stephenson & Saunders — *Simulating Film Grain using the Noise-Power Spectrum*, EG UK 2007 ([pdf](https://diglib.eg.org/bitstreams/372ec0ad-ff80-497b-81b0-2dd8d7021e48/download)) | Measure Wiener/NPS of real film at several densities; synthesise by spectrally shaping noise. | Simplest data-driven approach; matches what we measured. |
| AV1 film grain synthesis (Norkin & Birkbeck, DCC 2018; [ref impl](https://github.com/ncherel/film-grain-synthesis); SVT-AV1 estimator) | Auto-regressive noise model, strength as piecewise-linear function of intensity, parameters estimated from (noisy − denoised). | Cheap AR-model alternative to NPS; estimator design is reusable. |
| InterDigital: DeepFilmGrain (TIP 2023), Style-FG (TOMM 2025), FGA-NN (2025), FilmGrainStyle740k dataset | cGAN / style-encoder grain synthesis for codecs. Dataset grain is **synthetic** (Nuke plug-in), non-commercial license. | Not real film; architecture ideas only. |
| Film-GAN (Gong et al., NCAA 2023) | GAN digital→film style incl. Gold 200, Portra 160, HP5. Closed. | Evidence people try end-to-end; no reusable data. |
| Selwyn granularity / RMS granularity (Kodak, 48 µm aperture) | σ_D·√A ≈ const; published: HP5+ ≈ 10–12, Double-X 5222 = 16 (×1000) | Sanity check for measured σ_D(D). |

## Existing implementations
- Newson CPU/GPU (GPLv3), [AviSynthFilmGrain](https://github.com/MvonSchantz/AviSynthFilmGrain), [filmgrain-simplified](https://github.com/kanzwataru/filmgrain-simplified) (C/SDL3-GPU/HLSL)
- [autochrome](https://github.com/beatreichenbach/autochrome) — Python, MIT, Newson-based + spectral film model, early stage
- darktable / RawTherapee grain modules — procedural (simplex) noise on L; G'MIC film emulation = colour CLUTs only
- Commercial: Dehancer (procedural, physically-motivated, density-dependent per tonal range, negative vs positive modes), DxO FilmPack (scanned grain samples), Filmbox, FilmConvert Nitrate, Emul8, GrainX overlays

## Our data (diskdatorn:/mnt/st3raid/Pictures)
Nikon Coolscan V ED (LS-50) @ 4000 dpi (6.35 µm/px), VueScan RAW DNG = uncompressed 16-bit linear transmittance.
Raw DNG frame counts: HP5+ 494 (mostly @1600), BWXX 234, FP4+ 151, Tri-X 79; colour: Gold 265, Portra 191, Ektachrome 77, Vision3 41. Fomapan/XP2 and some 2025 HP5 rolls only have 8-bit processed TIFs (not usable).

## Quick measurement (tools/grainstats.py, 24×24 px patches, plane-detrended, density = −log10 T)
Grain σ_D at 10th percentile (≈ flat patches), BWXX 1023_0001 / HP5@1600 raw2545-0001:

| D | BWXX | HP5@1600 |
|---|---|---|
| 0.0–0.2 | 0.049 | 0.036 |
| 0.8–1.0 | 0.119 | 0.045 |
| 1.4–1.6 | 0.112 | 0.088 |
| 1.6–1.8 | 0.135 | 0.098 |
| 2.2–2.4 | 0.131 | 0.075 |
| 2.8–3.0 | 0.137 (median 0.28 → scanner noise) | 0.065 |

- Autocorrelation of grain residual: lag1 ≈ 0.68–0.79, lag2 ≈ 0.18–0.44, ≈0 by lag 4 → grain clumps span ~2–4 px (13–25 µm); anisotropic (scanner MTF).
- R/G/B correlation of the residual in flat midtones 0.92–0.96 → the common component is silver grain, the rest is scanner noise. Use this to separate the two.
- Skewness ≈ 0 → Gaussian regime (Zhang/Pappas), not the "individual grains" regime.

## Results — HP5+ @ EI 1600 profile (2026-08-29, `profiles/hp5-plus-ei1600.json`)

494 frames, 13 rolls, 10.4 M patches (32 px), 3.1 M weak-texture patches. Nikon LS-50, 4000 dpi.

| D | σ_D / px (median) | σ_D 10th pct | grain (R/G/B common) | scanner (G) | ac lag1 x / y | skew | kurt |
|---|---|---|---|---|---|---|---|
| 0.05 | 0.048 | 0.002 | 0.050 | 0 | 0.61 / 0.48 | +0.93 | 3.85 |
| 0.55 | 0.082 | 0.057 | 0.083 | 0 | 0.59 / 0.41 | +0.14 | 2.93 |
| 1.05 | 0.089 | 0.062 | 0.091 | 0 | 0.61 / 0.42 | +0.02 | 2.91 |
| 1.55 | 0.095 | 0.064 | 0.098 | 0 | 0.62 / 0.45 | −0.08 | 2.93 |
| 2.05 | 0.097 | 0.070 | 0.100 | 0 | 0.64 / 0.45 | −0.26 | 3.02 |
| 2.45 | 0.065 | 0.033 | 0.062 | 0.030 | 0.60 / 0.39 | −0.24 | 3.21 |
| 2.85 | 0.067 | 0.041 | 0.019 | 0.063 | 0.31 / 0.05 | +0.41 | 3.23 |

Findings
- **σ_D(D)**: 0.048 at base+fog, rising to ≈0.08 by D 0.5 and a broad plateau ≈0.09–0.10 for D 1.0–2.3. Above D≈2.4 the LS-50 hits its noise floor: channel correlation collapses (1.0 → 0), the common-mode "grain" estimate falls and the channel-independent "scanner" term rises — the profile is trustworthy for D ≤ 2.3, which covers 95 % of the patches on these negatives anyway.
- **Scanner noise is negligible below D≈2.3** — the R/G/B residuals are >0.98 correlated, so at 4000 dpi what the scan shows in the midtones is silver, not CCD noise. (Caveat: mechanical/banding noise common to all channels would be counted as grain; the re-scan experiment in `plan-existing-data.md` §2.2 tests that.)
- **Skewness flips sign at D≈1.1**: +0.9 at Dmin (a few dark specks on clear film) → 0 → −0.34 at D≈2.3 (a few clear holes in dense silver). That is exactly what a Boolean model predicts as coverage crosses 50 %, and it is measurable in real scans at 6.35 µm/px. Kurtosis ≈ 2.9–3.0 throughout: Gaussian marginals are a fine approximation, but the skew should be reproduced by the renderer (it is what makes shadows and highlights look different).
- **Correlation structure**: lag-1 ≈ 0.60 (x) / 0.43 (y), lag-2 ≈ 0.13 / 0.10, ~0 by lag 4; correlation area ≈ 3.7–4.1 px² (|lag| ≤ 6). Anisotropic and nearly constant with density → one 2-D NPS shape scaled by σ_D(D) would already be a good renderer; the profile stores the full per-bin NPS regardless.
- **Selwyn-scaled granularity** (σ at 48 µm circular aperture): 0.025–0.029 for D 1–2 → "RMS granularity" ≈ 25–28. Tri-X 400 is 17 at box speed; HP5+ pushed two stops being ~1.5× coarser is plausible. Absolute calibration against a microdensitometer needs the calibration roll (specular scanner geometry / Callier effect may inflate the number).
- **Roll-to-roll spread is real and large**: σ_D at D=1.0 spans 0.067–0.124 (1.8×). The grainiest rolls (1022, 1297, 8912) also have the highest base+fog (0.14–0.15 vs 0.04–0.07), i.e. they were developed harder. So "HP5+ @1600" is a family of profiles keyed by development, not one number; the profile should carry a spread (per-roll σ scale) that the renderer exposes as a "push/development" control. Roll 2094 was scanned greyscale (1 channel) and is the least grainy — treat as suspect until re-scanned RGB.
- Density histogram of the whole HP5@1600 archive peaks at D 0.1–0.4 (thin, shadow-heavy negatives — pushed film) with a long tail to 2.5.

Next: renderer (`grainifier render`) driven by this JSON; BWXX / Tri-X / FP4+ profiles with the same tool (`data/*-rolls.txt`); re-scan experiment to validate the scanner split.

## Results — BWXX (Kodak Double-X 5222) profiles and the scan-sharpness finding (2026-08-29)

`profiles/bwxx.json`: 197 frames, 6 rolls (normal dev). `profiles/bwxx-push2.json`: 37 frames, 1 roll (+2).
Pooled BWXX σ_D ≈ 0.082–0.095 for D 0.5–2.1 (≈ HP5@1600), scanner term small (0.01) up to D 2, noise floor from D≈2.5. Push-2 roll: 0.10–0.115, skew −0.29 at D 2 — grainier, as expected.

**Per-roll spread is mostly scan sharpness, not development.** Per-roll autocorrelation at D≈1:

| scanned with | rolls | lag-1 y | corr. area px² | σ_D/px @1.0 | σ·√A |
|---|---|---|---|---|---|
| VueScan 9.8.46 (spring–summer 2025) | HP5 1022, 1297, 8912; BWXX 1023, 1024, 8910, 8911 | 0.26–0.35 | 1.9–2.8 | 0.087–0.135 | HP5 0.18–0.22, BWXX 0.14–0.15 (1023: 0.21) |
| VueScan 9.8.49–9.8.56 (autumn 2025 →) | all later rolls | 0.41–0.63 | 3.5–7.6 | 0.057–0.099 | HP5 0.18–0.22, BWXX 0.135–0.14 |

The later scans are blurrier (higher, more isotropic correlation, lower per-pixel σ), and σ·√(correlation area) — roughly the density fluctuation seen through a larger aperture — is constant per stock across the two eras to within about ±20 % (HP5: 0.18–0.19 for 9 of 13 rolls; 2037/2094 low at 0.13–0.14, 2095/2096 high at 0.22–0.23 — residual differences that may well be development). Cause is on the scanner side (focus / film flatness / a VueScan default such as fine mode or multi-sampling), to be identified by re-scanning one 2025 negative with the current setup. BWXX roll 1023 is the one genuine development outlier (σ√A 0.21 vs 0.14, and the highest base+fog). The aggregator now reports `corr_area_px2@1.0` and `sigma_sqrt_area@1.0` per roll.

Consequences for the renderer: per-pixel σ_D is *not* a stock property — the NPS is. Store and render the full 2-D NPS; treat the scanner MTF as a separate, measurable factor (the sharp 9.8.46 sessions are the better reference for the emulsion itself), and expose "scan softness" as its own control rather than folding it into the grain amplitude.

### Cause confirmed: VueScan multi-pass (3 passes) from autumn 2025
The user switched from 1 to 3 passes (plus the raw+inv workflow) around then. Averaging passes cancels channel-independent CCD noise — which we already found negligible below D≈2.3 — but the LS-50 does not reposition to sub-pixel accuracy, so the average is a registration blur. Ratio of 3-pass to 1-pass HP5 spectra at D 0.8–1.3 (= |MTF_jitter|²): ≈1.0 at DC, 0.17 at Nyquist along y vs 0.72 along x. Separable-Gaussian fit: σ_x ≈ 0.42 px, σ_y ≈ 0.50 px (6.35 µm/px), i.e. a per-pass jitter of ≈0.6 px ≈ 4 µm along the transport axis.

Decisions
- **Profile and calibrate from single-pass scans.** Multi-pass only pays above D≈2.3 and costs grain resolution everywhere.
- The 9.8.46 single-pass rolls (HP5: 1022, 1297, 8912; BWXX: 1023, 1024, 8910, 8911) are the reference for the emulsion NPS; 3-pass rolls can be used after dividing their NPS by the fitted |MTF_jitter|², or kept as a "softer scan" variant.
- The renderer gets an explicit scan-softness (Gaussian σ in µm, anisotropic) parameter; the jitter above is simply one preset of it.
- Re-scan check still worth doing once: same negative, 1 pass vs 3 passes, to confirm the MTF fit directly rather than across different rolls.
