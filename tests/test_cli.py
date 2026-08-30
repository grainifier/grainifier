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
