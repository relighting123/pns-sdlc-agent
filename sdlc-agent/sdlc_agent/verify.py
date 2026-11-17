"""Python unittest gate that rejects zero discovered tests."""
from __future__ import annotations

import sys
import unittest


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    suite = unittest.defaultTestLoader.discover(args[0] if args else "tests")
    if suite.countTestCases() == 0:
        print("Quality gate failed: zero tests discovered", file=sys.stderr)
        return 2
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
