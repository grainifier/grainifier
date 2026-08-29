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
