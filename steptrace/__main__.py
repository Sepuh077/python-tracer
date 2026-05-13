#!/usr/bin/env python3
"""
Command-line interface for steptrace.

Usage:
    python -m steptrace run script.py [args...]
    python -m steptrace run script.py --config config.yaml
    python -m steptrace run script.py --config config.toml
"""

import argparse
import os
import sys
from pathlib import Path

from .config import load_config, merge_config_with_args
from .tracer import LogLevel, LogOutput, Tracer, VariableMode


def create_parser():
    """Create argument parser for CLI."""
    parser = argparse.ArgumentParser(
        prog="steptrace",
        description="A lightweight Python execution tracer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m steptrace run script.py
    python -m steptrace run script.py --log-output STDOUT
    python -m steptrace run script.py --log-level DEBUG --variable-mode CHANGED
    python -m steptrace run script.py --trace-async
    python -m steptrace run script.py --config config.yaml
    python -m steptrace run script.py -- arg1 arg2  (args after -- go to script)
    python -m steptrace run script.py --export            (structured JSON export)
    python -m steptrace run script.py --export out.json   (custom export path)
    python -m steptrace view                              (view latest trace)
    python -m steptrace view .tracer/trace.json           (view specific file)
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
        help="Path to configuration file (YAML or TOML)",
        metavar="FILE",
    )

    # Tracer options
    run_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "SILENT"],
        help="Log verbosity level (default: INFO)",
    )
    run_parser.add_argument(
        "--log-output",
        choices=["FILE", "STDOUT", "STDERR", "FILE_STDOUT", "FILE_STDERR"],
        help="Output destination (default: FILE)",
    )
    run_parser.add_argument(
        "--variable-mode",
        choices=["ALL", "CHANGED", "NONE"],
        help="Variable logging mode (default: ALL)",
    )
    run_parser.add_argument(
        "--log-dir",
        help="Directory for log files (default: .tracer)",
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

    # Async tracing options
    run_parser.add_argument(
        "--trace-async",
        action="store_true",
        help="Enable tracing of asyncio coroutines and await points",
    )
    run_parser.add_argument(
        "--async-threshold-ms",
        type=float,
        default=0.0,
        help="Only log await points taking longer than this threshold (ms)",
        metavar="MS",
    )

    # Structured export option
    run_parser.add_argument(
        "--export",
        nargs="?",
        const=True,
        default=None,
        help="Export structured trace data to JSON for interactive viewing. "
        "Optionally specify output file path (default: .tracer/trace.json)",
        metavar="FILE",
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
    """Run a script with tracing enabled."""
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

    # Determine if we need async tracing
    trace_async = tracer_kwargs.pop("trace_async", False)
    async_threshold_ms = tracer_kwargs.pop("async_threshold_ms", 0.0)

    # Determine if structured export is requested
    export_flag = getattr(args, "export", None)

    # Override workspace to be the script's directory
    tracer_kwargs["_workspace_override"] = script_dir

    # Create the tracer
    if export_flag is not None:
        from .structured_tracer import StructuredTracer

        export_path = None if export_flag is True else export_flag
        tracer = StructuredTracer(
            export_path=export_path,
            script_path=script_path,
            **tracer_kwargs,
        )
    elif trace_async:
        from .async_tracer import AsyncTracer

        tracer = AsyncTracer(
            await_threshold_ms=async_threshold_ms,
            **tracer_kwargs,
        )
    else:
        tracer = Tracer(**tracer_kwargs)

    # Run the script with tracing
    print(f"Tracing: {script_path}")
    if hasattr(tracer, "export_path"):
        print(f"Structured trace output: {tracer.export_path}")
    elif tracer.log_path:
        print(f"Log output: {tracer.log_path}")

    try:
        with tracer:
            exec(compiled, script_globals)
        if hasattr(tracer, "export_path"):
            print(f"Structured trace saved to: {tracer.export_path}")
            print(f"View with: python -m steptrace view {tracer.export_path}")
        return 0
    except SystemExit as e:
        if hasattr(tracer, "export_path"):
            print(f"Structured trace saved to: {tracer.export_path}")
        return e.code if isinstance(e.code, int) else 0
    except Exception as e:
        print(f"Error running script: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
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
