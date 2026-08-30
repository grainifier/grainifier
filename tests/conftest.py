"""Shared fixtures: a minimal VueScan-style DNG writer and synthetic grain fields."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest


def write_dng(path: Path, img: np.ndarray, rows_per_strip: int | None = None, software: str = "VueScan 9 a64 (9.8.46)") -> Path:
    """Write an uncompressed little-endian TIFF/DNG (LinearRaw) the way VueScan lays it out:
    a tiny thumbnail IFD0 plus the main image in a SubIFD."""
    h, w = img.shape[:2]
    spp = 1 if img.ndim == 2 else img.shape[2]
    bps = 16 if img.dtype == np.uint16 else 8
    data = np.ascontiguousarray(img).tobytes()
    rps = rows_per_strip or h
    row_bytes = w * spp * bps // 8
    strips = [(i * rps * row_bytes, min(rps, h - i * rps) * row_bytes) for i in range((h + rps - 1) // rps)]
    thumb = np.zeros((4, 4, 3), np.uint8).tobytes()

    def ifd(entries: list[tuple[int, int, int, bytes]], ifd_off: int, next_ifd: int = 0):
        """entries: (tag, type, count, packed value bytes). Returns (ifd bytes, extra data bytes)."""
        entries = sorted(entries)
        n = len(entries)
        extra = b""
        extra_off = ifd_off + 2 + 12 * n + 4
        out = struct.pack("<H", n)
        for tag, typ, cnt, val in entries:
            if len(val) <= 4:
                out += struct.pack("<HHI", tag, typ, cnt) + val.ljust(4, b"\x00")
            else:
                out += struct.pack("<HHI", tag, typ, cnt) + struct.pack("<I", extra_off + len(extra))
                extra += val + (b"\x00" if len(val) % 2 else b"")
        out += struct.pack("<I", next_ifd)
        return out, extra

    # layout: header | IFD0 (+extra) | SubIFD (+extra) | thumb | image
    def build(sub_off, thumb_off, img_off):
        sub_entries = [
            (254, 4, 1, struct.pack("<I", 0)), (256, 4, 1, struct.pack("<I", w)), (257, 4, 1, struct.pack("<I", h)),
            (258, 3, spp, struct.pack("<%dH" % spp, *([bps] * spp))), (259, 3, 1, struct.pack("<H", 1)),
            (262, 3, 1, struct.pack("<H", 34892)), (277, 3, 1, struct.pack("<H", spp)), (278, 4, 1, struct.pack("<I", rps)),
            (273, 4, len(strips), struct.pack("<%dI" % len(strips), *[img_off + o for o, _ in strips])),
            (279, 4, len(strips), struct.pack("<%dI" % len(strips), *[c for _, c in strips])),
            (282, 5, 1, struct.pack("<II", 4000, 1)),
        ]
        sub, sub_extra = ifd(sub_entries, sub_off)
        ifd0_entries = [
            (254, 4, 1, struct.pack("<I", 1)), (256, 4, 1, struct.pack("<I", 4)), (257, 4, 1, struct.pack("<I", 4)),
            (258, 3, 3, struct.pack("<3H", 8, 8, 8)), (259, 3, 1, struct.pack("<H", 1)), (262, 3, 1, struct.pack("<H", 2)),
            (271, 2, 6, b"Nikon\x00"), (272, 2, 6, b"LS-50\x00"), (277, 3, 1, struct.pack("<H", 3)),
            (273, 4, 1, struct.pack("<I", thumb_off)), (278, 4, 1, struct.pack("<I", 4)), (279, 4, 1, struct.pack("<I", len(thumb))),
            (305, 2, len(software) + 1, software.encode() + b"\x00"), (330, 4, 1, struct.pack("<I", sub_off)),
            (50708, 2, 12, b"Vuescan RAW\x00"),
        ]
        ifd0, ifd0_extra = ifd(ifd0_entries, 8)
        return ifd0 + ifd0_extra, sub + sub_extra

    ifd0_blob, sub_blob = build(0, 0, 0)
    sub_off = 8 + len(ifd0_blob)
    thumb_off = sub_off + len(sub_blob)
    img_off = thumb_off + len(thumb)
    ifd0_blob, sub_blob = build(sub_off, thumb_off, img_off)
    assert len(ifd0_blob) == sub_off - 8 and thumb_off == sub_off + len(sub_blob)
    path.write_bytes(b"II*\x00" + struct.pack("<I", 8) + ifd0_blob + sub_blob + thumb + data)
    return path


def correlated_noise(shape, rng, lag1_x=0.55, lag1_y=0.30):
    """Unit-variance Gaussian field with a separable exponential autocorrelation."""
    h, w = shape
    white = rng.standard_normal(shape, dtype=np.float32)
    ky = np.fft.fftfreq(h)[:, None]
    kx = np.fft.rfftfreq(w)[None, :]
    # exponential autocorrelation rho^|k| has power spectrum (1-r^2)/(1-2r cos(2pi f)+r^2)
    def spec(r, f):
        return (1 - r * r) / (1 - 2 * r * np.cos(2 * np.pi * f) + r * r)
    amp = np.sqrt(spec(lag1_y, ky) * spec(lag1_x, kx)).astype(np.float32)
    n = np.fft.irfft2(np.fft.rfft2(white) * amp, s=shape).astype(np.float32)
    return n / n.std()


def density_to_uint16(d: np.ndarray, channels: int = 3) -> np.ndarray:
    t = np.clip(10.0 ** (-d), 0, 1)
    u = (t * 65535 + 0.5).astype(np.uint16)
    return np.repeat(u[..., None], channels, axis=-1)


@pytest.fixture
def rng():
    return np.random.default_rng(1234)
