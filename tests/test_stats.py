import numpy as np

from grainifier.profile import aggregate
from grainifier.stats import DENSITY_BINS, frame_stats
from tests.conftest import correlated_noise, density_to_uint16


def _flat_frame(rng, d0, sigma, lag1_x=0.55, lag1_y=0.30, size=1024, scanner_sigma=0.0, channels=3):
    n = correlated_noise((size, size), rng, lag1_x, lag1_y)
    d = d0 + sigma * n
    if channels == 1:
        return density_to_uint16(d, 1)
    chans = []
    for _ in range(3):
        dc = d + scanner_sigma * rng.standard_normal(d.shape, dtype=np.float32)
        chans.append(density_to_uint16(dc, 1))
    return np.concatenate(chans, axis=-1)


def test_recovers_sigma_and_correlation(rng):
    img = _flat_frame(rng, d0=1.05, sigma=0.10)  # bin centre, so patch means stay in one bin
    st = frame_stats(img, 65535.0)
    b = np.digitize(1.05, DENSITY_BINS) - 1
    m = st["sel"] & (np.digitize(st["mean_d"], DENSITY_BINS) - 1 == b)
    assert m.sum() > 300
    sigma = np.sqrt(np.median(st["var"][m, 1]))
    assert abs(sigma - 0.10) / 0.10 < 0.05
    assert abs(np.median(st["skew"][m])) < 0.1
    assert abs(np.median(st["kurt"][m]) - 3.0) < 0.2
    ac = np.fft.fftshift(np.fft.irfft2(st["spec_sum"][b] / st["spec_n"][b], s=(32, 32)))
    ac /= ac.max()
    assert abs(ac[16, 17] - 0.55) < 0.05 and abs(ac[17, 16] - 0.30) < 0.05
    # channels carry the same grain → perfectly correlated
    corr = np.median(st["cov"][m, 0] / np.sqrt(st["var"][m, 0] * st["var"][m, 1]))
    assert corr > 0.99


def test_texture_rejection(rng):
    img = _flat_frame(rng, d0=1.0, sigma=0.10)
    d = -np.log10(img[..., 1] / 65535.0)
    yy, xx = np.mgrid[0:1024, 0:1024]
    d = d + 0.3 * np.sin(2 * np.pi * xx / 300) * np.sin(2 * np.pi * yy / 220)  # smooth "image content"
    st = frame_stats(density_to_uint16(d), 65535.0)
    # the texture is low-frequency: patches in the flattest regions should still be selected,
    # and the median sigma of selected patches should not be inflated by more than ~10 %
    sel_sigma = np.sqrt(np.median(st["var"][st["sel"], 1]))
    all_sigma = np.sqrt(np.median(st["var"][:, 1]))
    assert sel_sigma < all_sigma
    assert sel_sigma < 0.11


def test_greyscale_frame(rng):
    st = frame_stats(_flat_frame(rng, 0.8, 0.08, channels=1), 65535.0)
    assert st["channels_used"] == 1
    assert np.isnan(st["cov"]).all() and np.isnan(st["var"][:, 0]).all()
    assert abs(np.sqrt(np.median(st["var"][st["sel"], 1])) - 0.08) < 0.005


def test_scanner_noise_split_in_aggregate(rng):
    frames = []
    for i in range(3):
        img = _flat_frame(rng, d0=1.2, sigma=0.10, scanner_sigma=0.04)
        st = frame_stats(img, 65535.0)
        st["roll"] = "synthetic"
        st["meta"] = np.array('{"software": "test"}')
        frames.append(st)
    prof = aggregate(frames, min_width=500, min_patches=100)
    row = next(r for r in prof["per_bin"] if abs(r["d_mid"] - 1.25) < 0.01)
    assert abs(row["sigma_grain_common"] - 0.10) < 0.01
    assert abs(row["sigma_scanner_g"] - 0.04) < 0.01
    assert abs(row["sigma_d"] - np.hypot(0.10, 0.04)) < 0.01
    assert prof["n_frames"] == 3 and "synthetic" in prof["per_roll"]
