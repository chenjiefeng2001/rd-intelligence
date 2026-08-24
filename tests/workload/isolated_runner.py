"""Subprocess entry point for isolated reliability scenarios."""

import sys

from tests.workload import scenarios


def main():
    name = sys.argv[1]
    scenarios.SCENARIOS[name]()


if __name__ == "__main__":
    main()
