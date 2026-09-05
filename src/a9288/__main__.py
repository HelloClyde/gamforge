"""GUI, CLI and a restricted subprocess entry point share one implementation."""

import argparse
import importlib
import sys

WORKERS = {"cli", "compiler.build", "compiler.backend"}


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if args[:1] == ["--worker"]:
        if len(args) < 2 or args[1] not in WORKERS:
            raise SystemExit("Unknown compiler worker")
        module = importlib.import_module("a9288." + args[1])
        sys.argv = [sys.argv[0], *args[2:]]
        return module.main()
    if args[:1] == ["convert"]:
        from a9288.cli import main as convert

        sys.argv = [sys.argv[0], *args[1:]]
        return convert()
    if args[:1] == ["--self-test"]:
        from a9288.selftest import main as selftest

        return selftest()
    if not args or args == ["gui"]:
        from a9288.gui import main as gui

        sys.argv = [sys.argv[0]]
        return gui()
    from a9288 import __version__

    parser = argparse.ArgumentParser(
        description="A 系列 9288 翻译器：PC 离线生成 S1C33 / KF2 原生程序"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.epilog = "命令：gui | convert GAME --sdk PATH --toolchain PATH --rom8 PATH --rome PATH"
    parser.parse_args(args)


if __name__ == "__main__":
    main()
