# grainifier for darktable

A darktable image-operation module (`iop`) that applies grainifier's measured film grain inside
darktable's pixelpipe — live preview, zoom-consistent, non-destructive, exported at full
resolution. Same model as the Python renderer:

1. the pixel's luminance is a finished positive → placed on the negative through the scan curve
   `D = bp + (wp − bp)·L^(1/γ)`
2. grain in density: `ΔD = σ_D(D)·skew_D(n)`, `n` = hashed white noise on a lattice at the
   scanner's pitch **in film micrometres** ⊛ the measured NPS kernel — so the grain has a physical
   size set by *film width*, independent of zoom or export size
3. back to the positive with the same curve, applied to all channels (a colour image gets B&W-film
   luminance grain; convert to monochrome before it for the real thing)

Profiles are baked into `grainifier_profiles.h` by `gen_profiles_header.py` from the JSON
profiles (σ_D and skew on a 0.05-D grid, the 15×15 kernel at 6.35 µm, and decimated kernels for
zoomed-out views whose variance matches the box-averaged fine field).

## Files

- `grainifier.c` — the module (GPL-3+, like all darktable modules)
- `grainifier_profiles.h` — generated; `python darktable/gen_profiles_header.py grainifier/profiles/*.json -o darktable/grainifier_profiles.h`
- `build.sh` — copies both into a darktable source tree, registers the module (`src/iop/CMakeLists.txt`, pipeline position right after *grain* in `src/common/iop_order.c`) and builds

## Build

Homebrew deps on macOS: `brew install gtk+3 lensfun exiv2 pugixml json-glib libsoup lua curl iso-codes intltool ninja perl jpeg-xl desktop-file-utils potrace libomp` (plus the usual image libraries). On Debian/Ubuntu `apt build-dep darktable` covers it.

```
git clone --depth 1 --branch release-5.6.1 --recurse-submodules https://github.com/darktable-org/darktable
darktable/build.sh ./darktable ./darktable/build       # macOS with Homebrew deps, or Linux
./darktable/build/bin/darktable                        # run the built darktable; module is under "effects"
```

darktable modules must be built inside darktable's own tree (they link against its internal
API, which has no stable ABI), so the module cannot be dropped into a packaged darktable.
Upstreaming it is the way to reach users; the module is written to darktable's conventions
(introspection-annotated params, bauhaus GUI, OpenMP) with that in mind.

## Parameters

| parameter | default | |
|---|---|---|
| film | HP5+ @1600 | measured profile |
| film width | 36 mm | width of film the long side spans (24 = half frame, 56 = 6×6) |
| grain amount | 1.0 | multiplier on the measured σ_D |
| black point / white point / positive gamma | 0.03 / 2.6 / 1.45 | scan curve (VueScan); Lightroom/NLP look ≈ 0.2 / 2.6 / 2.2 |
| seed | 0 | pattern |

## Status

Branch `darktable`. Builds and runs against darktable 5.6.1 (macOS/Homebrew). Validated
headlessly with `darktable-cli`: a 24-MP export through the module matches the Python renderer's
output within 1–2 % in grain σ at every tone (`docs/research-notes.md`). Not yet: OpenCL path,
per-density NPS (one kernel per profile), softness control, upstream PR.
