import json

import numpy as np
import pytest
from PIL import Image

from grainifier.cli import main
from tests.conftest import correlated_noise, density_to_uint16, write_dng


def test_frame_aggregate_render_pipeline(tmp_path, rng, capsys):
    pytest.importorskip("matplotlib")
    frames = tmp_path / "frames" / "roll-a"
    frames.mkdir(parents=True)
    for i in range(2):
        d = 1.0 + 0.1 * correlated_noise((768, 768), rng)
        dng = write_dng(tmp_path / f"f{i}.dng", density_to_uint16(d))
        main(["frame", str(dng), "-o", str(frames / f"f{i}.npz")])
    out = capsys.readouterr().out
    assert '"width": 768' in out
    prof = tmp_path / "p.json"
    main(["aggregate", str(tmp_path / "frames"), "-o", str(prof), "--plots", str(tmp_path / "plots"),
          "--min-width", "500", "--stock", "Test", "--ei", "100"])
    doc = json.loads(prof.read_text())
    assert doc["stock"] == "Test" and doc["n_frames"] == 2 and "roll-a" in doc["per_roll"]
    assert (tmp_path / "plots" / "sigma_vs_density.png").exists()
    img = tmp_path / "in.png"
    Image.fromarray(np.tile(np.linspace(0, 255, 200, dtype=np.uint8), (100, 1))).save(img)
    main(["render", str(img), str(tmp_path / "out.png"), "--profile", str(prof), "--seed", "1", "--film-width-mm", "1.27"])
    o = np.asarray(Image.open(tmp_path / "out.png"))
    assert o.shape == (100, 200) and o.dtype == np.uint16 and o.std() > 0


def test_profiles_and_render_by_name(tmp_path, capsys):
    main(["profiles"])
    assert "hp5-plus-ei1600-1pass" in capsys.readouterr().out
    img = tmp_path / "in.jpg"
    Image.fromarray(np.full((64, 96, 3), 120, np.uint8)).save(img)
    main(["render", str(img), str(tmp_path / "o.png"), "--profile", "bwxx-1pass", "--bits", "8", "--seed", "2"])
    o = np.asarray(Image.open(tmp_path / "o.png"))
    assert o.dtype == np.uint8 and o.shape == (64, 96)


def test_scancurve_recovers_known_curve(tmp_path, rng, capsys):
    """A synthetic raw DNG and a positive made with a known ScanCurve → the fit recovers it."""
    from grainifier.render import ScanCurve, linear_to_srgb

    sc = ScanCurve(black_point=0.08, white_point=2.4, gamma=1.6)
    for i, frame in enumerate((3, 12)):
        # a smooth scene covering the density range, plus grain
        yy, xx = np.mgrid[0:600, 0:900] / 600.0
        d = (0.2 + 2.0 * (0.5 + 0.5 * np.sin(3 * xx) * np.cos(2 * yy))).astype(np.float32)
        d = d + 0.06 * correlated_noise(d.shape, rng)
        raw = write_dng(tmp_path / f"raw7777-{frame:04d}.dng", density_to_uint16(d))
        pos = tmp_path / f"inv7777-{frame:04d}.png"
        Image.fromarray((linear_to_srgb(sc.positive(d)) * 255 + 0.5).astype(np.uint8)).save(pos)
    out = tmp_path / "preset.json"
    main(["scancurve", str(tmp_path / "raw7777-0003.dng"), str(tmp_path / "raw7777-0012.dng"),
          str(tmp_path / "inv7777-0003.png"), str(tmp_path / "inv7777-0012.png"), "--write", str(out)])
    text = capsys.readouterr().out
    assert "7777-3" in text and "7777-12" in text and "wrote" in text
    doc = json.loads(out.read_text())
    assert abs(doc["black_point"] - 0.08) < 0.06
    assert abs(doc["white_point"] - 2.4) < 0.15
    assert abs(doc["gamma"] - 1.6) / 1.6 < 0.1
    # the written preset is accepted by render
    img = tmp_path / "in.jpg"
    Image.fromarray(np.full((48, 64, 3), 100, np.uint8)).save(img)
    main(["render", str(img), str(tmp_path / "o.png"), "--profile", "bwxx-1pass", "--scan-preset", str(out), "--bits", "8", "--seed", "1"])
    assert (tmp_path / "o.png").exists()
