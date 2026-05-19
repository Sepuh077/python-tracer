#!/usr/bin/env python3
"""
Comprehensive tests for the CLI functionality.
Tests the refactored CLI that always uses StructuredTracer (JSON export).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def create_test_script(directory: str, name: str = "test_script.py") -> str:
    """Create a simple test script."""
    script_path = os.path.join(directory, name)
    with open(script_path, "w") as f:
        f.write('''#!/usr/bin/env python3
def calculate(a, b):
    return a + b

def main():
    x = 10
    y = 20
    z = calculate(x, y)
    print(f"Result: {z}")
    return 0

if __name__ == "__main__":
    main()
''')
    return script_path


def create_async_test_script(directory: str, name: str = "async_script.py") -> str:
    """Create an async test script."""
    script_path = os.path.join(directory, name)
    with open(script_path, "w") as f:
        f.write('''#!/usr/bin/env python3
import asyncio

async def fetch_data():
    await asyncio.sleep(0.01)
    return "data"

async def main():
    result = await fetch_data()
    print(f"Async Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
''')
    return script_path


def create_toml_config(directory: str, config: dict, name: str = "steptrace.toml",
                       type_config: dict = None) -> str:
    """Create a TOML config file, optionally with [type_config] section."""
    config_path = os.path.join(directory, name)
    with open(config_path, "w") as f:
        for key, value in config.items():
            if isinstance(value, bool):
                f.write(f'{key} = {"true" if value else "false"}\n')
            elif isinstance(value, str):
                f.write(f'{key} = "{value}"\n')
            elif isinstance(value, (int, float)):
                f.write(f"{key} = {value}\n")
            elif isinstance(value, list):
                items = ", ".join(f'"{item}"' for item in value)
                f.write(f"{key} = [{items}]\n")
        if type_config:
            f.write("\n[type_config]\n")
            for cls_name, props in type_config.items():
                items = ", ".join(f'"{p}"' for p in props)
                f.write(f'"{cls_name}" = [{items}]\n')
    return config_path


def create_pyproject_toml(directory: str, config: dict) -> str:
    """Create a pyproject.toml with [tool.steptrace] section."""
    config_path = os.path.join(directory, "pyproject.toml")
    with open(config_path, "w") as f:
        f.write('[project]\nname = "test"\nversion = "1.0.0"\n\n')
        f.write("[tool.steptrace]\n")
        for key, value in config.items():
            if isinstance(value, bool):
                f.write(f'{key} = {"true" if value else "false"}\n')
            elif isinstance(value, str):
                f.write(f'{key} = "{value}"\n')
            elif isinstance(value, (int, float)):
                f.write(f"{key} = {value}\n")
            elif isinstance(value, list):
                items = ", ".join(f'"{item}"' for item in value)
                f.write(f"{key} = [{items}]\n")
    return config_path


def get_project_root():
    """Get the project root directory."""
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


# ==================== Basic CLI Tests ====================

def test_cli_basic_run():
    """Test basic CLI script execution produces structured JSON output."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = create_test_script(test_dir)

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path],
            capture_output=True,
            text=True,
            cwd=get_project_root(),
        )

        assert "Result: 30" in result.stdout, f"Script should output result. Got: {result.stdout}"
        assert result.returncode == 0, f"Should return 0. Got: {result.returncode}"
        # Default behaviour is structured export
        assert "Structured trace saved to:" in result.stdout, "Should report trace output"

        print("✓ test_cli_basic_run passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_cli_default_export():
    """Running without --export should still produce a JSON trace file."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")
    log_dir = os.path.join(test_dir, "logs")

    try:
        script_path = create_test_script(test_dir)

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--log-dir", log_dir],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0, f"Stderr: {result.stderr}"
        trace_file = os.path.join(log_dir, "trace.json")
        assert os.path.exists(trace_file), f"trace.json should be created in {log_dir}"

        with open(trace_file) as f:
            data = json.load(f)
        assert "call_tree" in data
        assert "metadata" in data

        print("✓ test_cli_default_export passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_cli_custom_output_path():
    """Test CLI with -o/--output to specify a custom trace path."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = create_test_script(test_dir)
        out = os.path.join(test_dir, "my_trace.json")

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0
        assert os.path.exists(out), f"Custom output file should exist: {out}"

        with open(out) as f:
            data = json.load(f)
        assert "call_tree" in data

        print("✓ test_cli_custom_output_path passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_cli_help():
    """Test CLI help output."""
    result = subprocess.run(
        [sys.executable, "-m", "steptrace", "--help"],
        capture_output=True, text=True, cwd=get_project_root(),
    )

    assert result.returncode == 0, "Help should succeed"
    assert "steptrace" in result.stdout.lower()

    # Check run subcommand help
    result = subprocess.run(
        [sys.executable, "-m", "steptrace", "run", "--help"],
        capture_output=True, text=True, cwd=get_project_root(),
    )

    assert result.returncode == 0
    assert "--config" in result.stdout, "Should show --config option"
    assert "--output" in result.stdout, "Should show --output option"
    assert "--log-dir" in result.stdout, "Should show --log-dir option"
    assert "--no-filter-workspace" in result.stdout
    assert "--traceable-functions" in result.stdout

    print("✓ test_cli_help passed")


def test_cli_missing_script():
    """Test CLI handles missing script gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "steptrace", "run", "/nonexistent/script.py"],
        capture_output=True, text=True, cwd=get_project_root(),
    )

    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()

    print("✓ test_cli_missing_script passed")


# ==================== Log Directory Tests ====================

def test_cli_log_dir():
    """Test CLI with --log-dir option."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")
    custom_log_dir = os.path.join(test_dir, "custom_logs")

    try:
        script_path = create_test_script(test_dir)

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--log-dir", custom_log_dir],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0
        trace_file = os.path.join(custom_log_dir, "trace.json")
        assert os.path.exists(trace_file), f"Trace file should be at {trace_file}"

        print("✓ test_cli_log_dir passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== Filter Workspace Tests ====================

def test_cli_no_filter_workspace():
    """Test CLI with --no-filter-workspace option."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = create_test_script(test_dir)

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--no-filter-workspace"],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0
        assert "Structured trace saved to:" in result.stdout

        print("✓ test_cli_no_filter_workspace passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== Script Arguments Tests ====================

def test_cli_with_script_args():
    """Test CLI passes arguments to script using -- separator."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = os.path.join(test_dir, "args_script.py")
        with open(script_path, "w") as f:
            f.write('''#!/usr/bin/env python3
import sys
print(f"Args: {sys.argv[1:]}")
''')

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--", "arg1", "arg2", "arg3"],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert "Args: ['arg1', 'arg2', 'arg3']" in result.stdout

        print("✓ test_cli_with_script_args passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== Traceable Functions Tests ====================

def test_cli_traceable_functions():
    """Test CLI with --traceable-functions option."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = os.path.join(test_dir, "multi_func.py")
        with open(script_path, "w") as f:
            f.write('''#!/usr/bin/env python3
def func_a():
    x = 1
    return x

def func_b():
    y = 2
    return y

def main():
    a = func_a()
    b = func_b()
    print(f"Result: {a + b}")

main()
''')
        out = os.path.join(test_dir, "trace.json")

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--traceable-functions", "func_a", "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0

        with open(out) as f:
            data = json.load(f)

        root = data["call_tree"]
        fa = _find_nodes(root, "func_a")
        fb = _find_nodes(root, "func_b")
        assert len(fa) >= 1, "func_a should be traced"
        assert len(fb) == 0, "func_b should NOT be traced"

        print("✓ test_cli_traceable_functions passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== Async Tracing Tests ====================

def test_cli_async_script():
    """Async scripts should work with the default StructuredTracer."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = create_async_test_script(test_dir)

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert "Async Result: data" in result.stdout
        assert result.returncode == 0

        print("✓ test_cli_async_script passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== TOML Config Tests ====================

def test_cli_toml_config_basic():
    """Test CLI with basic TOML config file."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = create_test_script(test_dir)
        config_path = create_toml_config(test_dir, {
            "filter_workspace": False,
        })

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--config", config_path],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0
        assert "Structured trace saved to:" in result.stdout

        print("✓ test_cli_toml_config_basic passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_cli_toml_config_with_type_config():
    """Test CLI with TOML config containing [type_config] section."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        # Script with a custom class
        script_path = os.path.join(test_dir, "tc_script.py")
        with open(script_path, "w") as f:
            f.write('''
class Sensor:
    def __init__(self, name, val):
        self.name = name
        self._val = val

    @property
    def reading(self):
        return self._val * 2

def main():
    s = Sensor("temp", 21)
    r = s.reading
    return r

main()
''')

        config_path = create_toml_config(
            test_dir, {"filter_workspace": False},
            type_config={"Sensor": ["reading"]},
        )

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--config", config_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        main_nodes = _find_nodes(data["call_tree"], "main")
        assert len(main_nodes) == 1

        var = _find_variable(main_nodes[0], "s")
        assert var is not None, "Variable 's' should be tracked"

        found = False
        for h in var.get("history", []):
            vd = h.get("value_data")
            if vd and "reading" in vd:
                found = True
                assert vd["reading"]["value"] == "42"
        assert found, "reading property should appear via TOML type_config"

        print("✓ test_cli_toml_config_with_type_config passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_cli_toml_config_log_dir():
    """Test that log_dir from TOML config is respected."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")
    custom_dir = os.path.join(test_dir, "custom_out")

    try:
        script_path = create_test_script(test_dir)
        config_path = create_toml_config(test_dir, {
            "log_dir": custom_dir,
        })

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--config", config_path],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0
        trace = os.path.join(custom_dir, "trace.json")
        assert os.path.exists(trace), f"Trace should be at {trace}"

        print("✓ test_cli_toml_config_log_dir passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_cli_toml_config_override():
    """CLI --log-dir should override TOML log_dir."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")
    toml_dir = os.path.join(test_dir, "toml_dir")
    cli_dir = os.path.join(test_dir, "cli_dir")

    try:
        script_path = create_test_script(test_dir)
        config_path = create_toml_config(test_dir, {"log_dir": toml_dir})

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--config", config_path, "--log-dir", cli_dir],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0
        assert os.path.exists(os.path.join(cli_dir, "trace.json"))
        assert not os.path.exists(os.path.join(toml_dir, "trace.json"))

        print("✓ test_cli_toml_config_override passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== pyproject.toml Config Tests ====================

def test_cli_pyproject_toml_config():
    """Test CLI with pyproject.toml [tool.steptrace] config."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = create_test_script(test_dir)
        config_path = create_pyproject_toml(test_dir, {
            "filter_workspace": False,
        })

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--config", config_path],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode == 0
        assert "Structured trace saved to:" in result.stdout

        print("✓ test_cli_pyproject_toml_config passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== Error Handling Tests ====================

def test_cli_invalid_config_file():
    """Test CLI with invalid config file path."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = create_test_script(test_dir)

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--config", "/nonexistent/config.toml"],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode != 0

        print("✓ test_cli_invalid_config_file passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_cli_unsupported_config_format():
    """Test CLI with unsupported config file format."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = create_test_script(test_dir)
        config_path = os.path.join(test_dir, "config.txt")
        with open(config_path, "w") as f:
            f.write("log_dir = .tracer\n")

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--config", config_path],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode != 0

        print("✓ test_cli_unsupported_config_format passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_cli_script_exception():
    """Test CLI handles script exceptions properly."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = os.path.join(test_dir, "error_script.py")
        with open(script_path, "w") as f:
            f.write('raise ValueError("test error")\n')

        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path],
            capture_output=True, text=True, cwd=get_project_root(),
        )

        assert result.returncode != 0
        assert "ValueError" in result.stderr or "test error" in result.stderr

        print("✓ test_cli_script_exception passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ==================== TOML type_config via CLI end-to-end ====================

def test_cli_toml_numpy_type_config():
    """Test TOML type_config with numpy.ndarray end-to-end."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_cli_test_")

    try:
        script_path = os.path.join(test_dir, "np_script.py")
        with open(script_path, "w") as f:
            f.write(
                "import numpy as np\n"
                "def main():\n"
                "    arr = np.zeros((10, 20))\n"
                "    return arr\n"
                "main()\n"
            )

        config_path = create_toml_config(
            test_dir, {},
            type_config={"numpy.ndarray": ["shape", "dtype"]},
        )

        out = os.path.join(test_dir, "trace.json")
        result = subprocess.run(
            [sys.executable, "-m", "steptrace", "run", script_path,
             "--config", config_path, "-o", out],
            capture_output=True, text=True, cwd=get_project_root(),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(out) as f:
            data = json.load(f)

        main_nodes = _find_nodes(data["call_tree"], "main")
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

        assert found, "shape should be in value_data via TOML type_config"

        print("✓ test_cli_toml_numpy_type_config passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    print("Testing CLI Functionality")
    print("=" * 60)

    # Basic tests
    test_cli_basic_run()
    test_cli_default_export()
    test_cli_custom_output_path()
    test_cli_help()
    test_cli_missing_script()

    # Log directory tests
    test_cli_log_dir()

    # Filter workspace tests
    test_cli_no_filter_workspace()

    # Script arguments tests
    test_cli_with_script_args()

    # Traceable functions tests
    test_cli_traceable_functions()

    # Async tracing
    test_cli_async_script()

    # TOML config tests
    test_cli_toml_config_basic()
    test_cli_toml_config_with_type_config()
    test_cli_toml_config_log_dir()
    test_cli_toml_config_override()

    # pyproject.toml config tests
    test_cli_pyproject_toml_config()

    # Error handling tests
    test_cli_invalid_config_file()
    test_cli_unsupported_config_format()
    test_cli_script_exception()

    # TOML type_config end-to-end
    test_cli_toml_numpy_type_config()

    print("=" * 60)
    print("All CLI tests passed!")
