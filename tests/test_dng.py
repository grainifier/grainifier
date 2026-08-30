import numpy as np

from grainifier.dng import read_vuescan_dng
from tests.conftest import write_dng


def test_roundtrip_rgb16_single_strip(tmp_path, rng):
    img = rng.integers(0, 65535, (40, 30, 3), dtype=np.uint16)
    p = write_dng(tmp_path / "a.dng", img)
    out, meta = read_vuescan_dng(p)
    assert out.shape == (40, 30, 3) and out.dtype == np.uint16
    assert np.array_equal(out, img)
    assert (meta.width, meta.height, meta.channels, meta.bits) == (30, 40, 3, 16)
    assert meta.make == "Nikon" and meta.model == "LS-50" and "VueScan" in meta.software
    assert meta.dpi == 4000 and meta.white_level == 65535


def test_roundtrip_multistrip_and_bytes_input(tmp_path, rng):
    img = rng.integers(0, 65535, (37, 23, 3), dtype=np.uint16)
    p = write_dng(tmp_path / "b.dng", img, rows_per_strip=4)
    out, _ = read_vuescan_dng(p.read_bytes())
    assert np.array_equal(out, img)


def test_greyscale_and_rgbi(tmp_path, rng):
    g = rng.integers(0, 65535, (12, 16), dtype=np.uint16)
    out, meta = read_vuescan_dng(write_dng(tmp_path / "g.dng", g))
    assert out.shape == (12, 16, 1) and meta.channels == 1 and np.array_equal(out[..., 0], g)
    i4 = rng.integers(0, 65535, (12, 16, 4), dtype=np.uint16)
    out, meta = read_vuescan_dng(write_dng(tmp_path / "i.dng", i4))
    assert out.shape == (12, 16, 4) and np.array_equal(out, i4)


def test_rejects_non_tiff(tmp_path):
    p = tmp_path / "x.dng"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    import pytest

    with pytest.raises(ValueError):
        read_vuescan_dng(p)
