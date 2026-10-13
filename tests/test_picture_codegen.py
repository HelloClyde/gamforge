"""Run the production blitter object on S1C33, not host-GCC C semantics."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_production_sys_picture_alignment_and_folded_row(tmp_path):
    clang = os.getenv("A9288_TEST_CLANG")
    emulator = os.getenv("A9288_TEST_C33EMU")
    runtime = os.getenv("A9288_TEST_T_RUNTIME")
    if not clang or not emulator or not runtime:
        pytest.skip("optional S1C33 toolchain/core/converted 9288T 1x runtime are not configured")
    # Synthetic ROM, not a copyrighted game fixture. Nontrivial bit patterns
    # exercise every packed pixel lane, scalar prefix/tail and word group.
    image = tmp_path / "synthetic.gam"
    image.write_bytes(bytes((i * 71 + (i >> 3) * 29) & 255 for i in range(81559)))
    output = tmp_path / "replay"
    script = Path(__file__).resolve().parents[1] / "scripts/verify_picture_codegen.py"
    cases = [
        "8,14,119,81",
        "0,14,111,81",
        "16,14,127,81",
        "1,64,112,66",
        "8,65,119,65",
        "152,95,158,95",
    ]
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--runtime-dir",
            runtime,
            "--toolchain",
            str(Path(clang).parent.parent),
            "--emulator",
            emulator,
            "--game",
            str(image),
            "--output-dir",
            str(output),
            *(argument for case in cases for argument in ("--rect", case)),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    report = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(report["cases"]) == len(cases)
    assert all(case["returned"] and case["ram_canaries_ok"] for case in report["cases"])
    assert all(case["framebuffer_different_bytes"] == 0 for case in report["cases"])
