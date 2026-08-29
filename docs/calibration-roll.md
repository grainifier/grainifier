# Calibration roll plan (one per stock × push × developer)

Purpose: measure (a) the characteristic curve D(log E) for *your* process and (b) clean grain statistics at known densities, and (c) the scanner's noise, all from one roll.

## Shooting
- Camera: M6, same lens for all rolls, aperture f/5.6–8 (avoid vignetting; keep the card away from frame edges or note it).
- Target: an 18 % grey card filling the frame, evenly lit (overcast sky or a wall in shade), defocused slightly so card texture doesn't register.
- Bracket in ⅓-stop steps from −5 to +5 stops around metered exposure (≈ 31 frames). Use shutter speed for the bracket where possible (reciprocity is negligible in this range); note each frame's speed/aperture on paper.
- Leave 2 frames fully unexposed (lens cap) → base+fog (Dmin); shoot 1 frame at +8 stops (or the sun) → Dmax.
- Optional but very useful: a Stouffer 21-step transmission wedge contact-printed/photographed on 2 frames gives an independent D(log E) check.
- Repeat per combination you actually use: HP5+ @400 / @1600 (+2) / +1, BWXX @250 / +2, Tri-X, FP4+ home-dev. Log the developer, dilution, time, temperature, agitation.

## Scanning (Coolscan V / VueScan)
- Same settings for every calibration frame *and* for the frames you'll later profile: 4000 dpi, 16-bit, RAW DNG output, no ICE (B&W silver blocks IR), no sharpening, no multi-exposure, fixed exposure/analog gain (lock it — VueScan auto-exposure changes the effective transmittance scale between frames).
- Scan each of ~6 representative density steps 8× (multi-pass by re-running the scan, not VueScan's "multi-sample" averaging) → scanner noise = variance across passes; grain = variance within the averaged image.
- Also scan a blank (no film) frame → scanner noise at T = 1.

## What we derive
- D(log E) per process → the tone curve used by the renderer.
- σ_D(D), full 2-D noise-power spectrum per D, skew/kurtosis per D, with scanner noise removed exactly.
- Absolute granularity check against datasheet RMS values.

## Re-scan check (planned with the next roll)
Pick one frame with a large smooth midtone area (sky/wall, D≈1). Scan it, without moving the strip between scans:
1. 1 pass, RAW DNG — `rescan_1pass_a.dng`
2. 1 pass again — `rescan_1pass_b.dng` (pass-to-pass difference = scanner noise + jitter, directly)
3. 3 passes — `rescan_3pass.dng`
Same VueScan exposure lock, no ICE/sharpening. Analysis: `grainifier frame` on each, then ratio of the green NPS at D 0.8–1.3 (3-pass ÷ 1-pass) → |MTF_jitter|², to be compared with the across-roll fit σ ≈ 0.42/0.50 px; a−b difference image → per-pixel scanner noise and the registration error between passes.
