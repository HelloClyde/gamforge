"""Resolve diagnostic boundary PCs with the EXACT EXE's sidecar (PC only).

Usage: python scripts/analyze_native_profile.py NATIVE.LOG GAME.profile-symbols.json
No guest binary, source code, or logs are uploaded anywhere.
"""

import argparse
import json
import re
from pathlib import Path


def resolve(pc, symbols):
    if not pc:
        return "session"
    # A return address can equal the end of a function. Resolve the last
    # byte of CALL, not the next symbol; do not guess a CALL instruction size.
    address = pc - 1
    candidates = [s for s in symbols if s["address"] <= address < s["address"] + s["size"]]
    if not candidates:
        return f"unmapped 0x{pc:08x}"
    symbol = max(candidates, key=lambda item: item["address"])
    name = symbol["name"]
    match = re.fullmatch(r"c6502_game_fn_([0-9a-f]+)", name)
    if match:
        name = f"GAM+0x{int(match[1], 16):05x}"
    return f"{name} native+0x{pc - symbol['address']:x}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("symbols", type=Path)
    args = parser.parse_args()
    lines = args.log.read_text(encoding="gbk", errors="replace").splitlines()
    sidecar = json.loads(args.symbols.read_text(encoding="utf-8"))
    if "build=" + sidecar["build"] not in lines:
        raise SystemExit("Log build does not match this sidecar")
    print("Use the exact tested EXE. Sidecar EXE SHA256:", sidecar["exe_sha256"])
    print("Edges locate execution BETWEEN boundaries, not exclusive function CPU time.")
    names, rows, pending = {0: "session"}, {}, None
    for line in lines:
        if line.startswith("profile_name_id,"):
            pending = int(line.split(",")[1])
        elif line.startswith("profile_name=") and pending is not None:
            names[pending] = line.split("=", 1)[1]
        elif line.startswith(
            ("profile_edge,", "profile_bridge,", "profile_spike,", "profile_keygap,")
        ):
            tag, *values = line.split(",")
            rows.setdefault(tag, []).append(list(map(int, values)))
        elif line.startswith(
            (
                "profile_other_match=",
                "profile_edge_overflow_ticks=",
                "profile_gap_other_ticks=",
                "profile_measured_bridge_other_ticks=",
            )
        ):
            print(line)
    for tag, weight in (("profile_edge", 5), ("profile_spike", 5), ("profile_keygap", 5)):
        print("\n" + tag + " (top 16)")
        for row in sorted(rows.get(tag, []), key=lambda row: row[weight], reverse=True)[:16]:
            left = resolve(row[1], sidecar["symbols"])
            right = resolve(row[3], sidecar["symbols"])
            print(
                f"{row[weight] / 256:.3f}s: {names.get(row[0], row[0])} [{left}] -> "
                f"{names.get(row[2], row[2])} [{right}] | {row[4:]}"
            )
    print("\nMeasured bridge OTHER ticks (sampled helper values are NOT totals)")
    for row in sorted(rows.get("profile_bridge", []), key=lambda row: row[4], reverse=True)[:24]:
        print(names.get(row[0], row[0]), "calls/samples/wall/other/max:", row[1:])


if __name__ == "__main__":
    main()
