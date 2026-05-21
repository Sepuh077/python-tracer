#!/usr/bin/env python3
"""
Command-line interface for steptrace.

Usage:
    python -m steptrace run script.py [args...]
    python -m steptrace run script.py --config steptrace.toml
    python -m steptrace run script.py -o trace.json
    python -m steptrace view
"""

import argparse
import os
import sys
from pathlib import Path

from .config import load_config, merge_config_with_args


def create_parser():
    """Create argument parser for CLI."""
    parser = argparse.ArgumentParser(
        prog="steptrace",
        description="A lightweight Python execution tracer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m steptrace run script.py
    python -m steptrace run script.py -o trace.json
    python -m steptrace run script.py --config steptrace.toml
    python -m steptrace run script.py -- arg1 arg2  (args after -- go to script)
    python -m steptrace view                        (view latest trace)
    python -m steptrace view .tracer/trace.json     (view specific file)
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a Python script with tracing")
    run_parser.add_argument("script", help="Path to the Python script to run")

    # Config file
    run_parser.add_argument(
        "-c",
        "--config",
        help="Path to TOML configuration file",
        metavar="FILE",
    )

    # Output path
    run_parser.add_argument(
        "-o",
        "--output",
        help="Custom path for trace JSON output (default: .tracer/trace.json)",
        metavar="FILE",
        default=None,
    )

    # Tracer options
    run_parser.add_argument(
        "--log-dir",
        help="Directory for trace output (default: .tracer)",
        default=None,
    )
    run_parser.add_argument(
        "--no-filter-workspace",
        action="store_true",
        help="Trace all files, not just workspace files",
    )
    run_parser.add_argument(
        "--traceable-functions",
        nargs="+",
        help="List of function names to trace (default: all)",
        metavar="FUNC",
    )

    # View command
    view_parser = subparsers.add_parser(
        "view", help="Interactively view a structured trace file"
    )
    view_parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Path to the trace JSON file (default: most recent in .tracer/)",
    )

    return parser


def run_script(args):
    """Run a script with structured tracing enabled."""
    script_path = os.path.abspath(args.script)

    if not os.path.exists(script_path):
        print(f"Error: Script not found: {script_path}", file=sys.stderr)
        return 1

    # Load configuration from file if specified
    config = {}
    if args.config:
        config = load_config(args.config)
        if config is None:
            return 1

    # Merge config with CLI arguments (CLI takes precedence)
    tracer_kwargs = merge_config_with_args(config, args)

    # Process script arguments (remove leading '--' if present)
    script_args = args.script_args or []
    if script_args and script_args[0] == "--":
        script_args = script_args[1:]

    # Set up sys.argv for the script
    sys.argv = [script_path] + script_args

    # Add script directory to path
    script_dir = os.path.dirname(script_path)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # Read and compile the script
    with open(script_path, "r") as f:
        script_code = f.read()

    # Create global namespace for script execution
    script_globals = {
        "__name__": "__main__",
        "__file__": script_path,
        "__doc__": None,
        "__package__": None,
        "__builtins__": __builtins__,
    }

    # Compile the script
    compiled = compile(script_code, script_path, "exec")

    # Override workspace to be the script's directory
    tracer_kwargs["_workspace_override"] = script_dir

    # Extract type_config from merged kwargs (not a Tracer kwarg)
    type_config = tracer_kwargs.pop("type_config", None)

    # Always use StructuredTracer for JSON export
    from .structured_tracer import StructuredTracer

    export_path = getattr(args, "output", None)
    tracer = StructuredTracer(
        export_path=export_path,
        script_path=script_path,
        type_config=type_config,
        **tracer_kwargs,
    )

    # Run the script with tracing
    print(f"Tracing: {script_path}")
    print(f"Structured trace output: {tracer.export_path}")

    try:
        with tracer:
            exec(compiled, script_globals)
        print(f"Structured trace saved to: {tracer.export_path}")
        print(f"View with: python -m steptrace view {tracer.export_path}")
        return 0
    except SystemExit as e:
        print(f"Structured trace saved to: {tracer.export_path}")
        return e.code if isinstance(e.code, int) else 0
    except Exception as e:
        print(f"Error running script: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        if os.path.exists(tracer.export_path):
            print(f"Structured trace saved to: {tracer.export_path}")
            print(f"View with: python -m steptrace view {tracer.export_path}")
        return 1


def main():
    """Main entry point for CLI."""
    parser = create_parser()

    # Use parse_known_args to allow options after script name
    # Unknown args will be passed to the script
    args, unknown = parser.parse_known_args()

    if args.command == "run":
        # Process unknown args as script arguments
        # Remove leading '--' separator if present
        script_args = unknown
        if script_args and script_args[0] == "--":
            script_args = script_args[1:]
        args.script_args = script_args
        return run_script(args)
    elif args.command == "view":
        from .viewer import main as viewer_main

        return viewer_main(getattr(args, "file", None))
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
