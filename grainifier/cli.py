"""Command-line entry points.

    grainifier frame  IN.dng -o OUT.npz         statistics for one local frame
    grainifier run    --host H --list rolls.txt --out data/frames/NAME
                                                stream every DNG in the listed remote
                                                directories over ssh, cache per-frame npz
    grainifier aggregate data/frames/NAME -o profiles/NAME.json [--plots DIR]
    grainifier profiles                         list bundled profiles
    grainifier scancurve raw*.dng inv*.jpg --write mine.json
                                                measure your workflow's negative→positive curve
    grainifier render IN.png OUT.png --profile NAME|profile.json [--film-width-mm 36 ...]
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from .dng import read_vuescan_dng
from .stats import frame_stats


def _process_bytes(data: bytes, out: Path) -> dict:
    img, meta = read_vuescan_dng(data)
    st = frame_stats(img, meta.white_level)
    st["meta"] = np.array(json.dumps(meta.__dict__))
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, **st)
    return dict(width=meta.width, height=meta.height, channels=meta.channels, n_sel=int(st["sel"].sum()), n=len(st["sel"]))


def _fetch_and_process(host: str, remote: str, out: Path) -> tuple[str, dict | str]:
    try:
        t0 = time.time()
        data = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", host, "cat " + shlex.quote(remote)],
            check=True, capture_output=True,
        ).stdout
        t1 = time.time()
        info = _process_bytes(data, out)
        info["fetch_s"] = round(t1 - t0, 1)
        info["compute_s"] = round(time.time() - t1, 1)
        info["mb"] = round(len(data) / 1e6)
        return remote, info
    except Exception as e:  # noqa: BLE001 — report and continue with the next frame
        return remote, f"ERROR {type(e).__name__}: {e}"[:300]


def cmd_frame(a):
    out = Path(a.output or (Path(a.input).stem + ".npz"))
    info = _process_bytes(Path(a.input).read_bytes(), out)
    print(json.dumps(info))


def cmd_run(a):
    dirs = [l.strip() for l in Path(a.list).read_text().splitlines() if l.strip() and not l.startswith("#")]
    find = " ; ".join(f"find {shlex.quote(d)} -maxdepth 1 -iname '*.dng' | sort" for d in dirs)
    listing = subprocess.run(["ssh", "-o", "BatchMode=yes", a.host, find], check=True, capture_output=True, text=True).stdout
    remotes = [l for l in listing.splitlines() if l.strip()]
    out_root = Path(a.out)
    jobs = []
    for r in remotes:
        roll = Path(r).parent.name
        out = out_root / roll / (Path(r).stem + ".npz")
        if out.exists() and not a.force:
            continue
        jobs.append((r, out))
    print(f"{len(remotes)} frames listed, {len(jobs)} to process, {a.workers} workers", flush=True)
    log = open(out_root / "run.log", "a")
    done = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(_fetch_and_process, a.host, r, o) for r, o in jobs]
        for f in as_completed(futs):
            remote, info = f.result()
            done += 1
            line = f"[{done}/{len(jobs)} {time.time() - t0:6.0f}s] {remote} -> {info}"
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
    print("done", flush=True)


def cmd_aggregate(a):
    from .profile import aggregate, load_frames, plot_profile, write_profile

    frames = load_frames(Path(a.frames))
    prof = aggregate(frames, min_width=a.min_width, software_contains=a.software, rolls_contain=a.rolls)
    meta = dict(
        name=a.name or Path(a.frames).name,
        stock=a.stock, exposure_index=a.ei, developer=a.developer,
        scanner=a.scanner, dpi=a.dpi, pixel_pitch_um=25400.0 / a.dpi,
        generated_by=f"grainifier aggregate", frames_dir=str(a.frames),
    )
    write_profile(prof, Path(a.output), meta)
    print(f"wrote {a.output}: {prof['n_frames']} frames, {prof['n_patches']} patches, {prof['n_patches_selected']} weak-texture")
    print(f"{'D':>5} {'n_sel':>7} {'σ_D':>7} {'mode':>7} {'p10':>7} {'grain':>7} {'scan':>7} {'ac1x':>6} {'ac1y':>6} {'skew':>6} {'kurt':>6}")
    for r in prof["per_bin"]:
        if "sigma_d" in r:
            ax = r.get("autocorr_x", [0, 0])[1]
            ay = r.get("autocorr_y", [0, 0])[1]
            print(f"{r['d_mid']:5.2f} {r['n_sel']:7d} {r['sigma_d']:7.4f} {r['sigma_d_mode']:7.4f} {r['sigma_d_p10']:7.4f} {r['sigma_grain_common']:7.4f} {r['sigma_scanner_g']:7.4f} {ax:6.3f} {ay:6.3f} {r['skew']:6.2f} {r['kurtosis']:6.2f}")
    print()
    print(f"{'roll':44s} {'frames':>6s} {'σ@1.0':>7s} {'ac1 x/y':>9s} {'area':>5s} {'σ√A':>6s}  scan sw")
    for r, v in prof["per_roll"].items():
        ac = v.get("autocorr_lag1_xy@1.0", [0, 0])
        print(f"{r[:44]:44s} {v['frames']:6d} {v['sigma_d@1.0'] or 0:7.4f} {ac[0]:4.2f}/{ac[1]:4.2f} {v.get('corr_area_px2@1.0', 0):5.2f} {v.get('sigma_sqrt_area@1.0') or 0:6.3f}  {','.join(v.get('scan_software', []))}")
    if a.plots:
        for f in plot_profile(prof, Path(a.plots), title=meta["name"]):
            print("plot:", f)


def cmd_profiles(a):
    from .render import list_bundled_profiles

    for p in list_bundled_profiles():
        print(f"{p['name']:28s} {p['stock']:22s} EI {str(p['ei']):5s} {p['developer']:24s} {p['frames']:4d} frames  {p['scanner']}")


def cmd_scancurve(a):
    from .scancurve import fit_pair, pair_files, summarize, write_preset

    pairs = pair_files(a.files)
    if not pairs:
        sys.exit("no raw/positive pairs found — name files with matching roll-frame numbers (raw2545-0007.dng + inv2545-0007.jpg) or pass raw.dng=positive.jpg")
    fits = []
    print(f"{'frame':10s} {'black':>6s} {'white':>6s} {'gamma':>6s} {'rms':>6s}  P'(D) at D=0.5 1.0 1.5 2.0   D p1/p50/p99")
    for raw, pos in pairs:
        try:
            f = fit_pair(raw, pos)
        except Exception as e:  # noqa: BLE001
            print(f"{raw}: {type(e).__name__}: {e}")
            continue
        fits.append(f)
        sl = "  ".join(f"{x:4.2f}" if np.isfinite(x) else "  - " for x in f.slopes)
        print(f"{f.key:10s} {f.black_point:6.2f} {f.white_point:6.2f} {f.gamma:6.2f} {f.rms:6.3f}  {sl}   {f.density_pct[0]:.2f}/{f.density_pct[1]:.2f}/{f.density_pct[2]:.2f}")
    if not fits:
        sys.exit("no pair could be fitted")
    summ = summarize(fits)
    print(f"\nmedian of {summ['n_pairs']} pairs: black point {summ['black_point']:.2f}, white point {summ['white_point']:.2f}, gamma {summ['gamma']:.2f}; "
          f"slopes {summ['slope_median']}")
    if a.write:
        write_preset(summ, Path(a.write), a.name or Path(a.write).stem)
        print(f"wrote {a.write} — use it with: grainifier render ... --scan-preset {a.write}")


def cmd_render(a):
    from .render import Curve, GrainProfile, ScanCurve, load_image_linear, render_image, save_image

    prof = GrainProfile(a.profile)
    curve = Curve(fog=a.fog, dmax=a.dmax, gamma=a.gamma, mid_density=a.mid_density)
    if a.scan_preset in ScanCurve.PRESETS:
        scan = ScanCurve.preset(a.scan_preset, black_point=a.black_point, white_point=a.white_point, gamma=a.print_gamma if a.print_gamma > 0 else None)
    else:
        from .scancurve import load_preset

        scan = load_preset(a.scan_preset)
        scan = ScanCurve(black_point=a.black_point if a.black_point is not None else scan.black_point,
                         white_point=a.white_point if a.white_point is not None else scan.white_point,
                         gamma=a.print_gamma if a.print_gamma > 0 else scan.gamma)
    lum = load_image_linear(a.input, assume_linear=a.linear_input)
    if a.exposure:
        lum = lum * (2.0 ** a.exposure)
    soft = tuple(a.softness_um) if len(a.softness_um) == 2 else (a.softness_um[0], a.softness_um[0])
    out = render_image(
        lum, prof, curve, negative=a.negative, scan=None if a.tone == "scene" and a.print_gamma <= 0 else scan,
        tone=a.tone, film_width_mm=a.film_width_mm, grain_scale=a.grain_scale, softness_um=soft, seed=a.seed,
    )
    save_image(a.output, out, bits=a.bits, encode_srgb=not a.negative)
    h, w = lum.shape
    print(f"{a.output}: {w}x{h}, profile {prof.name}, pitch {a.film_width_mm * 1000 / max(h, w):.2f} µm/px, tone={a.tone}, "
          f"σ_D reliable to D≈{prof.reliable_dmax:.1f}, {'negative transmittance' if a.negative else 'positive sRGB'} {a.bits}-bit")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="grainifier")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("frame", help="statistics for one local DNG")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_frame)

    s = sub.add_parser("run", help="stream remote DNGs over ssh and cache per-frame statistics")
    s.add_argument("--host", required=True)
    s.add_argument("--list", required=True, help="text file with one remote directory per line")
    s.add_argument("--out", required=True)
    s.add_argument("--workers", type=int, default=3)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("aggregate", help="build a profile JSON (+plots) from cached frame statistics")
    s.add_argument("frames")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--plots")
    s.add_argument("--name")
    s.add_argument("--stock", default="")
    s.add_argument("--ei", default="")
    s.add_argument("--developer", default="")
    s.add_argument("--scanner", default="Nikon Coolscan V ED (LS-50), VueScan RAW DNG")
    s.add_argument("--dpi", type=float, default=4000.0)
    s.add_argument("--min-width", type=int, default=3000)
    s.add_argument("--software", help="only frames whose VueScan version string contains this (e.g. 9.8.46 = single-pass era)")
    s.add_argument("--rolls", nargs="*", help="only rolls whose directory name contains one of these")
    s.set_defaults(fn=cmd_aggregate)

    s = sub.add_parser("profiles", help="list the profiles bundled with the package")
    s.set_defaults(fn=cmd_profiles)

    s = sub.add_parser("scancurve", help="measure your scanning workflow's negative→positive curve from raw DNG + delivered positive pairs")
    s.add_argument("files", nargs="+", help="raw DNGs and positives (paired by roll-frame numbers in the names), or explicit raw.dng=positive.jpg items")
    s.add_argument("--write", help="write a scan-curve preset JSON for `render --scan-preset`")
    s.add_argument("--name")
    s.set_defaults(fn=cmd_scancurve)

    s = sub.add_parser("render", help="apply a measured grain profile to an image")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("--profile", required=True, help="bundled profile name (see `grainifier profiles`) or path to a profile JSON")
    s.add_argument("--film-width-mm", type=float, default=36.0, help="film frame size mapped to the image's long side")
    s.add_argument("--tone", choices=("positive", "scene"), default="positive", help="positive: input is a finished image, placed on the negative via the scan curve (default); scene: input is scene-linear, placed via the film H&D curve + --exposure")
    s.add_argument("--fog", type=float, default=0.10)
    s.add_argument("--dmax", type=float, default=2.6)
    s.add_argument("--gamma", type=float, default=0.80)
    s.add_argument("--mid-density", type=float, default=0.90, help="negative density a mid-grey lands on")
    s.add_argument("--exposure", type=float, default=0.0, help="stops of exposure offset applied to the scene")
    s.add_argument("--grain-scale", type=float, default=1.0)
    s.add_argument("--scan-preset", default="vuescan", help="measured negative→positive curve: vuescan (VueScan inversion, γ≈1.45, default), nlp (Lightroom/Negative Lab Pro look, ≈1.5–2× steeper, grainier positive), or a JSON written by `grainifier scancurve --write`")
    s.add_argument("--print-gamma", type=float, default=0.0, help="override the preset's gamma (density stretched between black and white point, then gamma); higher = contrastier, grainier positive")
    s.add_argument("--black-point", type=float, help="override the preset's black point (negative density that maps to black)")
    s.add_argument("--white-point", type=float, help="override the preset's white point")
    s.add_argument("--softness-um", type=float, nargs="+", default=[0.0], help="scan-softness Gaussian blur (µm), one value or y x")
    s.add_argument("--negative", action="store_true", help="output the negative's linear transmittance instead of a positive")
    s.add_argument("--linear-input", action="store_true")
    s.add_argument("--seed", type=int)
    s.add_argument("--bits", type=int, default=16, choices=(8, 16))
    s.set_defaults(fn=cmd_render)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
