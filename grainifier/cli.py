"""Command-line entry points.

    grainifier frame  IN.dng -o OUT.npz         statistics for one local frame
    grainifier run    --host H --list rolls.txt --out data/frames/NAME
                                                stream every DNG in the listed remote
                                                directories over ssh, cache per-frame npz
    grainifier aggregate data/frames/NAME -o profiles/NAME.json [--plots DIR]
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
    prof = aggregate(frames, min_width=a.min_width)
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
    if a.plots:
        for f in plot_profile(prof, Path(a.plots), title=meta["name"]):
            print("plot:", f)


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
    s.set_defaults(fn=cmd_aggregate)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
