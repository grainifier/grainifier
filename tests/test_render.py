import numpy as np
import pytest

from grainifier.render import Curve, GrainProfile, list_bundled_profiles, render_density, render_image, resolve_profile, skew_coeff
from grainifier.stats import DENSITY_BINS, frame_stats
from tests.conftest import density_to_uint16


def test_curve_roundtrip_and_anchors():
    c = Curve(fog=0.1, dmax=2.6, gamma=0.8, mid_density=0.9)
    lin = np.logspace(-3, 0.5, 200).astype(np.float32)
    d = c.density(lin)
    assert np.all(np.diff(d) > 0) and d.min() > 0.1 and d.max() < 2.6
    assert abs(float(c.density(np.array([0.18], np.float32))[0]) - 0.9) < 1e-4
    back = c.inverse(d)
    ok = (d > 0.15) & (d < 2.5)
    assert np.allclose(np.log10(back[ok]), np.log10(lin[ok]), atol=0.01)
    with pytest.raises(ValueError):
        Curve(mid_density=3.0)


def test_skew_coeff_produces_requested_skew(rng):
    n = rng.standard_normal(2_000_000, dtype=np.float32)
    for s in (-0.3, 0.0, 0.5):
        a = skew_coeff(np.array([s], np.float32))[0]
        x = (n + a * (n * n - 1)) / np.sqrt(1 + 2 * a * a)
        assert abs(x.std() - 1) < 0.01
        assert abs(((x - x.mean()) ** 3).mean() - s) < 0.03


def test_bundled_profiles_resolve():
    names = [p["name"] for p in list_bundled_profiles()]
    assert "hp5-plus-ei1600-1pass" in names and "bwxx-1pass" in names
    assert resolve_profile("bwxx-1pass").exists() and resolve_profile("bwxx-1pass.json").exists()
    with pytest.raises(FileNotFoundError):
        resolve_profile("no-such-stock")


def test_profile_kernel_and_pitch():
    p = GrainProfile("hp5-plus-ei1600-1pass")
    assert p.kernel.shape == (32, 32) and abs((p.kernel**2).sum() - 1) < 1e-4
    k = p.kernel_at_pitch(3.0)
    assert k.shape[0] > 32 and abs((k**2).sum() - 1) < 1e-4
    assert p.reliable_dmax >= 2.0
    assert 0.08 < p.sigma_at(np.array([1.0]))[0] < 0.16


@pytest.mark.parametrize("d0", [0.55, 1.05, 2.05])
def test_closed_loop_against_profile(d0):
    p = GrainProfile("hp5-plus-ei1600-1pass")
    d = np.full((1024, 1024), d0, np.float32)
    dg = render_density(d, p, film_width_mm=1024 * p.pitch_um / 1000.0, seed=7)
    st = frame_stats(density_to_uint16(dg), 65535.0)
    b = np.digitize(d0, DENSITY_BINS) - 1
    m = st["sel"] & (np.digitize(st["mean_d"], DENSITY_BINS) - 1 == b)
    sigma = np.sqrt(np.median(st["var"][m, 1]))
    assert abs(sigma - p.sigma_at(np.array([d0]))[0]) / sigma < 0.04
    assert abs(np.median(st["skew"][m]) - p.skew_at(np.array([d0]))[0]) < 0.06
    ac = np.fft.fftshift(np.fft.irfft2(st["spec_sum"][b] / st["spec_n"][b], s=(32, 32)))
    ac /= ac.max()
    assert 0.45 < ac[16, 17] < 0.65 and 0.2 < ac[17, 16] < 0.42  # x more correlated than y, as measured


def test_physical_scaling_reduces_grain_when_downsized():
    p = GrainProfile("bwxx-1pass")
    d = np.full((512, 512), 1.0, np.float32)
    fine = render_density(d, p, film_width_mm=512 * p.pitch_um / 1000.0, seed=1) - 1.0   # 6.35 µm/px
    coarse = render_density(d, p, film_width_mm=36.0, seed=1) - 1.0                        # 70 µm/px
    assert fine.std() > 3 * coarse.std()
    assert coarse.std() > 0


def test_render_image_outputs_and_seed():
    p = GrainProfile("bwxx-1pass")
    lum = np.tile(np.linspace(0.01, 0.9, 256, dtype=np.float32), (128, 1))
    c = Curve()
    a = render_image(lum, p, c, seed=3, film_width_mm=256 * p.pitch_um / 1000.0)
    b = render_image(lum, p, c, seed=3, film_width_mm=256 * p.pitch_um / 1000.0)
    assert np.array_equal(a, b) and a.min() >= 0
    assert np.isfinite(a).all()  # linear scene values; grain may push highlights well above 1.0, save_image clips
    neg = render_image(lum, p, c, seed=3, negative=True, film_width_mm=256 * p.pitch_um / 1000.0)
    assert neg.min() > 0 and neg.max() <= 1
    # tone is preserved on average: column means follow the input
    assert np.corrcoef(a.mean(0), lum.mean(0))[0, 1] > 0.99


def test_positive_model_matches_slope_times_sigma():
    """Grain in the positive must equal ScanCurve.slope(D) * sigma_D in log-luminance, tone preserved."""
    from grainifier.render import ScanCurve

    p = GrainProfile("hp5-plus-ei1600-1pass")
    sc = ScanCurve()
    for L in (0.05, 0.2, 0.6):
        lum = np.full((512, 512), L, np.float32)
        out = render_image(lum, p, seed=5, film_width_mm=512 * p.pitch_um / 1000.0)
        d = float(sc.density(np.array([L], np.float32))[0])
        expected = sc.slope(np.array([d], np.float32))[0] * p.sigma_at(np.array([d]))[0]
        measured = np.log10(out).std()
        assert abs(measured - expected) / expected < 0.08, (L, d, measured, expected)
        assert abs(np.median(out) - L) / L < 0.05
    # placement matches the measured real-frame pairs (L 0.05/0.24/0.79 -> D ~0.4/1.0/2.1)
    d = sc.density(np.array([0.05, 0.24, 0.79], np.float32))
    assert np.allclose(d, [0.32, 0.87, 2.09], atol=0.12)
    # highlights carry gentler grain than midtones in log-luminance, as in real scans
    s = lambda L: np.log10(render_image(np.full((256, 256), L, np.float32), p, seed=1, film_width_mm=256 * p.pitch_um / 1000.0)).std()
    assert s(0.8) < s(0.25) < s(0.05)


def test_scene_tone_mode_and_exact_inverse():
    p = GrainProfile("bwxx-1pass")
    lum = np.full((256, 256), 0.18, np.float32)
    a = render_image(lum, p, Curve(), tone="scene", seed=1, film_width_mm=256 * p.pitch_um / 1000.0)
    b = render_image(lum, p, Curve(), tone="scene", print_gamma=1.25, seed=1, film_width_mm=256 * p.pitch_um / 1000.0)
    assert np.isfinite(a).all() and np.isfinite(b).all() and a.std() > 0 and b.std() > 0
    assert abs(np.median(b) - 0.18) / 0.18 < 0.05
    with pytest.raises(ValueError):
        render_image(lum, p, tone="nonsense")
