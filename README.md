# grainifier

Real film grain, measured from real scans, applied to digital images. Open source (MIT).

Most "film grain" tools either overlay a scanned grain texture (which ignores that grain
*is* the image) or synthesise a procedural pattern with hand-tuned parameters. grainifier
instead **measures** how a specific stock/developer/scanner combination actually behaves —
grain amplitude versus negative density, its 2-D noise power spectrum, its higher-order
statistics — and renders that behaviour onto a digital image in the domain where it
physically happens: negative density.

Status (2026-08): the **profiler** exists and is being run on the author's Ilford HP5+ @ EI 1600
scans (Nikon Coolscan V, 4000 dpi, VueScan RAW DNG). The renderer is next. B&W silver
stocks only; colour negative is a later project.

## Pipeline

```
digital image → linear scene → stock characteristic curve (incl. push) → negative density D
             → add grain with measured σ_D(D) and NPS(D) → invert → output
```

## Profiler

```
pip install -e .[plots]
grainifier frame  scan.dng -o frame.npz                      # one local frame
grainifier run    --host nas --list rolls.txt --out data/frames/hp5-1600   # stream a whole archive over ssh
grainifier aggregate data/frames/hp5-1600 -o profiles/hp5-1600.json --plots profiles/hp5-1600 \
          --stock "Ilford HP5 Plus" --ei 1600
```

Per frame, in density D = −log10(T): 32-px patches are plane-detrended; per patch we keep
variance and cross-channel covariances (silver grain is common to R/G/B, scanner noise is
not — the "three-cornered hat" separates them), a low-frequency power fraction to reject
textured patches, skewness/kurtosis, and the green-channel power spectrum accumulated per
0.1-D bin. Aggregation produces a JSON profile with σ_D(D), σ_scanner(D), 2-D NPS and
autocorrelation per density, Gaussianity checks, and per-roll consistency.

See `docs/` for the research notes, the plan for working with existing scans, and the
calibration-roll protocol. `eval/` holds third-party implementations used for comparison
(their own licences; nothing from them is used in grainifier's code).

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

MIT — see `LICENSE`.
