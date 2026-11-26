"""MCAP folder -> flat folder of .rrd (imuninn to-rrd / browse), no viewer, no server."""

import os
import subprocess

import pytest

from imuninn import rrd_dataset as rd

pytest.importorskip("rerun")
from test_rerun_bridge import make_synthetic_mcap  # noqa: E402


@pytest.fixture
def runs(tmp_path):
    """runs/a/top.mcap, runs/b/top.mcap, runs/b/side.mcap, plus an output-like folder to skip."""
    root = tmp_path / "runs"
    for rel in ("a/top.mcap", "b/top.mcap", "b/side.mcap"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        make_synthetic_mcap(root / rel, seconds=0.5)
    (root / "_rerun-old").mkdir()
    (root / "_rerun-old" / "x.mcap").write_bytes(b"not scanned")
    return root


def test_plan_names_and_skips_output_folders(runs):
    out, jobs = rd.plan(runs)
    assert out == runs.resolve() / "_rerun"
    assert [j.recording_id for j in jobs] == ["a/top", "b/side", "b/top"]
    assert [j.dst.name for j in jobs] == ["a__top.rrd", "b__side.rrd", "b__top.rrd"]
    assert not any(j.up_to_date for j in jobs)


def test_out_dir_name_per_setting():
    assert rd.Options().out_dir_name() == "_rerun"
    assert rd.Options(video="decode").out_dir_name() == "_rerun-decode"
    assert rd.Options(video="decode", scale=0.5).out_dir_name() == "_rerun-decode-scale0.5"
    assert rd.Options(video="off", frames="raw").out_dir_name() == "_rerun-novideo-raw"


def test_estimate_stream_is_about_mcap_size(runs):
    _, jobs = rd.plan(runs)
    size, secs = rd.estimate(jobs, rd.Options(), workers=2)
    total = sum(j.size for j in jobs)
    assert total <= size <= 1.2 * total
    assert secs > 0
    big, _ = rd.estimate(jobs, rd.Options(video="decode"), workers=2)
    assert big > 10 * size


def test_convert_then_up_to_date(runs):
    out, jobs = rd.plan(runs)
    failed = rd.convert(jobs, out, rd.Options(), workers=2, progress=lambda m: None)
    assert failed == []
    files = sorted(p.name for p in out.iterdir())
    assert files == ["a__top.rrd", "b__side.rrd", "b__top.rrd"]
    assert all((out / f).stat().st_size > 0 for f in files)

    _, again = rd.plan(runs)
    assert all(j.up_to_date for j in again)
    _, forced = rd.plan(runs, force=True)
    assert not any(j.up_to_date for j in forced)

    # a newer MCAP is converted again
    src = runs / "a" / "top.mcap"
    later = (out / "a__top.rrd").stat().st_mtime + 10
    os.utime(src, (later, later))
    _, after_touch = rd.plan(runs)
    assert [j.recording_id for j in after_touch if not j.up_to_date] == ["a/top"]


def test_recording_id_is_stored(runs, tmp_path):
    """The dataset shows the recording id as the segment name: it must be the relative path."""
    out, jobs = rd.plan(runs / "a" / "top.mcap", tmp_path / "o")
    assert [j.recording_id for j in jobs] == ["top"]
    rd.convert(jobs, out, rd.Options(), workers=1, progress=lambda m: None)
    r = subprocess.run([rd.rerun_executable(), "rrd", "print", str(out / "top.rrd")], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("this rerun has no `rrd print`")
    head = r.stdout[:2000]
    assert '"imuninn-replay"' in head and '"top"' in head


def test_cli_to_rrd(runs, tmp_path, capsys):
    from imuninn.cli import main

    out = tmp_path / "rrd"
    main(["to-rrd", str(runs), "-o", str(out), "-j", "2"])
    text = capsys.readouterr().out
    assert "found 3 MCAP file(s)" in text and "converted 3 of 3" in text
    assert len(list(out.glob("*.rrd"))) == 3


def test_cli_browse_asks_first(runs, monkeypatch, capsys):
    from imuninn.cli import main

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    with pytest.raises(SystemExit, match="cancelled"):
        main(["browse", str(runs)])
    assert "estimated:" in capsys.readouterr().out
    assert not (runs / "_rerun").exists()


def test_device_names(runs):
    _, jobs = rd.plan(runs)
    assert rd.device_names(jobs) == ["synthetic_iphone"]
