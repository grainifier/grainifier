# Calibration roll plan (one per stock × push × developer)

Purpose: measure (a) the characteristic curve D(log E) for *your* process and (b) clean grain statistics at known densities, and (c) the scanner's noise, all from one roll.

## Shooting (checklist)
- Target: matte 18 % grey card, **over-filling the frame** (50 mm at ~0.7–1 m on an A4 card, edges well outside the finder). Slightly **defocused** (focus at ~2 m) so paper texture doesn't register.
- Light: **overcast sky / open shade outdoors**, card ~45° to the sky, no glare, no direct sun. No LED panels unless known flicker-free (PWM + fast shutter = random exposure errors). Meter at start and end of the sequence; redo if it drifted.
- Aperture f/5.6–f/8 for the bracket (vignetting ≤ ~0.2 stop; the curve is fitted on the central ~60 % of the frame).
- Sequence per roll (~20 frames): meter the card ("0"); **shutter bracket in full stops −4…+4 at fixed aperture** (9 frames); repeat with the aperture closed ½ stop (9 frames) → ½-stop spacing. All exposures ≤ 1 s (reciprocity). **1 frame ≈ +8 stops** (Dmax). **1 frame slanted edge** (black card on the grey card, edge tilted ~5°, in focus, f/5.6) → whole-chain MTF, separates scanner MTF from grain. Dmin (fog) comes free from the unexposed leader and the gaps between frames. Remaining ~16 frames: ordinary pictures.
- Log every frame: shutter, aperture, meter reading, light. Develop **exactly as usual** (same lab / push order as the archive) so the curve describes the rolls already profiled.
- Rolls (ordered 2026-08-31, 4× HP5+ 135-36):
  | roll | EI / lab order | purpose |
  |---|---|---|
  | 1 | HP5+ @1600, +2 push, same lab as the archive | curve + clean σ_D(D) for the shipped profile |
  | 2 | HP5+ @1600, identical, shot on another day | roll-to-roll / lab spread, insurance for roll 1 |
  | 3 | HP5+ @400, normal | box-speed profile (none in the archive) |
  | 4 | HP5+ @3200, +3 push | push axis 400 / 1600 / 3200 for interpolation |
  | – | BWXX @250 from the bulk roll | curve for the BWXX profiles |
  Colour deferred (dye clouds break the R/G/B common-grain scanner-noise split; would need the 8× re-scan variance instead).

## Scanning (Coolscan V / VueScan)
- **Single pass**, 4000 dpi, 16-bit RAW DNG, no ICE (silver blocks IR anyway), no sharpening, no multi-exposure. **Lock exposure** on the mid-grey frame (VueScan: preview → *Lock exposure* → *Lock film base color*) and scan every frame of the roll with those locks — with auto-exposure the densities of different frames are not comparable.
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
