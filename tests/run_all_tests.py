#!/usr/bin/env python3
"""
Main test runner for all steptrace tests.
Run this script to execute all test suites.
"""

import os
import subprocess
import sys

# Get the directory containing this script
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TEST_DIR)

# Add project root to path
sys.path.insert(0, PROJECT_ROOT)


def run_test_file(filename):
    """Run a single test file and return success status."""
    filepath = os.path.join(TEST_DIR, filename)
    print(f"\n{'=' * 60}")
    print(f"Running: {filename}")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, filepath], cwd=PROJECT_ROOT, capture_output=False
    )

    return result.returncode == 0


def main():
    """Run all test files."""
    test_files = [
        "test_log_level.py",
        "test_log_output.py",
        "test_variable_mode.py",
        "test_all_options.py",
        "test_config.py",
        "test_async_tracer.py",
        "test_cli.py",
        "test_class_filter_and_type_config.py",
    ]

    print("\n" + "=" * 60)
    print("STEPTRACE TEST SUITE")
    print("=" * 60)

    results = {}
    for test_file in test_files:
        results[test_file] = run_test_file(test_file)

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    all_passed = True
    for test_file, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{status}: {test_file}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
