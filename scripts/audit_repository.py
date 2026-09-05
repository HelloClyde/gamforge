"""Guard the public Git index against private inputs and generated game outputs."""

import subprocess
from pathlib import Path


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").split("\0")
    allowed = {"src/a9288/data/icons/ico1.bin", "src/a9288/data/icons/ico2.bin"}
    forbidden = {".gam", ".sav", ".rom", ".exe", ".elf", ".o", ".raw", ".flat", ".map", ".log"}
    bad = [
        n
        for n in names
        if n
        and (
            Path(n).suffix.lower() in forbidden
            or (Path(n).suffix.lower() == ".bin" and n not in allowed)
        )
    ]
    if bad:
        raise SystemExit("Private/generated files must not be tracked:\n" + "\n".join(bad))
    print(f"Public-source audit passed: {sum(bool(n) for n in names)} tracked files")


if __name__ == "__main__":
    main()
