"""Per-frame grain statistics from a linear film scan.

Everything is computed in *negative density* D = -log10(T), T = value / white, which is
the physically meaningful axis for silver grain (Selwyn granularity, Kodak/Ilford RMS
values are all density fluctuations).

The frame is tiled into P×P patches. For each patch and channel we remove a fitted plane
(local image gradient) and keep the residual, then record:

- mean density (green channel) → density bin
- residual variance per channel, and the cross-channel covariances. Silver grain is common
  to R, G and B while scanner (CCD/readout) noise is channel-independent, so
  cov(R, G) ≈ grain variance and var(G) − cov(R, G) ≈ scanner noise variance.
- a low-frequency power fraction used as a "weak texture" criterion: image content adds
  power at the lowest spatial frequencies, stationary grain does not.
- skewness and kurtosis of the green residual (Gaussianity check).
- the 2-D power spectrum of the green residual, accumulated per density bin over the
  weakly-textured patches → noise power spectrum (NPS) and autocorrelation per density.

Nothing here decides what the final profile is — thresholds are recorded so the
aggregation step can be re-run on the cached per-frame results with different choices.
"""
from __future__ import annotations

import numpy as np

DENSITY_BINS = np.round(np.arange(0.0, 3.6 + 1e-9, 0.1), 2)  # 36 bins of 0.1 D
PATCH = 32  # px; 32 px ≈ 203 µm at 4000 dpi
LOWFREQ_K = 2  # |k| <= 2 cycles per patch counts as "low frequency" (period >= 16 px)


def density(img: np.ndarray, white: float, channels: int = 3) -> np.ndarray:
    """Linear transmittance → negative density, float32 (H, W, channels)."""
    t = img[..., :channels].astype(np.float32) / np.float32(white)
    np.clip(t, 1e-4, 1.0, out=t)
    return -np.log10(t, out=t)


def _plane_basis(p: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:p, 0:p].astype(np.float32)
    a = np.stack([np.ones(p * p, np.float32), (yy.ravel() - p / 2) / p, (xx.ravel() - p / 2) / p], 1)
    return a, np.linalg.pinv(a).astype(np.float32)


def _spectral_weights(p: int) -> tuple[np.ndarray, np.ndarray]:
    """Weights so that sum(w * |rfft2|^2) / p^4 == variance, and a low-frequency mask."""
    w = np.full((p, p // 2 + 1), 2.0, np.float32)
    w[:, 0] = 1.0
    w[:, -1] = 1.0
    ky = np.fft.fftfreq(p) * p  # -p/2 .. p/2-1 (integer cycles per patch)
    kx = np.arange(p // 2 + 1)
    low = (np.abs(ky)[:, None] <= LOWFREQ_K) & (kx[None, :] <= LOWFREQ_K)
    low[0, 0] = False  # DC is zero after detrending anyway
    return w, low


def frame_stats(
    img: np.ndarray,
    white: float,
    patch: int = PATCH,
    bins: np.ndarray = DENSITY_BINS,
    texture_quantile: float = 0.10,
    texture_factor: float = 1.5,
) -> dict:
    p = patch
    d = density(img, white)  # (H, W, 3)
    h, w = d.shape[:2]
    nh, nw = h // p, w // p
    # (N, 3, p*p) patches
    patches = (
        d[: nh * p, : nw * p]
        .reshape(nh, p, nw, p, 3)
        .transpose(0, 2, 4, 1, 3)
        .reshape(nh * nw, 3, p * p)
    )
    del d
    a, pinv = _plane_basis(p)
    coef = patches @ pinv.T  # (N, 3, 3)
    res = patches - coef @ a.T  # (N, 3, p*p)
    mean_d = patches[:, 1, :].mean(-1)
    mean_rgb = patches.mean(-1)  # (N, 3)
    del patches
    var = (res * res).mean(-1)  # (N, 3)
    cov = np.stack(
        [
            (res[:, 0] * res[:, 1]).mean(-1),  # R-G
            (res[:, 1] * res[:, 2]).mean(-1),  # G-B
            (res[:, 0] * res[:, 2]).mean(-1),  # R-B
        ],
        1,
    )
    g = res[:, 1]
    sd = np.sqrt(var[:, 1]) + 1e-9
    skew = ((g / sd[:, None]) ** 3).mean(-1)
    kurt = ((g / sd[:, None]) ** 4).mean(-1)

    spec = np.abs(np.fft.rfft2(g.reshape(-1, p, p))) ** 2  # (N, p, p/2+1), float32/64
    spec = spec.astype(np.float32)
    wts, low = _spectral_weights(p)
    total = (spec * wts).sum((1, 2)) + 1e-12
    lowfrac = (spec * (wts * low)).sum((1, 2)) / total

    thr = float(texture_factor * np.quantile(lowfrac, texture_quantile))
    sel = lowfrac < thr
    bin_idx = np.digitize(mean_d, bins) - 1
    valid = (bin_idx >= 0) & (bin_idx < len(bins) - 1)
    nb = len(bins) - 1
    spec_sum = np.zeros((nb, p, p // 2 + 1), np.float64)
    spec_n = np.zeros(nb, np.int64)
    var_sum = np.zeros(nb, np.float64)
    use = sel & valid
    for b in np.unique(bin_idx[use]):
        m = use & (bin_idx == b)
        spec_sum[b] = spec[m].sum(0)
        spec_n[b] = int(m.sum())
        var_sum[b] = float(var[m, 1].sum())

    hist, _ = np.histogram(mean_d, bins=np.arange(0, 4.0 + 1e-9, 0.02))
    return dict(
        patch=p,
        bins=bins,
        mean_d=mean_d.astype(np.float32),
        mean_rgb=mean_rgb.astype(np.float32),
        var=var.astype(np.float32),
        cov=cov.astype(np.float32),
        lowfrac=lowfrac.astype(np.float32),
        skew=skew.astype(np.float32),
        kurt=kurt.astype(np.float32),
        sel=sel,
        texture_threshold=thr,
        spec_sum=spec_sum,
        spec_n=spec_n,
        var_sum=var_sum,
        density_hist=hist,
        shape=np.array([h, w, img.shape[2]]),
        white=float(white),
    )
