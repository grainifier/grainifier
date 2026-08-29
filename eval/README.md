# eval/ — third-party implementations for comparison

Everything under `eval/repos/` is **third-party code with its own license**; nothing here may be copied into grainifier's own source. It exists only to render reference outputs to compare against.

| Repo | License | Builds/runs here (macOS arm64)? | Notes |
|---|---|---|---|
| `film_grain_rendering` (Newson et al., IPOL 2017, CPU) | GPL v3+ | **Yes** — `make OMP=1 CXX=clang++ CXXFLAGS="-std=c++11 -Wall -Xpreprocessor -fopenmp -I/opt/homebrew/opt/libomp/include" INCPATH="-Isrc -I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib -L/opt/homebrew/opt/libomp/lib -lpng -ltiff -lomp"` | Reads PNG (RGB); its TIFF reader rejects ImageMagick TIFFs. 512×512, N=800: ~2 s with OpenMP. Options: `-r` radius (input px), `-sigmaR`, `-NmonteCarlo`, `-zoom`, `-sigmaFilter`, `-color 0/1`. |
| `film_grain_rendering_gpu` (same, CUDA) | GPL v3+ | No — needs CUDA; no NVIDIA GPU on this Mac or on diskdatorn | Also needs GLUT/GL. |
| `AviSynthFilmGrain` | not stated (copyright M. von Schantz) | No — Windows/AviSynth only | Port of the IPOL algorithm with a grain cache. |
| `filmgrain-simplified` (C + SDL3 GPU + HLSL) | MIT | Builds (`build.sh` patched for Homebrew SDL3, `.bak` kept) but **crashes at run time on macOS**: `SDL_MapGPUTransferBuffer` returns NULL (main.c:249) under the Metal backend → SDL assertion dialog + crash report. Don't re-run on macOS; use the Linux/Windows release binaries. | Binary "grain reconstruction" via 4 layered noise-texture thresholds — cheap approximation of the Boolean model. |
| `autochrome` (Python) | MIT | Not tried — pinned to Python <3.11 with PySide2 + pyopencl + OpenColorIO | Newson-based grain + spectral film model, GUI. Early-stage. |
| `Neural_Film_Grain_Rendering` (Lesné et al. 2025) | **Academic research use only** | **Yes** — venv at `eval/.venv` (system torch 2.11 + imageio/pandas/tqdm/matplotlib). `eval/.venv/bin/python edit.py -i in.png -o out.png -gs 0.1 -s 1`. ~1.3 s / 512² on CPU. | Pretrained `models/GrainNet/default/grainnet.pt` + grain-size classifier ship in the repo. Trained on synthetic Newson output (Kaggle dataset). |
| `film-grain-synthesis` (ncherel, AV1 spec) | not stated | **Yes** — `python3 main.py` (numpy + pillow), 0.4 s | Luma-only AR(3) model + piecewise-linear gain LUT; parameters come from an AV1 stream (`ffprobe_output.json`). |

## Rendered outputs (`eval/outputs/`)
- `newson_ramp_r{0.05,0.1,0.2}.png`, `newson_bateau_r0.1.png` — Newson reference on the grey ramp / step chart and the IPOL sample.
- `neural_ramp_gs0.1.png`, `neural_bateau_gs{0.05,0.1,0.2}.png` — GrainNet.
- `compare_ramp_midband_2x.png` (Newson r=0.1 / GrainNet gs=0.1 / input, 2×), `compare_bateau_crops_2x.png`, `av1_output_crop_2x.png`.

## Observations (2026-08-29)
- Both Newson and GrainNet put the *maximum* grain at mid-grey and taper towards black and white (σ in 8-bit at grey 32/64/128/192/224 — Newson r=0.1: 7.3 / 9.5 / 10.2 / 8.4 / 6.1; GrainNet gs=0.1: 5.4 / 6.8 / 7.0 / 5.8 / 3.6). That is the Boolean model's binomial-variance shape p(1−p) in *positive* space — it is not what a negative stock does. On the real LS-50 scans grain σ in **density** keeps rising to D≈1.7–2.5 (see `docs/research-notes.md`), i.e. in positive terms the highlights stay grainy and the deep shadows are almost clean. Confirms the plan: render in negative-density space with a measured σ_D(D).
- Newson output shows the "sparse grains in shadows" artefact the paper admits (visible salt-like dots at grey 32 in the step chart).
- GrainNet is smoother/lower contrast than Newson at the same nominal size — it reproduces the look of its training renderer at a fixed filter σ.
- Neither has any notion of physical scale (µm / film format); the radius is in input pixels.
- AV1 AR model is a decent "correlated Gaussian" engine (that is essentially what we intend to drive with measured statistics), but its 64×64 tiled template repeats visibly at 100 %.
