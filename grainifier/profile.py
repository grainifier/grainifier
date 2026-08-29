"""Aggregate per-frame statistics into a grain profile."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .stats import _spectral_weights


def load_frames(frame_dir: Path) -> list[dict]:
    frames = []
    for f in sorted(Path(frame_dir).rglob("*.npz")):
        with np.load(f, allow_pickle=False) as z:
            d = {k: z[k] for k in z.files}
        d["path"] = str(f)
        d["roll"] = f.parent.name
        frames.append(d)
    return frames


def _mode_of_log(x: np.ndarray, nbins: int = 60) -> float:
    """Mode of a positive quantity, estimated on a log grid with light smoothing."""
    x = x[x > 0]
    if len(x) < 20:
        return float(np.median(x)) if len(x) else float("nan")
    lx = np.log(x)
    h, e = np.histogram(lx, bins=nbins)
    h = np.convolve(h, np.ones(5) / 5, mode="same")
    c = 0.5 * (e[:-1] + e[1:])
    return float(np.exp(c[np.argmax(h)]))


def aggregate(frames: list[dict], min_width: int = 3000, min_patches: int = 200) -> dict:
    frames = [f for f in frames if int(f["shape"][1]) >= min_width and int(f["shape"][0]) >= min_width]
    if not frames:
        raise ValueError("no frames pass the size filter")
    bins = frames[0]["bins"]
    p = int(frames[0]["patch"])
    nb = len(bins) - 1
    wts, _ = _spectral_weights(p)

    mean_d = np.concatenate([f["mean_d"] for f in frames])
    var = np.concatenate([f["var"] for f in frames])
    cov = np.concatenate([f["cov"] for f in frames])
    skew = np.concatenate([f["skew"] for f in frames])
    kurt = np.concatenate([f["kurt"] for f in frames])
    sel = np.concatenate([f["sel"] for f in frames])
    roll = np.concatenate([np.full(len(f["mean_d"]), f["roll"]) for f in frames])
    bin_idx = np.digitize(mean_d, bins) - 1
    valid = (bin_idx >= 0) & (bin_idx < nb)

    spec_sum = sum(f["spec_sum"] for f in frames)
    spec_n = sum(f["spec_n"] for f in frames)

    per_bin = []
    autocorr_x, autocorr_y, nps = [], [], []
    for b in range(nb):
        m_all = valid & (bin_idx == b)
        m = m_all & sel
        row = dict(
            d_lo=float(bins[b]), d_hi=float(bins[b + 1]), d_mid=float(0.5 * (bins[b] + bins[b + 1])),
            n_all=int(m_all.sum()), n_sel=int(m.sum()),
        )
        if m.sum() >= min_patches:
            vg = var[m, 1]
            # "three-cornered hat": with D_c = g_c * grain + n_c (n_c independent per channel),
            # cov_rg * cov_gb / cov_rb = g_g^2 * var(grain), i.e. the grain variance as seen in G.
            crb = np.where(cov[m, 2] > 1e-9, cov[m, 2], np.nan)
            common = cov[m, 0] * cov[m, 1] / crb
            common = common[np.isfinite(common)]
            scanner = (var[m, 1] - cov[m, 0] * cov[m, 1] / crb)
            scanner = scanner[np.isfinite(scanner)]
            row.update(
                sigma_d=float(np.sqrt(np.median(vg))),
                sigma_d_p10=float(np.sqrt(np.quantile(vg, 0.10))),
                sigma_d_p25=float(np.sqrt(np.quantile(vg, 0.25))),
                sigma_d_mode=float(np.sqrt(_mode_of_log(vg))),
                sigma_d_all_median=float(np.sqrt(np.median(var[m_all, 1]))),
                sigma_grain_common=float(np.sqrt(max(np.median(common), 0.0))),
                sigma_scanner_g=float(np.sqrt(max(np.median(scanner), 0.0))),
                sigma_r=float(np.sqrt(np.median(var[m, 0]))),
                sigma_b=float(np.sqrt(np.median(var[m, 2]))),
                corr_rg=float(np.median(cov[m, 0] / np.sqrt(var[m, 0] * var[m, 1] + 1e-12))),
                corr_gb=float(np.median(cov[m, 1] / np.sqrt(var[m, 1] * var[m, 2] + 1e-12))),
                skew=float(np.median(skew[m])),
                kurtosis=float(np.median(kurt[m])),
            )
        if spec_n[b] > 0:
            s = spec_sum[b] / spec_n[b]  # mean |F|^2 of green residual
            # autocorrelation = inverse transform of the power spectrum (Wiener–Khinchin);
            # irfft2 reconstructs the Hermitian half for us
            ac = np.fft.irfft2(s.astype(np.float64), s=(p, p))
            ac /= ac[0, 0] + 1e-20
            autocorr_x.append([float(ac[0, k]) for k in range(9)])
            autocorr_y.append([float(ac[k, 0]) for k in range(9)])
            nps.append((s / (p * p)).astype(np.float32).tolist())  # per-pixel power units (D^2)
            row["autocorr_x"] = autocorr_x[-1]
            row["autocorr_y"] = autocorr_y[-1]
        per_bin.append(row)

    # per-roll consistency at a few reference densities
    rolls = sorted(set(roll.tolist()))
    ref = [0.6, 1.0, 1.5, 2.0]
    per_roll = {}
    for r in rolls:
        mr = (roll == r) & sel & valid
        per_roll[r] = {}
        for dref in ref:
            b = int(np.digitize(dref, bins) - 1)
            m = mr & (bin_idx == b)
            per_roll[r][f"sigma_d@{dref}"] = float(np.sqrt(np.median(var[m, 1]))) if m.sum() >= 50 else None
            per_roll[r][f"n@{dref}"] = int(m.sum())
        per_roll[r]["frames"] = int(sum(1 for f in frames if f["roll"] == r))

    hist = sum(f["density_hist"] for f in frames)
    return dict(
        patch_px=p,
        bins=[float(b) for b in bins],
        n_frames=len(frames),
        n_patches=int(valid.sum()),
        n_patches_selected=int((valid & sel).sum()),
        texture_threshold_median=float(np.median([f["texture_threshold"] for f in frames])),
        per_bin=per_bin,
        per_roll=per_roll,
        density_histogram=dict(edges=[round(x, 2) for x in np.arange(0, 4.0 + 1e-9, 0.02).tolist()], counts=hist.astype(int).tolist()),
        nps_green=dict(note="mean power spectrum of plane-detrended green-channel density residual, rfft2 layout (p, p/2+1), units D^2 per pixel", bins_with_data=[i for i in range(nb) if spec_n[i] > 0], spectra=nps),
    )


def write_profile(profile: dict, out: Path, meta: dict | None = None) -> None:
    doc = dict(meta or {})
    doc.update(profile)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(doc, indent=1))


def plot_profile(profile: dict, out_dir: Path, title: str = "") -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [r for r in profile["per_bin"] if "sigma_d" in r]
    d = np.array([r["d_mid"] for r in rows])
    written = []

    fig, ax = plt.subplots(figsize=(8, 5))
    for key, lab, st in [
        ("sigma_d_all_median", "all patches, median", ":"),
        ("sigma_d", "weak-texture patches, median", "-"),
        ("sigma_d_mode", "weak-texture, mode", "--"),
        ("sigma_d_p10", "weak-texture, 10th pct", "-."),
        ("sigma_grain_common", "grain = R/G common part", "-"),
        ("sigma_scanner_g", "scanner (G − common)", "-"),
    ]:
        ax.plot(d, [r[key] for r in rows], st, label=lab, lw=2 if key in ("sigma_d", "sigma_grain_common") else 1.2)
    ax.set_xlabel("negative density D")
    ax.set_ylabel(f"σ_D per pixel ({profile['patch_px']} px patches)")
    ax.set_title(f"{title} grain amplitude vs density".strip())
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    ax2 = ax.twinx()
    e = np.array(profile["density_histogram"]["edges"])
    c = np.array(profile["density_histogram"]["counts"], float)
    ax2.fill_between(0.5 * (e[:-1] + e[1:]), c / c.max(), alpha=0.12, color="grey", step="mid")
    ax2.set_yticks([])
    ax2.set_ylabel("patch density histogram", color="grey")
    f = out_dir / "sigma_vs_density.png"
    fig.tight_layout()
    fig.savefig(f, dpi=130)
    plt.close(fig)
    written.append(f)

    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    axs[0].plot(d, [r["autocorr_x"][1] for r in rows], label="lag 1 x")
    axs[0].plot(d, [r["autocorr_y"][1] for r in rows], label="lag 1 y")
    axs[0].plot(d, [r["autocorr_x"][2] for r in rows], "--", label="lag 2 x")
    axs[0].plot(d, [r["autocorr_y"][2] for r in rows], "--", label="lag 2 y")
    axs[0].set_xlabel("D")
    axs[0].set_ylabel("autocorrelation")
    axs[0].set_title("grain correlation vs density")
    axs[0].grid(alpha=0.3)
    axs[0].legend(fontsize=8)
    axs[1].plot(d, [r["skew"] for r in rows], label="skewness")
    axs[1].plot(d, [r["kurtosis"] - 3 for r in rows], label="excess kurtosis")
    axs[1].plot(d, [r["corr_rg"] for r in rows], label="corr(R,G)")
    axs[1].axhline(0, color="k", lw=0.5)
    axs[1].set_xlabel("D")
    axs[1].set_title("Gaussianity and channel correlation")
    axs[1].grid(alpha=0.3)
    axs[1].legend(fontsize=8)
    f = out_dir / "correlation_and_shape.png"
    fig.tight_layout()
    fig.savefig(f, dpi=130)
    plt.close(fig)
    written.append(f)

    # NPS images at a few densities
    picks = [r for r in rows if abs(r["d_mid"] - 0.55) < 0.01 or abs(r["d_mid"] - 1.05) < 0.01 or abs(r["d_mid"] - 1.55) < 0.01 or abs(r["d_mid"] - 2.05) < 0.01]
    if picks:
        p = profile["patch_px"]
        fig, axs = plt.subplots(1, len(picks), figsize=(3.2 * len(picks), 3.4))
        axs = np.atleast_1d(axs)
        idx = {b: i for i, b in enumerate(profile["nps_green"]["bins_with_data"])}
        for ax, r in zip(axs, picks):
            b = int(round(r["d_lo"] / (profile["bins"][1] - profile["bins"][0])))
            s = np.array(profile["nps_green"]["spectra"][idx[b]], np.float64)
            full = np.abs(np.fft.fft2(np.fft.irfft2(s, s=(p, p))))
            ax.imshow(np.fft.fftshift(np.log10(full + 1e-12)), cmap="magma")
            ax.set_title(f"NPS, D≈{r['d_mid']:.2f}", fontsize=9)
            ax.set_xticks([])
            ax.set_yticks([])
        f = out_dir / "nps.png"
        fig.tight_layout()
        fig.savefig(f, dpi=130)
        plt.close(fig)
        written.append(f)

    # per-roll consistency
    pr = profile["per_roll"]
    rolls = list(pr)
    fig, ax = plt.subplots(figsize=(max(8, 0.55 * len(rolls)), 4))
    for dref, mk in zip([0.6, 1.0, 1.5, 2.0], "osd^"):
        ax.plot(range(len(rolls)), [pr[r][f"sigma_d@{dref}"] or np.nan for r in rolls], mk, label=f"D≈{dref}")
    ax.set_xticks(range(len(rolls)))
    ax.set_xticklabels([r[:22] for r in rolls], rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("σ_D (weak-texture median)")
    ax.set_title("per-roll consistency")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    f = out_dir / "per_roll.png"
    fig.tight_layout()
    fig.savefig(f, dpi=130)
    plt.close(fig)
    written.append(f)
    return written
