#!/usr/bin/env python3
"""
Tests for:
1. Class body filtering – class definitions should NOT appear as function
   calls in the structured trace.
2. Type config – extra properties listed in a Python config file should
   be serialized alongside __dict__ attributes.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steptrace.structured_tracer import StructuredTracer, load_type_config


# ── Helpers ──────────────────────────────────────────────────────────────────


def _trace_and_load(func, type_config=None):
    """Run *func* under a StructuredTracer and return the parsed call tree."""
    log_dir = tempfile.mkdtemp(prefix="steptrace_test_cf_")
    export_path = os.path.join(log_dir, "trace.json")
    try:
        tracer = StructuredTracer(
            export_path=export_path,
            script_path="<test>",
            log_dir=log_dir,
            type_config=type_config,
        )
        with tracer:
            func()
        with open(export_path) as f:
            data = json.load(f)
        return data["call_tree"]
    finally:
        shutil.rmtree(log_dir, ignore_errors=True)


def _find_nodes(node, name):
    """Recursively find all nodes with the given name."""
    found = []
    if node.get("name") == name:
        found.append(node)
    for child in node.get("calls", []):
        found.extend(_find_nodes(child, name))
    return found


def _child_names(node):
    """Return direct children's names."""
    return [c["name"] for c in node.get("calls", [])]


def _find_variable(node, var_name):
    """Find a variable by name in a node's variables list."""
    for v in node.get("variables", []):
        if v.get("name") == var_name:
            return v
    return None


def get_project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══════════════════════════════════════════════════════════════════════
#  1. Class body filtering tests
# ══════════════════════════════════════════════════════════════════════


def test_class_body_not_in_trace():
    """Class definitions should not appear as function calls."""

    class MyClass:
        def __init__(self, x):
            self.x = x

    def run():
        obj = MyClass(42)
        _ = obj.x

    tree = _trace_and_load(run)
    nodes = _find_nodes(tree, "MyClass")

    # The ONLY occurrences should be methods (kind=method), not bare calls
    for n in nodes:
        assert n["kind"] == "method", (
            f"Expected kind 'method' for MyClass node, got '{n['kind']}'"
        )
    print("  pass test_class_body_not_in_trace")


def test_multiple_classes_filtered():
    """Multiple class definitions should all be filtered."""

    class Alpha:
        pass

    class Beta:
        pass

    class Gamma:
        pass

    def run():
        a = Alpha()
        b = Beta()
        c = Gamma()

    tree = _trace_and_load(run)

    for cls_name in ("Alpha", "Beta", "Gamma"):
        nodes = _find_nodes(tree, cls_name)
        # No node at all, or only method-kind nodes
        for n in nodes:
            assert n["kind"] in ("method",), (
                f"{cls_name} should not appear as kind='{n['kind']}'"
            )
    print("  pass test_multiple_classes_filtered")


def test_class_methods_still_traced():
    """Methods on class instances should still appear in the trace."""

    class Counter:
        def __init__(self, start=0):
            self.value = start

        def increment(self):
            self.value += 1

    def run():
        c = Counter(0)
        c.increment()
        c.increment()

    tree = _trace_and_load(run)

    # __init__ should be traced as a method
    init_nodes = _find_nodes(tree, "__init__")
    assert len(init_nodes) >= 1, "Counter.__init__ should be traced"
    for n in init_nodes:
        assert n["kind"] == "method"

    # increment should be traced as a method
    inc_nodes = _find_nodes(tree, "increment")
    assert len(inc_nodes) == 2, f"Expected 2 increment calls, got {len(inc_nodes)}"
    for n in inc_nodes:
        assert n["kind"] == "method"
        assert n["class_name"] == "Counter"

    print("  pass test_class_methods_still_traced")


def test_nested_class_filtered():
    """A class defined inside a function should also be filtered."""

    def run():
        class Inner:
            def greet(self):
                return "hello"

        obj = Inner()
        obj.greet()

    tree = _trace_and_load(run)

    nodes = _find_nodes(tree, "Inner")
    for n in nodes:
        assert n["kind"] == "method", (
            f"Nested class 'Inner' should not appear as kind='{n['kind']}'"
        )

    greet_nodes = _find_nodes(tree, "greet")
    assert len(greet_nodes) == 1
    assert greet_nodes[0]["kind"] == "method"
    print("  pass test_nested_class_filtered")


def test_class_filter_via_cli():
    """Class bodies should also be filtered when running via CLI --export."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_test_cf_cli_")
    try:
        script = os.path.join(test_dir, "classes.py")
        with open(script, "w") as f:
            f.write("""
class Dog:
    def __init__(self, name):
        self.name = name
    def bark(self):
        return "woof"

class Cat:
    def __init__(self, name):
        self.name = name

def main():
    d = Dog("Rex")
    d.bark()
    c = Cat("Whiskers")

main()
""")
        export = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script, "--export", export],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(export) as f:
            data = json.load(f)

        root = data["call_tree"]
        top_names = _child_names(root)
        assert "Dog" not in top_names, f"Dog class body should be filtered, got {top_names}"
        assert "Cat" not in top_names, f"Cat class body should be filtered, got {top_names}"
        assert "main" in top_names, f"main() should remain, got {top_names}"

        # Methods should still be present
        bark_nodes = _find_nodes(root, "bark")
        assert len(bark_nodes) == 1
        assert bark_nodes[0]["kind"] == "method"

        print("  pass test_class_filter_via_cli")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_inheritance_class_bodies_filtered():
    """Class bodies for classes using inheritance should also be filtered."""

    class Base:
        def __init__(self):
            self.base_val = 1

    class Child(Base):
        def __init__(self):
            super().__init__()
            self.child_val = 2

    def run():
        c = Child()
        _ = c.child_val

    tree = _trace_and_load(run)

    for cls_name in ("Base", "Child"):
        nodes = _find_nodes(tree, cls_name)
        for n in nodes:
            assert n["kind"] == "method", (
                f"{cls_name} should not appear as kind='{n['kind']}'"
            )
    print("  pass test_inheritance_class_bodies_filtered")


# ══════════════════════════════════════════════════════════════════════
#  2. Type config tests
# ══════════════════════════════════════════════════════════════════════


def test_load_type_config_single_string():
    """load_type_config should normalise a single string to a list."""
    import numpy as np

    cfg_dir = tempfile.mkdtemp(prefix="steptrace_test_tc_")
    try:
        cfg_path = os.path.join(cfg_dir, "tc.py")
        with open(cfg_path, "w") as f:
            f.write("import numpy as np\nCONFIG = {np.ndarray: 'shape'}\n")

        result = load_type_config(cfg_path)
        assert np.ndarray in result
        assert result[np.ndarray] == ["shape"]
        print("  pass test_load_type_config_single_string")
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def test_load_type_config_list():
    """load_type_config should keep lists as-is."""
    import numpy as np

    cfg_dir = tempfile.mkdtemp(prefix="steptrace_test_tc_")
    try:
        cfg_path = os.path.join(cfg_dir, "tc.py")
        with open(cfg_path, "w") as f:
            f.write(
                "import numpy as np\n"
                "CONFIG = {np.ndarray: ['shape', 'dtype', 'size']}\n"
            )
        result = load_type_config(cfg_path)
        assert result[np.ndarray] == ["shape", "dtype", "size"]
        print("  pass test_load_type_config_list")
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def test_load_type_config_missing_config_raises():
    """load_type_config should raise if CONFIG is missing."""
    cfg_dir = tempfile.mkdtemp(prefix="steptrace_test_tc_")
    try:
        cfg_path = os.path.join(cfg_dir, "bad.py")
        with open(cfg_path, "w") as f:
            f.write("X = 1\n")  # no CONFIG

        try:
            load_type_config(cfg_path)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        print("  pass test_load_type_config_missing_config_raises")
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def test_load_type_config_bad_type_raises():
    """load_type_config should raise if CONFIG is not a dict."""
    cfg_dir = tempfile.mkdtemp(prefix="steptrace_test_tc_")
    try:
        cfg_path = os.path.join(cfg_dir, "bad.py")
        with open(cfg_path, "w") as f:
            f.write("CONFIG = [1, 2, 3]\n")

        try:
            load_type_config(cfg_path)
            assert False, "Should have raised TypeError"
        except TypeError:
            pass
        print("  pass test_load_type_config_bad_type_raises")
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def test_type_config_numpy_shape_exported():
    """numpy.ndarray.shape should be exported when configured."""
    import numpy as np

    type_config = {np.ndarray: ["shape"]}

    def run():
        arr = np.zeros((3, 4))
        _ = arr.shape

    tree = _trace_and_load(run, type_config=type_config)

    run_nodes = _find_nodes(tree, "run")
    assert len(run_nodes) == 1

    var = _find_variable(run_nodes[0], "arr")
    assert var is not None, "Variable 'arr' should be tracked"

    # Find history entry with value_data
    found_shape = False
    for h in var.get("history", []):
        vd = h.get("value_data")
        if vd and "shape" in vd:
            assert vd["shape"]["value"] == "(3, 4)"
            found_shape = True

    assert found_shape, "shape should appear in value_data for ndarray"
    print("  pass test_type_config_numpy_shape_exported")


def test_type_config_multiple_props():
    """Multiple properties should all be exported."""
    import numpy as np

    type_config = {np.ndarray: ["shape", "dtype", "size"]}

    def run():
        arr = np.ones((2, 5), dtype=np.int32)
        _ = arr

    tree = _trace_and_load(run, type_config=type_config)

    run_nodes = _find_nodes(tree, "run")
    assert len(run_nodes) == 1

    var = _find_variable(run_nodes[0], "arr")
    assert var is not None

    found = False
    for h in var.get("history", []):
        vd = h.get("value_data")
        if vd and "shape" in vd:
            found = True
            assert "shape" in vd, "shape should be exported"
            assert "dtype" in vd, "dtype should be exported"
            assert "size" in vd, "size should be exported"
            assert vd["shape"]["value"] == "(2, 5)"
            assert vd["size"]["value"] == "10"

    assert found, "value_data with properties should exist"
    print("  pass test_type_config_multiple_props")


def test_type_config_no_config_no_extra_props():
    """Without type config, ndarray should have no value_data (no __dict__)."""
    import numpy as np

    def run():
        arr = np.zeros((3, 4))
        _ = arr

    tree = _trace_and_load(run, type_config=None)

    run_nodes = _find_nodes(tree, "run")
    assert len(run_nodes) == 1

    var = _find_variable(run_nodes[0], "arr")
    assert var is not None

    for h in var.get("history", []):
        vd = h.get("value_data")
        # ndarray has no __dict__, so without type_config there's nothing
        assert vd is None, f"Without type config, ndarray should have no value_data, got {vd}"

    print("  pass test_type_config_no_config_no_extra_props")


def test_type_config_custom_class_extra_property():
    """Type config should work for custom classes with @property."""

    class Box:
        def __init__(self, w, h):
            self.w = w
            self.h = h

        @property
        def area(self):
            return self.w * self.h

    type_config = {Box: ["area"]}

    def run():
        b = Box(3, 5)
        _ = b.area

    tree = _trace_and_load(run, type_config=type_config)

    run_nodes = _find_nodes(tree, "run")
    assert len(run_nodes) == 1

    var = _find_variable(run_nodes[0], "b")
    assert var is not None

    found = False
    for h in var.get("history", []):
        vd = h.get("value_data")
        if vd and "area" in vd:
            found = True
            assert vd["area"]["value"] == "15"
            assert vd["area"]["type"] == "int"
            # w and h should also be present (from __dict__)
            assert "w" in vd
            assert "h" in vd

    assert found, "area property should appear in value_data"
    print("  pass test_type_config_custom_class_extra_property")


def test_type_config_subclass_inherits():
    """Type config for a parent class should apply to subclasses."""
    import numpy as np

    type_config = {np.ndarray: ["shape"]}

    # np.matrix is a subclass of ndarray
    def run():
        m = np.matrix([[1, 2], [3, 4]])
        _ = m

    tree = _trace_and_load(run, type_config=type_config)
    run_nodes = _find_nodes(tree, "run")
    assert len(run_nodes) == 1

    var = _find_variable(run_nodes[0], "m")
    assert var is not None

    found = False
    for h in var.get("history", []):
        vd = h.get("value_data")
        if vd and "shape" in vd:
            found = True
            assert vd["shape"]["value"] == "(2, 2)"

    assert found, "shape should be exported for np.matrix (subclass of ndarray)"
    print("  pass test_type_config_subclass_inherits")


def test_type_config_via_cli():
    """--type-config CLI option should work end-to-end."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_test_tc_cli_")
    try:
        # Write config file
        cfg_path = os.path.join(test_dir, "myconfig.py")
        with open(cfg_path, "w") as f:
            f.write(
                "import numpy as np\n"
                "CONFIG = {\n"
                "    np.ndarray: ['shape', 'dtype'],\n"
                "}\n"
            )

        # Write test script
        script = os.path.join(test_dir, "np_script.py")
        with open(script, "w") as f:
            f.write(
                "import numpy as np\n"
                "def main():\n"
                "    arr = np.zeros((10, 20))\n"
                "    return arr\n"
                "main()\n"
            )

        export = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [
                sys.executable, "-m", "steptrace", "run", script,
                "--export", export, "--type-config", cfg_path,
            ],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(export) as f:
            data = json.load(f)

        root = data["call_tree"]
        main_nodes = _find_nodes(root, "main")
        assert len(main_nodes) == 1

        var = _find_variable(main_nodes[0], "arr")
        assert var is not None

        found = False
        for h in var.get("history", []):
            vd = h.get("value_data")
            if vd and "shape" in vd:
                found = True
                assert vd["shape"]["value"] == "(10, 20)"
                assert "dtype" in vd

        assert found, "shape should be in value_data via --type-config"
        print("  pass test_type_config_via_cli")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_type_config_cli_bad_file():
    """--type-config with a missing file should fail gracefully."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_test_tc_cli_")
    try:
        script = os.path.join(test_dir, "dummy.py")
        with open(script, "w") as f:
            f.write("x = 1\n")

        result = subprocess.run(
            [
                sys.executable, "-m", "steptrace", "run", script,
                "--export", "--type-config", "/nonexistent/config.py",
            ],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode != 0, "Should fail for missing type config"
        assert "error" in result.stderr.lower() or "Error" in result.stderr

        print("  pass test_type_config_cli_bad_file")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ── Entry point ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("Testing Class Body Filtering + Type Config")
    print("=" * 55)

    # Class filtering
    test_class_body_not_in_trace()
    test_multiple_classes_filtered()
    test_class_methods_still_traced()
    test_nested_class_filtered()
    test_class_filter_via_cli()
    test_inheritance_class_bodies_filtered()

    # Type config loading
    test_load_type_config_single_string()
    test_load_type_config_list()
    test_load_type_config_missing_config_raises()
    test_load_type_config_bad_type_raises()

    # Type config in tracer
    test_type_config_numpy_shape_exported()
    test_type_config_multiple_props()
    test_type_config_no_config_no_extra_props()
    test_type_config_custom_class_extra_property()
    test_type_config_subclass_inherits()

    # Type config via CLI
    test_type_config_via_cli()
    test_type_config_cli_bad_file()

    print("=" * 55)
    print("All class filter + type config tests passed!")
