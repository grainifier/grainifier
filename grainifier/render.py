"""Render measured film grain onto a digital image.

Pipeline (B&W silver negative):

    image → linear luminance → H&D curve → negative density D
          → D + σ_D(D) · skewed, NPS-shaped noise   (grain, in density space)
          → optional scan-softness blur
          → inverse H&D curve → linear → output      (or the negative's transmittance)

The grain statistics — σ_D(D), skewness(D) and the 2-D noise power spectrum — come from a
profile JSON produced by `grainifier aggregate` from real scans. The NPS is used as a
convolution kernel expressed in micrometres, so the grain has a physical size: the output
image is mapped onto a film frame (`film_width_mm` across its long side), grain is
synthesised on the scanner's pitch (6.35 µm for the 4000-dpi profiles) and area-averaged
onto the output pixel grid. A small image therefore gets finer, weaker per-pixel grain, as
a real scan downsized would.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REF_PITCH_UM = 25400.0 / 4000.0


# ----------------------------------------------------------------------------- colour helpers
def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def luminance(rgb_lin: np.ndarray) -> np.ndarray:
    """Linear RGB → scene luminance. A panchromatic B&W film's response is close enough
    to Rec.709 luma for a first version; filters/spectral response can come later."""
    if rgb_lin.ndim == 2:
        return rgb_lin.astype(np.float32)
    r, g, b = rgb_lin[..., 0], rgb_lin[..., 1], rgb_lin[..., 2]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b).astype(np.float32)


# ----------------------------------------------------------------------------- H&D curve
@dataclass
class Curve:
    """Logistic characteristic curve D(log E) — a placeholder until measured curves exist.

    fog:          base + fog density (Dmin)
    dmax:         shoulder density
    gamma:        slope at the curve midpoint (≈ average gradient; ~0.6 normal, ~0.8 pushed)
    mid_density:  density that a mid-grey (18 %) scene value lands on
    """

    fog: float = 0.10
    dmax: float = 2.6
    gamma: float = 0.80
    mid_density: float = 0.90
    k: float = field(init=False)
    le0: float = field(init=False)

    def __post_init__(self):
        rng = self.dmax - self.fog
        self.k = 4.0 * self.gamma / (rng * np.log(10.0))
        f = (self.mid_density - self.fog) / rng
        if not 0.0 < f < 1.0:
            raise ValueError("mid_density must lie between fog and dmax")
        self.le0 = np.log10((1.0 - f) / f) / self.k

    def density(self, lin: np.ndarray) -> np.ndarray:
        le = np.log10(np.maximum(lin, 1e-6) / 0.18)
        return (self.fog + (self.dmax - self.fog) / (1.0 + 10.0 ** (-self.k * (le - self.le0)))).astype(np.float32)

    def inverse(self, d: np.ndarray, eps: float = 1e-4) -> np.ndarray:
        f = np.clip((d - self.fog) / (self.dmax - self.fog), eps, 1.0 - eps)
        le = self.le0 - np.log10(1.0 / f - 1.0) / self.k
        return (0.18 * 10.0 ** le).astype(np.float32)


# ----------------------------------------------------------------------------- profile
def _skew_table():
    a = np.linspace(-0.6, 0.6, 1201)
    s = (6 * a + 8 * a**3) / (1 + 2 * a**2) ** 1.5
    return s, a


_SKEW_S, _SKEW_A = _skew_table()


def skew_coeff(target_skew: np.ndarray) -> np.ndarray:
    """Coefficient a such that (n + a(n²−1))/sqrt(1+2a²) has the requested skewness (n ~ N(0,1))."""
    return np.interp(np.clip(target_skew, _SKEW_S[0], _SKEW_S[-1]), _SKEW_S, _SKEW_A).astype(np.float32)


BUNDLED_DIR = Path(__file__).parent / "profiles"


def list_bundled_profiles() -> list[dict]:
    out = []
    for f in sorted(BUNDLED_DIR.glob("*.json")):
        p = json.loads(f.read_text())
        out.append(dict(name=f.stem, stock=p.get("stock", ""), ei=p.get("exposure_index", ""),
                        developer=p.get("developer", ""), frames=p.get("n_frames"), scanner=p.get("scanner", "")))
    return out


def resolve_profile(name_or_path: str | Path) -> Path:
    """A path to a JSON file, or the name of a bundled profile (with or without .json)."""
    q = Path(name_or_path)
    if q.exists():
        return q
    cand = BUNDLED_DIR / (q.name if q.suffix == ".json" else q.name + ".json")
    if cand.exists():
        return cand
    names = ", ".join(f.stem for f in sorted(BUNDLED_DIR.glob("*.json")))
    raise FileNotFoundError(f"no profile {name_or_path!r}; bundled: {names}")


class GrainProfile:
    def __init__(self, path: str | Path, kernel_density_range=(0.7, 1.7), min_channel_corr=0.9):
        path = resolve_profile(path)
        p = json.loads(Path(path).read_text())
        self.name = p.get("name", Path(path).stem)
        self.pitch_um = float(p.get("pixel_pitch_um", REF_PITCH_UM))
        rows = [r for r in p["per_bin"] if "sigma_d" in r]
        self.d = np.array([r["d_mid"] for r in rows], np.float32)
        self.sigma = np.array([r["sigma_d"] for r in rows], np.float32)
        self.skew = np.array([r["skew"] for r in rows], np.float32)
        # beyond the scanner's reliable density range the channel correlation collapses;
        # hold the last trustworthy values there instead of following the noise floor
        ok = np.array([r.get("corr_rg", 1.0) >= min_channel_corr for r in rows])
        if ok.any():
            last = int(np.nonzero(ok)[0].max())
            self.sigma[last + 1 :] = self.sigma[last]
            self.skew[last + 1 :] = self.skew[last]
        self.reliable_dmax = float(self.d[last]) if ok.any() else float(self.d[-1])
        # kernel: unit-normalised NPS shape averaged over the mid-density bins → zero-phase filter
        P = int(p["patch_px"])
        idx = {b: i for i, b in enumerate(p["nps_green"]["bins_with_data"])}
        bins = p["bins"]
        acc, n = 0.0, 0
        for b, i in idx.items():
            dm = 0.5 * (bins[b] + bins[b + 1])
            if kernel_density_range[0] <= dm <= kernel_density_range[1]:
                s = np.array(p["nps_green"]["spectra"][i], np.float64)
                acc = acc + s / s.sum()
                n += 1
        if n == 0:
            raise ValueError("profile has no spectra in the kernel density range")
        s = acc / n
        power = np.abs(np.fft.fft2(np.fft.irfft2(s, s=(P, P))))
        h = np.fft.fftshift(np.fft.ifft2(np.sqrt(power)).real)
        self.kernel = (h / np.sqrt((h**2).sum())).astype(np.float32)  # P×P, unit output variance
        self.patch = P

    def sigma_at(self, d: np.ndarray) -> np.ndarray:
        return np.interp(d, self.d, self.sigma).astype(np.float32)

    def skew_at(self, d: np.ndarray) -> np.ndarray:
        return np.interp(d, self.d, self.skew).astype(np.float32)

    def kernel_at_pitch(self, pitch_um: float) -> np.ndarray:
        """Bilinearly resample the kernel to a finer pixel pitch (same physical extent)."""
        if abs(pitch_um - self.pitch_um) < 1e-6:
            return self.kernel
        P = self.patch
        extent = P * self.pitch_um
        n = int(np.ceil(extent / pitch_um)) | 1
        c = np.arange(n) - n // 2
        u = c * pitch_um / self.pitch_um + P / 2  # sample position in kernel pixel units
        u = np.clip(u, 0, P - 1)
        i0 = np.floor(u).astype(int)
        i1 = np.minimum(i0 + 1, P - 1)
        t = (u - i0).astype(np.float32)
        k = self.kernel
        rows = k[i0][:, None, :] * (1 - t)[:, None, None] + k[i1][:, None, :] * t[:, None, None]  # (n,1,P)
        rows = rows[:, 0, :]
        out = rows[:, i0] * (1 - t)[None, :] + rows[:, i1] * t[None, :]
        return (out / np.sqrt((out**2).sum())).astype(np.float32)


# ----------------------------------------------------------------------------- synthesis
def _resize_f32(a: np.ndarray, size: tuple[int, int], box: bool) -> np.ndarray:
    from PIL import Image

    im = Image.fromarray(np.ascontiguousarray(a, dtype=np.float32), mode="F")
    return np.asarray(im.resize(size, Image.BOX if box else Image.BILINEAR), dtype=np.float32)


def _shaped_noise(shape: tuple[int, int], kernel: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    h, w = shape
    kh, kw = kernel.shape
    pad = np.zeros(shape, np.float32)
    pad[:kh, :kw] = kernel
    pad = np.roll(pad, (-(kh // 2), -(kw // 2)), axis=(0, 1))  # centre the zero-phase kernel at (0,0)
    white = rng.standard_normal(shape, dtype=np.float32)
    return np.fft.irfft2(np.fft.rfft2(white) * np.fft.rfft2(pad), s=shape).astype(np.float32)


def _gaussian_blur_fft(a: np.ndarray, sigma_px: tuple[float, float]) -> np.ndarray:
    sy, sx = sigma_px
    if sy <= 0 and sx <= 0:
        return a
    h, w = a.shape
    ky = np.fft.fftfreq(h)[:, None]
    kx = np.fft.rfftfreq(w)[None, :]
    g = np.exp(-2 * np.pi**2 * ((sy * ky) ** 2 + (sx * kx) ** 2)).astype(np.float32)
    return np.fft.irfft2(np.fft.rfft2(a) * g, s=a.shape).astype(np.float32)


def render_density(
    d: np.ndarray,
    profile: GrainProfile,
    film_width_mm: float = 36.0,
    grain_scale: float = 1.0,
    softness_um: tuple[float, float] = (0.0, 0.0),
    seed: int | None = None,
) -> np.ndarray:
    """Add grain to a negative-density image. Returns the grainy density image."""
    h, w = d.shape
    out_pitch = film_width_mm * 1000.0 / max(h, w)
    rng = np.random.default_rng(seed)
    if out_pitch >= profile.pitch_um * (1 - 1e-6):
        # output is coarser than the scan: synthesise at scan pitch, area-average down
        scale = out_pitch / profile.pitch_um
        hr, wr = int(round(h * scale)), int(round(w * scale))
        dr = _resize_f32(d, (wr, hr), box=False)
        kernel, pitch = profile.kernel, profile.pitch_um
    else:
        hr, wr, dr = h, w, d
        kernel, pitch = profile.kernel_at_pitch(out_pitch), out_pitch
    n = _shaped_noise((hr, wr), kernel, rng)
    a = skew_coeff(profile.skew_at(dr))
    n = (n + a * (n * n - 1.0)) / np.sqrt(1.0 + 2.0 * a * a)
    g = n * profile.sigma_at(dr) * np.float32(grain_scale)
    del n, a
    if softness_um[0] > 0 or softness_um[1] > 0:
        g = _gaussian_blur_fft(g, (softness_um[0] / pitch, softness_um[1] / pitch))
    if (hr, wr) != (h, w):
        g = _resize_f32(g, (w, h), box=True)
    return (d + g).astype(np.float32)


@dataclass
class ScanCurve:
    """Scan-style negative ↔ positive relation, measured on the author's VueScan/Negative-Lab-Pro
    workflow (roll 2545 frame 7, raw DNG vs delivered JPEG): the positive is a linear stretch of
    *density* between a black point (≈ base+fog) and a white point, followed by a gamma:

        L = ((D − D_bp) / (D_wp − D_bp)) ** gamma          D = D_bp + (D_wp − D_bp) · L ** (1/gamma)

    Its log-slope dlog10(L)/dD = gamma / ((D − D_bp) ln 10) is ≈0.6 at D 1.0, ≈0.3 at D 2.0 and
    steep in the thin shadows; predicted σ_logL = slope · σ_D matched the JPEG's measured grain
    within ~10 % at every tone. gamma ≈ 1.25 fits that workflow; a contrasty print is higher.
    """

    black_point: float = 0.10
    white_point: float = 2.50
    gamma: float = 1.25
    min_offset: float = 0.05  # guards the slope in the clipped-black region

    def density(self, lin: np.ndarray) -> np.ndarray:
        f = np.clip(lin, 0.0, 1.0) ** np.float32(1.0 / self.gamma)
        return (self.black_point + (self.white_point - self.black_point) * f).astype(np.float32)

    def positive(self, d: np.ndarray) -> np.ndarray:
        """Negative density → linear positive luminance (0 at/below the black point)."""
        f = np.clip((d - self.black_point) / (self.white_point - self.black_point), 0.0, None)
        return (f ** np.float32(self.gamma)).astype(np.float32)

    def slope(self, d: np.ndarray) -> np.ndarray:
        return (np.float32(self.gamma) / (np.maximum(d - np.float32(self.black_point), np.float32(self.min_offset)) * np.float32(np.log(10.0)))).astype(np.float32)


def positive_slope(d: np.ndarray, print_gamma: float, black_point: float, min_offset: float = 0.05) -> np.ndarray:
    return ScanCurve(black_point=black_point, gamma=print_gamma, min_offset=min_offset).slope(d)


def render_image(
    lin_lum: np.ndarray,
    profile: GrainProfile,
    curve: Curve | None = None,
    negative: bool = False,
    scan: ScanCurve | None = None,
    tone: str = "positive",
    print_gamma: float | None = None,
    black_point: float | None = None,
    **kw,
) -> np.ndarray:
    """Linear luminance in → linear positive out (or negative transmittance if negative=True).

    tone="positive" (default): the input is a finished positive (a JPEG, an edited TIFF). Its
        tones are placed on the negative through the inverse ScanCurve — the same relation a
        scan of a real negative has to its delivered positive — grain is added in density, and
        the ScanCurve brings it back: L_out = P(D + ΔD). To first order that is a
        log-luminance fluctuation of slope(D)·ΔD (mean tone preserved), but it stays bounded
        near the black point where the linearised slope would explode.
    tone="scene": the input is scene-linear (from a RAW). The film H&D `curve` (with
        --exposure) decides the density; the positive is then formed with the ScanCurve slope,
        or, if print_gamma is None and tone == "scene", by inverting the film curve exactly.
    print_gamma / black_point are legacy aliases that override the ScanCurve's gamma / black point.
    """
    sc = scan or ScanCurve()
    if print_gamma is not None:
        sc = ScanCurve(black_point=sc.black_point, white_point=sc.white_point, gamma=print_gamma, min_offset=sc.min_offset)
    if black_point is not None:
        sc = ScanCurve(black_point=black_point, white_point=sc.white_point, gamma=sc.gamma, min_offset=sc.min_offset)
    if tone == "scene":
        curve = curve or Curve()
        d = curve.density(lin_lum)
    elif tone == "positive":
        d = sc.density(lin_lum)
    else:
        raise ValueError("tone must be 'positive' or 'scene'")
    dg = render_density(d, profile, **kw)
    if negative:
        return (10.0 ** (-dg)).astype(np.float32)
    if tone == "scene" and print_gamma is None and scan is None:
        return curve.inverse(dg)
    if tone == "positive":
        # exact: the input already equals sc.positive(d), so this is L_in · P(D+ΔD)/P(D) without
        # any linearisation — bounded near the black point (no exploding shadow speckles)
        return sc.positive(dg)
    base = np.maximum(sc.positive(d), np.float32(1e-6))
    return (lin_lum * sc.positive(dg) / base).astype(np.float32)


# ----------------------------------------------------------------------------- image I/O
def load_image_linear(path: str | Path, assume_linear: bool = False) -> np.ndarray:
    from PIL import Image

    im = Image.open(path)
    if im.mode in ("I;16", "I;16B", "I;16L", "I"):
        a = np.asarray(im, dtype=np.float32) / 65535.0
    elif im.mode in ("F",):
        a = np.asarray(im, dtype=np.float32)
    else:
        im = im.convert("RGB") if im.mode not in ("L", "RGB") else im
        a = np.asarray(im, dtype=np.float32) / 255.0
    if not assume_linear:
        a = srgb_to_linear(a)
    return luminance(a)


def save_image(path: str | Path, lin: np.ndarray, bits: int = 16, encode_srgb: bool = True) -> None:
    from PIL import Image

    x = linear_to_srgb(lin) if encode_srgb else np.clip(lin, 0, 1)
    if bits == 16:
        Image.fromarray((x * 65535.0 + 0.5).astype(np.uint16)).save(path)
    else:
        Image.fromarray((x * 255.0 + 0.5).astype(np.uint8)).save(path)
