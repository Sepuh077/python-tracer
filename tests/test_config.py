#!/usr/bin/env python3
"""
Tests for configuration file support (TOML only, with type_config).
"""

import os
import shutil
import sys
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steptrace.config import (
    load_config,
    normalize_config,
    parse_type_config,
    merge_config_with_args,
    find_config_file,
)


def test_normalize_config_basic():
    """Test basic configuration normalization."""
    config = {
        "log-dir": ".my_tracer",
        "filter_workspace": True,
    }

    normalized = normalize_config(config)

    # Hyphens should be converted to underscores
    assert "log_dir" in normalized
    assert normalized["log_dir"] == ".my_tracer"
    assert normalized["filter_workspace"] is True

    print("✓ test_normalize_config_basic passed")


def test_normalize_config_with_type_config():
    """Test normalization preserves type_config section."""
    config = {
        "log_dir": ".tracer",
        "type_config": {
            "numpy.ndarray": ["shape", "dtype"],
            "Vector2D": "magnitude",
        },
    }

    normalized = normalize_config(config)

    assert "type_config" in normalized
    tc = normalized["type_config"]
    assert tc["numpy.ndarray"] == ["shape", "dtype"]
    # Single string should be normalised to a list
    assert tc["Vector2D"] == ["magnitude"]

    print("✓ test_normalize_config_with_type_config passed")


def test_parse_type_config():
    """Test parse_type_config normalises values correctly."""
    raw = {
        "numpy.ndarray": ["shape", "dtype", "sum"],
        "Vector2D": "magnitude",
        "Sprite": ["x", "y"],
    }

    result = parse_type_config(raw)

    assert result["numpy.ndarray"] == ["shape", "dtype", "sum"]
    assert result["Vector2D"] == ["magnitude"]
    assert result["Sprite"] == ["x", "y"]

    print("✓ test_parse_type_config passed")


def test_parse_type_config_skips_invalid():
    """Invalid type_config entries are silently skipped."""
    raw = {
        "Good": ["prop"],
        "Bad": 42,       # not a string or list
        "AlsoGood": "x",
    }

    result = parse_type_config(raw)

    assert "Good" in result
    assert "Bad" not in result
    assert "AlsoGood" in result

    print("✓ test_parse_type_config_skips_invalid passed")


def test_load_toml_config():
    """Test loading TOML configuration."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_config_test_")

    try:
        config_path = os.path.join(test_dir, "steptrace.toml")
        with open(config_path, "w") as f:
            f.write('''
log_dir = ".toml_tracer"
filter_workspace = true
''')

        config = load_config(config_path)

        if config is None:
            print("⚠ test_load_toml_config skipped (tomli not installed)")
            return

        assert config["log_dir"] == ".toml_tracer"
        assert config["filter_workspace"] is True

        print("✓ test_load_toml_config passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_load_toml_with_type_config():
    """Test loading TOML configuration with [type_config] section."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_config_test_")

    try:
        config_path = os.path.join(test_dir, "steptrace.toml")
        with open(config_path, "w") as f:
            f.write('''
log_dir = ".tracer"
filter_workspace = true

[type_config]
"numpy.ndarray" = ["shape", "dtype", "sum"]
"Vector2D" = ["magnitude"]
''')

        config = load_config(config_path)
        assert config is not None

        assert config["log_dir"] == ".tracer"
        tc = config["type_config"]
        assert tc["numpy.ndarray"] == ["shape", "dtype", "sum"]
        assert tc["Vector2D"] == ["magnitude"]

        print("✓ test_load_toml_with_type_config passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_load_pyproject_toml():
    """Test loading configuration from pyproject.toml."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_config_test_")

    try:
        config_path = os.path.join(test_dir, "pyproject.toml")
        with open(config_path, "w") as f:
            f.write('''
[project]
name = "my-project"
version = "1.0.0"

[tool.steptrace]
log_dir = ".custom"
filter_workspace = false

[tool.steptrace.type_config]
"MyClass" = ["prop1", "prop2"]
''')

        config = load_config(config_path)

        if config is None:
            print("⚠ test_load_pyproject_toml skipped (tomli not installed)")
            return

        assert config["log_dir"] == ".custom"
        assert config["filter_workspace"] is False
        assert config["type_config"]["MyClass"] == ["prop1", "prop2"]

        print("✓ test_load_pyproject_toml passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_merge_config_with_args():
    """Test merging config with CLI arguments."""
    from argparse import Namespace

    config = {
        "log_dir": ".config_tracer",
        "filter_workspace": True,
        "type_config": {"Foo": ["bar"]},
    }

    # CLI args should override config
    args = Namespace(
        log_dir=None,  # Not specified
        no_filter_workspace=True,
        traceable_functions=None,
    )

    merged = merge_config_with_args(config, args)

    # CLI overrides
    assert merged["filter_workspace"] is False

    # Config values where CLI not specified
    assert merged["log_dir"] == ".config_tracer"
    assert merged["type_config"] == {"Foo": ["bar"]}

    print("✓ test_merge_config_with_args passed")


def test_merge_config_cli_overrides_log_dir():
    """Test that CLI --log-dir overrides config."""
    from argparse import Namespace

    config = {"log_dir": ".old"}
    args = Namespace(
        log_dir=".new",
        no_filter_workspace=False,
        traceable_functions=None,
    )

    merged = merge_config_with_args(config, args)
    assert merged["log_dir"] == ".new"

    print("✓ test_merge_config_cli_overrides_log_dir passed")


def test_find_config_file_toml():
    """Test finding steptrace.toml config file."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_config_test_")

    try:
        sub_dir = os.path.join(test_dir, "a", "b", "c")
        os.makedirs(sub_dir)

        config_path = os.path.join(test_dir, "steptrace.toml")
        with open(config_path, "w") as f:
            f.write('log_dir = ".tracer"\n')

        found = find_config_file(sub_dir)
        assert found == config_path, f"Should find config at {config_path}, got {found}"

        print("✓ test_find_config_file_toml passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_find_config_file_pyproject():
    """Test finding pyproject.toml with [tool.steptrace]."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_config_test_")

    try:
        sub_dir = os.path.join(test_dir, "src")
        os.makedirs(sub_dir)

        config_path = os.path.join(test_dir, "pyproject.toml")
        with open(config_path, "w") as f:
            f.write('[tool.steptrace]\nlog_dir = ".tracer"\n')

        found = find_config_file(sub_dir)
        assert found == config_path

        print("✓ test_find_config_file_pyproject passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_invalid_config_file():
    """Test handling of invalid config files."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_config_test_")

    try:
        # Test unsupported extension
        config_path = os.path.join(test_dir, "config.txt")
        with open(config_path, "w") as f:
            f.write("log_dir = .tracer\n")

        config = load_config(config_path)
        assert config is None, "Should return None for unsupported format"

        # Test non-existent TOML file
        config = load_config(os.path.join(test_dir, "nonexistent.toml"))
        assert config is None, "Should return None for missing file"

        print("✓ test_invalid_config_file passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_yaml_not_supported():
    """YAML config files should be rejected."""
    test_dir = tempfile.mkdtemp(prefix="steptrace_config_test_")

    try:
        config_path = os.path.join(test_dir, "steptrace.yaml")
        with open(config_path, "w") as f:
            f.write("log_dir: .tracer\n")

        config = load_config(config_path)
        assert config is None, "YAML should no longer be supported"

        print("✓ test_yaml_not_supported passed")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    print("Testing Configuration Support")
    print("=" * 50)
    test_normalize_config_basic()
    test_normalize_config_with_type_config()
    test_parse_type_config()
    test_parse_type_config_skips_invalid()
    test_load_toml_config()
    test_load_toml_with_type_config()
    test_load_pyproject_toml()
    test_merge_config_with_args()
    test_merge_config_cli_overrides_log_dir()
    test_find_config_file_toml()
    test_find_config_file_pyproject()
    test_invalid_config_file()
    test_yaml_not_supported()
    print("=" * 50)
    print("All config tests passed!")
