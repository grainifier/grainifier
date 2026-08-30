"""Measure the negative → positive curve of a scanning workflow.

Give it raw scans (VueScan RAW DNG) and the delivered positives of the *same frames* (JPEG,
PNG or TIFF — whatever your scanner software or Lightroom/Negative Lab Pro exported). Pairs are
matched by the roll and frame numbers in the file names (`raw2545-0007.dng` ↔ `inv2545-0007.jpg`,
`neg_1533_0003.dng` ↔ `neg_1533_0003.jpg`), or given explicitly as `raw.dng=positive.jpg`.

For each pair the per-patch mean negative density (raw, box-downsized to the positive's pixel
count) is quantile-matched to the per-patch mean log-luminance of the positive. Because the
conversion is monotone this yields the curve P(D) without any image registration, even when the
positive is cropped, rotated or resized. The ScanCurve model

    L = ((D − black_point) / (white_point − black_point)) ** gamma

is then fitted (grid over the black point, linear least squares for gamma and the white point in
log space). The slope P′(D) at a few densities is also reported non-parametrically, which is what
the renderer actually uses.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .dng import read_vuescan_dng
from .render import ScanCurve, load_image_linear
from .stats import density

_KEY = re.compile(r"(\d{4})[-_]0*(\d+)\.[A-Za-z]+$")
SLOPE_DENSITIES = (0.5, 1.0, 1.5, 2.0)


@dataclass
class PairFit:
    key: str
    raw: str
    positive: str
    black_point: float
    white_point: float
    gamma: float
    rms: float
    slopes: list[float]  # P'(D) at SLOPE_DENSITIES (nan where the frame has no such densities)
    density_pct: list[float]  # 1 / 50 / 99 percentiles of patch density


def frame_key(path: str | Path) -> str | None:
    m = _KEY.search(Path(path).name)
    return f"{m.group(1)}-{int(m.group(2))}" if m else None


def pair_files(paths: list[str]) -> list[tuple[str, str]]:
    """Explicit `raw=positive` items, plus automatic pairing by roll/frame key."""
    pairs, raws, positives = [], {}, {}
    for p in paths:
        if "=" in p and not Path(p).exists():
            r, q = p.split("=", 1)
            pairs.append((r, q))
            continue
        key = frame_key(p)
        if key is None:
            continue
        (raws if p.lower().endswith(".dng") else positives).setdefault(key, p)
    for key in sorted(raws):
        if key in positives:
            pairs.append((raws[key], positives[key]))
    return pairs


def _patch_means(a: np.ndarray, p: int = 24) -> np.ndarray:
    h, w = a.shape[0] // p * p, a.shape[1] // p * p
    return a[:h, :w].reshape(h // p, p, w // p, p).mean((1, 3)).ravel()


def _resize_box(a: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.fromarray(np.ascontiguousarray(a, np.float32), mode="F").resize(size, Image.BOX), np.float32)


def quantile_curve(d: np.ndarray, log_l: np.ndarray, n: int = 193) -> tuple[np.ndarray, np.ndarray]:
    """Monotone map D → log10 L from the two images' patch-mean distributions."""
    scale = np.sqrt(log_l.size / d.size)
    ds = _resize_box(d, (max(1, int(d.shape[1] * scale)), max(1, int(d.shape[0] * scale))))
    md, ml = _patch_means(ds), _patch_means(log_l)
    qs = np.linspace(0.02, 0.98, n)
    return np.quantile(md, qs), np.quantile(ml, qs)


def fit_scancurve(qd: np.ndarray, ql: np.ndarray) -> tuple[float, float, float, float]:
    best = None
    for bp in np.arange(0.0, 0.8, 0.005):
        x = qd - bp
        ok = x > 0.02
        if ok.sum() < 40:
            continue
        X = np.log10(x[ok])
        A = np.stack([X, np.ones_like(X)], 1)
        (g, c), *_ = np.linalg.lstsq(A, ql[ok], rcond=None)
        if g <= 0:
            continue
        rms = float(np.sqrt(np.mean((A @ [g, c] - ql[ok]) ** 2)))
        if best is None or rms < best[0]:
            best = (rms, float(bp), float(g), float(bp + 10 ** (-c / g)))
    if best is None:
        raise ValueError("could not fit a scan curve (not enough density range)")
    rms, bp, g, wp = best
    return bp, wp, g, rms


def local_slopes(qd: np.ndarray, ql: np.ndarray, at=SLOPE_DENSITIES, half_width: float = 0.15) -> list[float]:
    out = []
    for d0 in at:
        k = np.abs(qd - d0) < half_width
        if k.sum() < 8 or qd.min() > d0 - 0.05 or qd.max() < d0 + 0.05:
            out.append(float("nan"))
        else:
            out.append(float(np.polyfit(qd[k], ql[k], 1)[0]))
    return out


def fit_pair(raw: str, positive: str) -> PairFit:
    img, meta = read_vuescan_dng(raw)
    d = density(img, meta.white_level, channels=1 if img.shape[2] < 3 else 3)[..., min(1, img.shape[2] - 1)]
    lin = load_image_linear(positive)
    log_l = np.log10(np.clip(lin, 1e-4, 1.0))
    qd, ql = quantile_curve(d, log_l)
    bp, wp, g, rms = fit_scancurve(qd, ql)
    return PairFit(
        key=frame_key(raw) or Path(raw).stem, raw=raw, positive=positive,
        black_point=bp, white_point=wp, gamma=g, rms=rms,
        slopes=local_slopes(qd, ql),
        density_pct=[float(x) for x in np.percentile(_patch_means(d), [1, 50, 99])],
    )


def summarize(fits: list[PairFit]) -> dict:
    bp = float(np.median([f.black_point for f in fits]))
    wp = float(np.median([f.white_point for f in fits]))
    g = float(np.median([f.gamma for f in fits]))
    slopes = np.array([f.slopes for f in fits])
    return dict(
        n_pairs=len(fits),
        black_point=round(bp, 3), white_point=round(wp, 3), gamma=round(g, 3),
        slope_densities=list(SLOPE_DENSITIES),
        slope_median=[None if not np.isfinite(x) else round(float(x), 3) for x in np.nanmedian(slopes, 0)],
        pairs=[dict(key=f.key, black_point=round(f.black_point, 3), white_point=round(f.white_point, 3), gamma=round(f.gamma, 3), rms=round(f.rms, 4)) for f in fits],
    )


def write_preset(summary: dict, out: Path, name: str, note: str = "") -> None:
    doc = dict(name=name, black_point=summary["black_point"], white_point=summary["white_point"], gamma=summary["gamma"],
               n_pairs=summary["n_pairs"], slope_densities=summary["slope_densities"], slope_median=summary["slope_median"],
               note=note or "measured with `grainifier scancurve`", pairs=summary["pairs"])
    Path(out).write_text(json.dumps(doc, indent=1))


def load_preset(path: str | Path) -> ScanCurve:
    doc = json.loads(Path(path).read_text())
    return ScanCurve(black_point=float(doc["black_point"]), white_point=float(doc["white_point"]), gamma=float(doc["gamma"]))
