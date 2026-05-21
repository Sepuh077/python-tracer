"""
Configuration file support for steptrace.

Supports loading configuration from TOML files (.toml and pyproject.toml).
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_toml(filepath: str) -> Optional[Dict[str, Any]]:
    """Load configuration from a TOML file."""
    # Python 3.11+ has built-in tomllib
    try:
        import tomllib
    except ImportError:
        # Fall back to tomli for Python < 3.11
        try:
            import tomli as tomllib
        except ImportError:
            print(
                "Error: tomli is required to load TOML config files on Python < 3.11. "
                "Install it with: pip install tomli",
                file=sys.stderr,
            )
            return None

    try:
        with open(filepath, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        print(f"Error parsing TOML file {filepath}: {e}", file=sys.stderr)
        return None
    except FileNotFoundError:
        print(f"Error: Config file not found: {filepath}", file=sys.stderr)
        return None


def load_config(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Load configuration from a TOML file.

    Supports steptrace.toml and pyproject.toml (with [tool.steptrace] section).

    Args:
        filepath: Path to the configuration file.

    Returns:
        Dictionary with configuration options, or None on error.
    """
    filepath = os.path.abspath(filepath)
    ext = Path(filepath).suffix.lower()

    if ext != ".toml":
        print(
            f"Error: Unsupported config file format: {ext}. "
            "Use .toml",
            file=sys.stderr,
        )
        return None

    config = load_toml(filepath)
    # If it's a pyproject.toml, look for [tool.steptrace]
    if config and os.path.basename(filepath) == "pyproject.toml":
        config = config.get("tool", {}).get("steptrace", {})

    if config is not None:
        config = normalize_config(config)

    return config


def normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize configuration dictionary.

    - Converts hyphens to underscores in keys
    - Extracts type_config section as-is (string keys → list of strings)
    """
    normalized = {}

    for key, value in config.items():
        # Convert hyphens to underscores
        key = key.replace("-", "_")

        if key == "type_config" and isinstance(value, dict):
            # type_config section: normalize values to lists of strings
            normalized[key] = parse_type_config(value)
        elif isinstance(value, dict):
            value = normalize_config(value)
            normalized[key] = value
        else:
            normalized[key] = value

    return normalized


def parse_type_config(raw: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Parse the [type_config] TOML section.

    Keys are class names (optionally module-qualified, e.g. "numpy.ndarray")
    and values are lists of property/method names to track.

    A single string value is normalised to a one-element list.
    """
    result: Dict[str, List[str]] = {}
    for class_key, props in raw.items():
        if isinstance(props, str):
            props = [props]
        elif isinstance(props, list):
            props = [str(p) for p in props]
        else:
            continue  # skip invalid entries silently
        result[class_key] = props
    return result


def merge_config_with_args(config: Dict[str, Any], args) -> Dict[str, Any]:
    """
    Merge configuration from file with CLI arguments.

    CLI arguments take precedence over config file values.

    Args:
        config: Configuration dictionary from file.
        args: Parsed command-line arguments.

    Returns:
        Merged configuration for StructuredTracer initialization.
    """
    result = {}

    # Map config keys to tracer kwargs
    if "log_dir" in config:
        result["log_dir"] = config["log_dir"]
    if "filter_workspace" in config:
        result["filter_workspace"] = config["filter_workspace"]
    if "traceable_functions" in config:
        result["tracable_functions"] = config["traceable_functions"]
    if "type_config" in config:
        result["type_config"] = config["type_config"]

    # Override with CLI arguments
    if hasattr(args, "log_dir") and args.log_dir:
        result["log_dir"] = args.log_dir
    if hasattr(args, "no_filter_workspace") and args.no_filter_workspace:
        result["filter_workspace"] = False
    if hasattr(args, "traceable_functions") and args.traceable_functions:
        result["tracable_functions"] = args.traceable_functions

    return result


def find_config_file(start_dir: str = None) -> Optional[str]:
    """
    Find a steptrace configuration file by searching upward.

    Looks for:
    - steptrace.toml
    - pyproject.toml (with [tool.steptrace] section)

    Args:
        start_dir: Directory to start searching from. Defaults to current directory.

    Returns:
        Path to config file if found, None otherwise.
    """
    if start_dir is None:
        start_dir = os.getcwd()

    current = Path(start_dir).resolve()

    for _ in range(20):  # Limit search depth
        # Check for steptrace.toml
        config_path = current / "steptrace.toml"
        if config_path.exists():
            return str(config_path)

        # Check for pyproject.toml
        pyproject_path = current / "pyproject.toml"
        if pyproject_path.exists():
            # Check if it has [tool.steptrace]
            config = load_toml(str(pyproject_path))
            if config and "tool" in config and "steptrace" in config["tool"]:
                return str(pyproject_path)

        # Move up
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None
