"""Build the redistributable PC-only boot exporter from its GPL source."""

import argparse

from a9288.compiler.boot import build_helper, bundled_helper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    build_helper(bundled_helper(), args.cc)
    print(bundled_helper())


if __name__ == "__main__":
    main()
