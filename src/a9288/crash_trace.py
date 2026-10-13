"""Validate reboot-surviving GAMForge snapshots and symbolize their last caller."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_snapshot(path: Path) -> dict:
    raw = path.read_bytes()
    marker = b"checksum_fnv1a32="
    at = raw.rfind(marker)
    if at < 0 or not raw.startswith(b"[GAMFORGE CRASH TRACE 1]\n"):
        raise ValueError("不是完整的 GAMForge 崩溃追踪快照")
    tail = raw[at:].splitlines()
    if len(tail) != 2 or tail[1] != b"[END]":
        raise ValueError("快照写入未完成")
    checksum = 2166136261
    for byte in raw[:at]:
        checksum = ((checksum ^ byte) * 16777619) & 0xFFFFFFFF
    if int(tail[0][len(marker) :], 16) != checksum:
        raise ValueError("快照校验失败，可能在写入时重启")
    metadata, events = {}, []
    for line in raw[:at].decode("gbk").splitlines():
        if line.startswith("event,"):
            fields = [int(v, 16) for v in line.split(",")[1:]]
            if len(fields) != 32:
                raise ValueError("追踪事件字段数不匹配")
            events.append(fields)
        elif "=" in line:
            key, value = line.split("=", 1)
            metadata[key] = value
    if not events:
        raise ValueError("快照没有事件")
    for key in ("session_tick", "snapshot_sequence", "events_total"):
        metadata[key] = int(metadata[key], 16)
    if events[-1][0] != metadata["events_total"]:
        raise ValueError("快照事件序号不匹配")
    return {"path": str(path.resolve()), "metadata": metadata, "events": events}


def latest_snapshot(snapshots: list[dict]) -> dict:
    if not snapshots:
        raise ValueError("没有可用的完整快照")
    latest = snapshots[0]
    for candidate in snapshots[1:]:
        left, right = candidate["metadata"], latest["metadata"]
        delta = (left["session_tick"] - right["session_tick"]) & 0xFFFFFFFF
        if 0 < delta < 0x80000000 or (
            not delta and left["snapshot_sequence"] > right["snapshot_sequence"]
        ):
            latest = candidate
    return latest


def describe(snapshot: dict, symbols: dict | None = None) -> dict:
    meta, last = snapshot["metadata"], snapshot["events"][-1]
    result = {
        "file": snapshot["path"],
        "game": meta.get("game"),
        "target": meta.get("target"),
        "status": meta["status"],
        "last_bridge": meta.get("last_bridge"),
        "pending_call": last[1] == 0,
        "native_caller_return_pc": f"{last[4]:08X}",
        "bridge_entry_host_sp": f"{last[5]:08X}",
        "guest_software_sp": f"{last[16]:08X}",
        "stack_snapshot_valid": bool(last[23]),
        "stack_words": [f"{v:08X}" for v in last[24:28]],
        "exact_fault_pc_available": False,
    }
    host_exit = last[1] in (5, 6)
    if host_exit:
        result.update(
            pending_call=last[1] == 5,
            last_bridge=None,
            phase="host_exit",
            exit_stage=meta.get("exit_stage", "unknown"),
            exit_stage_id=last[3],
            exit_step_returned=last[1] == 6,
            exit_detail=meta.get("exit_detail"),
        )
    if symbols is not None:
        if symbols.get("game_sha256") != meta.get("game_sha256"):
            raise ValueError("符号表与游戏指纹不匹配")
        if (
            meta.get("build_id", "unknown") != "unknown"
            and symbols.get("build_id") != meta["build_id"]
        ):
            raise ValueError("符号表与 EXE 构建不匹配，即使是同一 GAM 也不能混用")
        if not host_exit:
            result["last_bridge"] = symbols.get("bridge_names", {}).get(
                str(last[3]), result["last_bridge"]
            )
        # CALL's return PC is after the call, not the failing instruction.
        for symbol in symbols.get("symbols", []):
            if symbol["address"] <= last[4] - 2 < symbol["address"] + symbol["size"]:
                result["native_caller_symbol"] = symbol["name"]
                break
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--symbols", type=Path, help="转换输出的 .debug-symbols.json")
    args = parser.parse_args()
    valid, rejected = [], []
    for path in args.logs:
        try:
            valid.append(read_snapshot(path))
        except (OSError, ValueError) as exc:
            rejected.append({"file": str(path), "error": str(exc)})
    try:
        symbols = json.loads(args.symbols.read_text(encoding="utf-8")) if args.symbols else None
        result = describe(latest_snapshot(valid), symbols)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"无法分析：{exc}\n")
    result["rejected_snapshots"] = rejected
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
