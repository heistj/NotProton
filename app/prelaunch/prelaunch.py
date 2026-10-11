#!/usr/bin/env python3
# Runs before NotProton opens, from launcher.sh. A non-zero exit blocks the launch
# and shows what this script printed to stderr.

import sys

import crossover_update


def main() -> int:
    crossover_update.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
