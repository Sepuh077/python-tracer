#!/usr/bin/env python3
"""
Tests for step-ordered display and exception tracking features.

Tests:
1. Step ordering: variable events and calls are interleaved correctly by step
2. Exception tracking: exceptions are captured in the originating node
3. Caught exceptions: caught exceptions are still tracked
4. CLI exception trace: trace file is saved even when script raises
5. Viewer _items(): produces correct step-ordered items
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_nodes(node, name):
    """Recursively find all nodes with the given name."""
    found = []
    if node.get("name") == name:
        found.append(node)
    for child in node.get("calls", []):
        found.extend(_find_nodes(child, name))
    return found


def _find_variable(node, var_name):
    """Find a variable by name in a node's variables list."""
    for v in node.get("variables", []):
        if v.get("name") == var_name:
            return v
    return None


# ==================== Step Ordering Tests ====================


def test_step_order_variables_and_calls():
    """Variable events and calls should be interleaved by step order."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_step_order_")

    try:
        script_path = os.path.join(test_dir, "step_order_script.py")
        with open(script_path, "w") as f:
            f.write('''
def helper():
    return 42

def main():
    x = 1
    y = 2
    z = helper()
    w = 10
    return w

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        main_nodes = _find_nodes(data["call_tree"], "main")
        assert len(main_nodes) == 1, "Should find exactly one main node"
        main_node = main_nodes[0]

        # main should have helper as a child call
        helper_calls = [c for c in main_node.get("calls", [])
                        if c.get("name") == "helper"]
        assert len(helper_calls) == 1, "main should call helper once"
        helper_call = helper_calls[0]

        # main should have variables x, y, z, w
        var_x = _find_variable(main_node, "x")
        var_y = _find_variable(main_node, "y")
        var_z = _find_variable(main_node, "z")
        var_w = _find_variable(main_node, "w")

        assert var_x is not None, "Variable x should be tracked"
        assert var_y is not None, "Variable y should be tracked"
        assert var_z is not None, "Variable z should be tracked"
        assert var_w is not None, "Variable w should be tracked"

        # Verify step ordering: x, y come before helper, z, w come after
        x_step = var_x["history"][0]["step"]
        y_step = var_y["history"][0]["step"]
        helper_step = helper_call["step_start"]
        z_step = var_z["history"][0]["step"]
        w_step = var_w["history"][0]["step"]

        assert x_step < helper_step, \
            f"x (step {x_step}) should come before helper (step {helper_step})"
        assert y_step < helper_step, \
            f"y (step {y_step}) should come before helper (step {helper_step})"
        assert z_step > helper_step, \
            f"z (step {z_step}) should come after helper (step {helper_step})"
        assert w_step > z_step, \
            f"w (step {w_step}) should come after z (step {z_step})"

        # Verify variable values
        assert var_x["history"][0]["value"] == "1"
        assert var_y["history"][0]["value"] == "2"
        assert var_z["history"][0]["value"] == "42"
        assert var_w["history"][0]["value"] == "10"

        print("✓ test_step_order_variables_and_calls passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_step_order_variable_modifications():
    """Variable modifications should appear at correct step positions."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_step_mod_")

    try:
        script_path = os.path.join(test_dir, "mod_script.py")
        with open(script_path, "w") as f:
            f.write('''
def helper():
    return 99

def main():
    x = 1
    y = 2
    x = helper()
    y = 3
    return y

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        main_nodes = _find_nodes(data["call_tree"], "main")
        assert len(main_nodes) == 1
        main_node = main_nodes[0]

        # Verify x has two history entries (assign + modify)
        var_x = _find_variable(main_node, "x")
        assert var_x is not None
        assert len(var_x["history"]) == 2, \
            f"x should have 2 history entries, got {len(var_x['history'])}"
        assert var_x["history"][0]["action"] == "assign"
        assert var_x["history"][0]["value"] == "1"
        assert var_x["history"][1]["action"] == "modify"
        assert var_x["history"][1]["value"] == "99"

        # Verify y has two history entries (assign + modify)
        var_y = _find_variable(main_node, "y")
        assert var_y is not None
        assert len(var_y["history"]) == 2, \
            f"y should have 2 history entries, got {len(var_y['history'])}"
        assert var_y["history"][0]["value"] == "2"
        assert var_y["history"][1]["value"] == "3"

        # Verify helper call step is between x=1 and x=99
        helper_calls = [c for c in main_node.get("calls", [])
                        if c.get("name") == "helper"]
        assert len(helper_calls) == 1
        helper_step = helper_calls[0]["step_start"]

        x_assign_step = var_x["history"][0]["step"]
        x_modify_step = var_x["history"][1]["step"]

        assert x_assign_step < helper_step < x_modify_step, \
            (f"helper (step {helper_step}) should be between "
             f"x=1 (step {x_assign_step}) and x=99 (step {x_modify_step})")

        print("✓ test_step_order_variable_modifications passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_viewer_items_step_order():
    """Viewer _items() should return items sorted by step."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_viewer_items_")

    try:
        script_path = os.path.join(test_dir, "items_script.py")
        with open(script_path, "w") as f:
            f.write('''
def helper():
    return 5

def main():
    a = 1
    b = helper()
    c = 3
    return c

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        # Use the Viewer class to get items
        from steptrace.viewer import Viewer
        viewer = Viewer(data)

        # Navigate to main node
        main_nodes = _find_nodes(data["call_tree"], "main")
        assert len(main_nodes) == 1
        viewer.node = main_nodes[0]

        items = viewer._items()
        assert len(items) >= 4, f"Should have at least 4 items, got {len(items)}"

        # Verify item types are mixed (not all calls then all vars)
        kinds = [item[0] for item in items]
        assert "call" in kinds, "Should have call items"
        assert "var_event" in kinds, "Should have var_event items"

        # The items should be ordered: variable events before calls and after
        # calls should be interleaved, not grouped
        call_positions = [i for i, k in enumerate(kinds) if k == "call"]
        var_positions = [i for i, k in enumerate(kinds) if k == "var_event"]

        # Some var_events should be before the call and some after
        assert any(v < call_positions[0] for v in var_positions), \
            "Some variable events should appear before the first call"
        assert any(v > call_positions[0] for v in var_positions), \
            "Some variable events should appear after the first call"

        print("✓ test_viewer_items_step_order passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== Exception Tracking Tests ====================


def test_exception_tracked_in_originating_function():
    """Exception should be recorded in the function where it was raised."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_exc_track_")

    try:
        script_path = os.path.join(test_dir, "exc_script.py")
        with open(script_path, "w") as f:
            f.write('''
def risky():
    x = 1
    raise ValueError("test error")

def main():
    try:
        risky()
    except ValueError:
        pass
    return 0

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        # Find the risky function node
        risky_nodes = _find_nodes(data["call_tree"], "risky")
        assert len(risky_nodes) == 1, "Should find risky node"
        risky_node = risky_nodes[0]

        # risky should have an exception
        exceptions = risky_node.get("exceptions", [])
        assert len(exceptions) == 1, \
            f"risky should have 1 exception, got {len(exceptions)}"

        exc = exceptions[0]
        assert exc["type"] == "ValueError", \
            f"Exception type should be ValueError, got {exc['type']}"
        assert exc["message"] == "test error", \
            f"Exception message should be 'test error', got {exc['message']}"
        assert isinstance(exc["line"], int), "Exception line should be an int"
        assert isinstance(exc["step"], int), "Exception step should be an int"
        assert isinstance(exc["traceback"], list), "Traceback should be a list"

        # main should NOT have the exception (only risky has it)
        main_nodes = _find_nodes(data["call_tree"], "main")
        assert len(main_nodes) == 1
        main_exceptions = main_nodes[0].get("exceptions", [])
        assert len(main_exceptions) == 0, \
            f"main should not have exceptions, got {len(main_exceptions)}"

        print("✓ test_exception_tracked_in_originating_function passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_exception_uncaught_tracked():
    """Uncaught exceptions should be tracked and trace should still be saved."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_exc_uncaught_")

    try:
        script_path = os.path.join(test_dir, "uncaught_script.py")
        with open(script_path, "w") as f:
            f.write('''
def boom():
    x = 42
    raise RuntimeError("kaboom")

def main():
    boom()

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        # Script should fail
        assert result.returncode != 0, "Script with uncaught exception should fail"

        # But trace file should still be saved
        assert os.path.exists(out), "Trace file should be saved even on exception"

        # Verify trace path is printed in output
        assert "Structured trace saved to:" in result.stdout, \
            "Should print trace path even on error"

        with open(out) as f:
            data = json.load(f)

        # boom should have the exception
        boom_nodes = _find_nodes(data["call_tree"], "boom")
        assert len(boom_nodes) == 1
        exceptions = boom_nodes[0].get("exceptions", [])
        assert len(exceptions) == 1, f"boom should have 1 exception, got {len(exceptions)}"
        assert exceptions[0]["type"] == "RuntimeError"
        assert exceptions[0]["message"] == "kaboom"

        print("✓ test_exception_uncaught_tracked passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_exception_with_variables():
    """Exception should appear in correct step position alongside variables."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_exc_vars_")

    try:
        script_path = os.path.join(test_dir, "exc_vars_script.py")
        with open(script_path, "w") as f:
            f.write('''
def risky():
    a = 10
    b = 20
    raise ValueError("oops")

def main():
    try:
        risky()
    except ValueError:
        pass
    return 0

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        risky_nodes = _find_nodes(data["call_tree"], "risky")
        assert len(risky_nodes) == 1
        risky_node = risky_nodes[0]

        # risky should have variables a and b
        var_a = _find_variable(risky_node, "a")
        var_b = _find_variable(risky_node, "b")
        assert var_a is not None, "Variable a should be tracked"
        assert var_b is not None, "Variable b should be tracked"

        # risky should have an exception
        exceptions = risky_node.get("exceptions", [])
        assert len(exceptions) == 1
        exc = exceptions[0]

        # Exception step should come after variable steps
        a_step = var_a["history"][0]["step"]
        b_step = var_b["history"][0]["step"]
        exc_step = exc["step"]

        assert exc_step > a_step, \
            f"Exception (step {exc_step}) should come after a (step {a_step})"
        assert exc_step > b_step, \
            f"Exception (step {exc_step}) should come after b (step {b_step})"

        print("✓ test_exception_with_variables passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_exception_in_viewer_items():
    """Viewer _items() should include exception items at correct positions."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_exc_viewer_")

    try:
        script_path = os.path.join(test_dir, "exc_viewer_script.py")
        with open(script_path, "w") as f:
            f.write('''
def risky():
    x = 1
    raise ValueError("fail")

def main():
    try:
        risky()
    except ValueError:
        pass
    return 0

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        from steptrace.viewer import Viewer
        viewer = Viewer(data)

        # Navigate to the risky node
        risky_nodes = _find_nodes(data["call_tree"], "risky")
        assert len(risky_nodes) == 1
        viewer.node = risky_nodes[0]

        items = viewer._items()
        kinds = [item[0] for item in items]

        assert "exception" in kinds, "risky's items should include an exception"
        assert "var_event" in kinds, "risky's items should include variable events"

        # Exception should be the last item (highest step)
        exc_idx = kinds.index("exception")
        assert exc_idx == len(items) - 1, \
            "Exception should be the last item in step order"

        print("✓ test_exception_in_viewer_items passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_exception_call_row_indicator():
    """Call row for a function that raised should have exceptions in its data."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_exc_indicator_")

    try:
        script_path = os.path.join(test_dir, "indicator_script.py")
        with open(script_path, "w") as f:
            f.write('''
def risky():
    raise TypeError("bad type")

def main():
    try:
        risky()
    except TypeError:
        pass
    return 0

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        from steptrace.viewer import Viewer
        viewer = Viewer(data)

        # Navigate to main
        main_nodes = _find_nodes(data["call_tree"], "main")
        assert len(main_nodes) == 1
        viewer.node = main_nodes[0]

        items = viewer._items()

        # Find the call item for risky
        call_items = [(kind, d, e) for kind, d, e in items if kind == "call"]
        risky_calls = [d for _, d, _ in call_items if d.get("name") == "risky"]
        assert len(risky_calls) == 1, "Should have one call to risky"

        # risky's call node should have exceptions
        risky_call_data = risky_calls[0]
        exceptions = risky_call_data.get("exceptions", [])
        assert len(exceptions) == 1, "risky call should show 1 exception"
        assert exceptions[0]["type"] == "TypeError"

        print("✓ test_exception_call_row_indicator passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_multiple_caught_exceptions():
    """Multiple different caught exceptions in one function should all be tracked."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_multi_exc_")

    try:
        script_path = os.path.join(test_dir, "multi_exc_script.py")
        with open(script_path, "w") as f:
            f.write('''
def risky_a():
    raise ValueError("error a")

def risky_b():
    raise TypeError("error b")

def main():
    try:
        risky_a()
    except ValueError:
        pass
    try:
        risky_b()
    except TypeError:
        pass
    return 0

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        # Both risky functions should have their exceptions
        risky_a_nodes = _find_nodes(data["call_tree"], "risky_a")
        risky_b_nodes = _find_nodes(data["call_tree"], "risky_b")

        assert len(risky_a_nodes) == 1
        assert len(risky_b_nodes) == 1

        exc_a = risky_a_nodes[0].get("exceptions", [])
        exc_b = risky_b_nodes[0].get("exceptions", [])

        assert len(exc_a) == 1, "risky_a should have 1 exception"
        assert len(exc_b) == 1, "risky_b should have 1 exception"
        assert exc_a[0]["type"] == "ValueError"
        assert exc_b[0]["type"] == "TypeError"

        print("✓ test_multiple_caught_exceptions passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_exception_traceback_content():
    """Exception traceback should contain meaningful stack information."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_exc_tb_")

    try:
        script_path = os.path.join(test_dir, "tb_script.py")
        with open(script_path, "w") as f:
            f.write('''
def deep_func():
    raise RuntimeError("deep error")

def middle_func():
    deep_func()

def main():
    try:
        middle_func()
    except RuntimeError:
        pass

main()
''')

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        deep_nodes = _find_nodes(data["call_tree"], "deep_func")
        assert len(deep_nodes) == 1
        exceptions = deep_nodes[0].get("exceptions", [])
        assert len(exceptions) == 1

        tb = exceptions[0].get("traceback", [])
        assert len(tb) > 0, "Traceback should have at least one entry"

        # Traceback should mention the script file
        tb_text = "".join(tb)
        assert "deep_func" in tb_text or "tb_script" in tb_text, \
            f"Traceback should reference the function or script: {tb_text}"

        print("✓ test_exception_traceback_content passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    print("Testing Step Order and Exception Features")
    print("=" * 60)

    # Step ordering tests
    test_step_order_variables_and_calls()
    test_step_order_variable_modifications()
    test_viewer_items_step_order()

    # Exception tracking tests
    test_exception_tracked_in_originating_function()
    test_exception_uncaught_tracked()
    test_exception_with_variables()
    test_exception_in_viewer_items()
    test_exception_call_row_indicator()
    test_multiple_caught_exceptions()
    test_exception_traceback_content()

    print("=" * 60)
    print("All step order and exception tests passed!")