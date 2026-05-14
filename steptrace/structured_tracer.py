"""
Structured tracer that captures execution data as a navigable JSON tree.

Exports a JSON file containing the call tree with variable history,
suitable for interactive viewing with the steptrace viewer.

Usage:
    from steptrace import StructuredTracer

    with StructuredTracer():
        main()

    # Then view with: python -m steptrace view
"""

import inspect
import json
import os
import sys
import time
import types
from datetime import datetime
from typing import Dict, List, Optional

from .tracer import LogLevel, LogOutput, Tracer

# Types to skip when tracking variables (we only want data, not code objects)
_SKIP_VAR_TYPES = (
    types.FunctionType,
    types.BuiltinFunctionType,
    types.BuiltinMethodType,
    types.MethodType,
    types.ModuleType,
    type,
)


class StructuredTracer(Tracer):
    """
    Tracer that exports a structured JSON call tree with variable history.

    The JSON file can be viewed interactively with:
        python -m steptrace view [trace.json]
    """

    def __init__(
        self,
        export_path: str = None,
        script_path: str = None,
        log_dir: str = ".tracer",
        **kwargs,
    ):
        # Force no text output - structured tracer only produces JSON
        kwargs["log_level"] = LogLevel.SILENT
        kwargs["log_output"] = LogOutput.STDOUT  # prevents log file creation
        kwargs["log_dir"] = log_dir

        # Fix workspace detection: the base Tracer uses stack[1] which would
        # point at *this* __init__, not the user's code. Pass it through.
        if "_workspace_override" not in kwargs:
            import inspect

            caller_frame = inspect.stack()[1]
            caller_file = caller_frame.filename
            if not caller_file.startswith("<"):
                kwargs["_workspace_override"] = os.path.dirname(
                    os.path.abspath(caller_file)
                )

        super().__init__(**kwargs)

        if export_path:
            self._export_path = export_path
        else:
            self._export_path = self._find_export_path(log_dir)

        self._script_path = script_path or ""
        self._call_stack: List[dict] = []
        self._root_node: Optional[dict] = None
        self._node_counter = 0
        self._frame_to_node: Dict[int, dict] = {}
        self._scope_vars: Dict[int, dict] = {}
        self._prev_line: Dict[int, int] = {}
        self._start_time = 0.0

        # Async coroutine tracking
        self._coro_frame_nodes: Dict[int, dict] = {}
        self._coro_frames: Dict[int, object] = {}  # prevent frame id reuse
        self._orphan_parent: Optional[dict] = None

    @property
    def export_path(self) -> str:
        return self._export_path

    def _find_export_path(self, log_dir: str) -> str:
        """Find a non-conflicting export path."""
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "trace.json")
        if os.path.exists(path):
            counter = 1
            while os.path.exists(os.path.join(log_dir, f"trace_{counter}.json")):
                counter += 1
            path = os.path.join(log_dir, f"trace_{counter}.json")
        return path

    def _new_node(self, name, kind, filename, line, class_name=None, args=None):
        """Create a new call tree node."""
        self._node_counter += 1
        return {
            "id": self._node_counter,
            "name": name,
            "kind": kind,
            "class_name": class_name,
            "file": os.path.basename(filename) if filename else "unknown",
            "file_path": filename or "unknown",
            "line_start": line,
            "calls": [],
            "variables": {},
            "args": args or {},
            "return_value": None,
            "duration_ms": 0.0,
            "step_start": self._step,
            "step_end": None,
            "_start_time": time.perf_counter(),
        }

    def _repr(self, value, max_len=500) -> str:
        """Safely get repr of a value, truncated."""
        try:
            r = repr(value)
            return r[:max_len] + "..." if len(r) > max_len else r
        except Exception:
            return "<unrepresentable>"

    def _track_variables(self, frame, change_line: int):
        """Track variable changes in the current scope."""
        if not self._call_stack:
            return

        node = self._call_stack[-1]
        frame_id = id(frame)

        # Determine argument names for this frame
        code = frame.f_code
        arg_names = set(code.co_varnames[: code.co_argcount])

        # Collect current local variables (filtered)
        current = {}
        for key, value in frame.f_locals.items():
            if key.startswith("__") and key.endswith("__"):
                continue
            if key in ("self", "cls"):
                continue
            if isinstance(value, _SKIP_VAR_TYPES):
                continue
            val_repr = self._repr(value)
            val_type = type(value).__name__
            current[key] = (val_repr, val_type)

        prev = self._scope_vars.get(frame_id, {})

        for key, (val_repr, val_type) in current.items():
            if key not in node["variables"]:
                # New variable
                is_arg = key in arg_names
                node["variables"][key] = {
                    "name": key,
                    "type": val_type,
                    "final_value": val_repr,
                    "history": [
                        {
                            "line": change_line,
                            "step": self._step,
                            "action": "arg" if is_arg else "assign",
                            "value": val_repr,
                            "value_type": val_type,
                        }
                    ],
                }
            elif key in prev and prev[key][0] != val_repr:
                # Value changed
                node["variables"][key]["history"].append(
                    {
                        "line": change_line,
                        "step": self._step,
                        "action": "modify",
                        "value": val_repr,
                        "value_type": val_type,
                        "old_value": prev[key][0],
                    }
                )
                node["variables"][key]["type"] = val_type
                node["variables"][key]["final_value"] = val_repr

        # Detect deleted variables
        for key in prev:
            if key not in current and key in node["variables"]:
                node["variables"][key]["history"].append(
                    {
                        "line": change_line,
                        "step": self._step,
                        "action": "delete",
                    }
                )

        self._scope_vars[frame_id] = current

    def _run_tracer(self, frame, event, arg):
        """Trace handler that captures structured execution data."""
        filename = frame.f_code.co_filename
        func_name = frame.f_code.co_name

        if not self._is_tracable(filename):
            self._timer = time.perf_counter()
            return self._run_tracer

        try:
            is_coro = bool(frame.f_code.co_flags & inspect.CO_COROUTINE)
            frame_id = id(frame)

            if event == "call":
                if not self._is_tracable_func(func_name):
                    self._timer = time.perf_counter()
                    return self._run_tracer

                # --- Coroutine resumption detection ---
                # Python fires a "call" event every time a coroutine resumes
                # after an await.  Reuse the existing node instead of creating
                # a duplicate.
                if is_coro and frame_id in self._coro_frame_nodes:
                    existing = self._coro_frame_nodes[frame_id]
                    if existing["name"] == func_name:
                        # Valid resumption – push the same node back
                        self._call_stack.append(existing)
                        self._frame_to_node[frame_id] = existing
                        self._timer = time.perf_counter()
                        return self._run_tracer
                    else:
                        # Stale entry (memory address reused by a new coro)
                        del self._coro_frame_nodes[frame_id]
                        self._scope_vars.pop(frame_id, None)
                        self._prev_line.pop(frame_id, None)
                        # Fall through to "new call" below

                # --- New call ---
                self._step += 1

                # Detect kind (module / method / function / async variants)
                class_name = None
                if func_name == "<module>":
                    kind = "module"
                elif is_coro:
                    kind = "async_function"
                else:
                    kind = "function"
                args = {}

                if "self" in frame.f_locals:
                    try:
                        class_name = type(frame.f_locals["self"]).__name__
                    except Exception:
                        class_name = "unknown"
                    kind = "async_method" if is_coro else "method"
                elif "cls" in frame.f_locals:
                    try:
                        class_name = frame.f_locals["cls"].__name__
                    except Exception:
                        class_name = "unknown"
                    kind = "classmethod"

                # Capture function arguments
                code = frame.f_code
                for vname in code.co_varnames[: code.co_argcount]:
                    if vname in ("self", "cls"):
                        continue
                    if vname in frame.f_locals:
                        args[vname] = self._repr(frame.f_locals[vname], max_len=200)

                node = self._new_node(
                    name=func_name,
                    kind=kind,
                    filename=filename,
                    line=frame.f_lineno,
                    class_name=class_name,
                    args=args,
                )

                if is_coro:
                    node["_is_coro"] = True

                # --- Parent assignment ---
                parent_assigned = False

                if is_coro:
                    # For a new coroutine, prefer a coroutine ancestor on
                    # the call stack (handles sequential `await`).
                    for n in reversed(self._call_stack):
                        if n.get("_is_coro"):
                            n["calls"].append(node)
                            parent_assigned = True
                            break

                    # No coroutine ancestor → orphan (e.g. from gather /
                    # create_task).  Attach to the most recently suspended
                    # non-orphan coroutine.
                    if not parent_assigned and self._orphan_parent is not None:
                        self._orphan_parent["calls"].append(node)
                        node["_orphan"] = True
                        parent_assigned = True

                # Fallback: use whatever is on top of the call stack.
                if not parent_assigned and self._call_stack:
                    self._call_stack[-1]["calls"].append(node)
                    parent_assigned = True

                # Set as root if this is the very first node
                if self._root_node is None:
                    self._root_node = node

                self._call_stack.append(node)
                self._frame_to_node[frame_id] = node
                self._prev_line[frame_id] = frame.f_lineno

                if is_coro:
                    self._coro_frame_nodes[frame_id] = node
                    # Hold a strong reference so the frame is not
                    # garbage-collected and its id() is not reused by
                    # a later coroutine of the same function.
                    self._coro_frames[frame_id] = frame

            elif event == "line":
                if not self._is_tracable_func(func_name):
                    self._timer = time.perf_counter()
                    return self._run_tracer

                self._step += 1

                # Create module node for top-level code (no call event for exec'd code)
                if not self._call_stack:
                    if self._root_node is None:
                        module_node = self._new_node(
                            name="<module>",
                            kind="module",
                            filename=filename,
                            line=1,
                        )
                        self._root_node = module_node
                        self._call_stack.append(module_node)
                        self._frame_to_node[frame_id] = module_node
                        self._prev_line[frame_id] = frame.f_lineno
                    elif frame_id in self._frame_to_node:
                        # Re-entering a scope after a child function returned
                        self._call_stack.append(self._frame_to_node[frame_id])

                # The line that was just executed is the previous line
                change_line = self._prev_line.get(frame_id, frame.f_lineno)

                # Track variable changes
                self._track_variables(frame, change_line)

                # Remember current line for next iteration
                self._prev_line[frame_id] = frame.f_lineno

            elif event == "return":
                if is_coro and frame_id in self._coro_frame_nodes:
                    # Coroutine return – may be a suspension (yield to the
                    # event loop) or a real completion.  We can't tell which,
                    # so we tentatively update the node but keep all tracking
                    # data alive for a potential resumption.
                    node = self._coro_frame_nodes[frame_id]
                    node["step_end"] = self._step
                    node["duration_ms"] = round(
                        (time.perf_counter() - node.get("_start_time", self._timer))
                        * 1000,
                        4,
                    )
                    try:
                        node["return_value"] = (
                            self._repr(arg, max_len=300) if arg is not None else None
                        )
                    except Exception:
                        node["return_value"] = "<unrepresentable>"

                    # Pop from call stack (will be re-pushed on resumption)
                    if self._call_stack and self._call_stack[-1] is node:
                        self._call_stack.pop()

                    # A non-orphan coroutine that just suspended becomes the
                    # candidate parent for upcoming orphan coroutines (e.g.
                    # ones started by asyncio.gather / create_task).
                    if not node.get("_orphan"):
                        self._orphan_parent = node

                    # Do NOT delete from _frame_to_node, _scope_vars,
                    # _prev_line, or _coro_frame_nodes – they are needed if
                    # the coroutine resumes later.
                else:
                    # Normal synchronous return – clean up as usual.
                    if frame_id in self._frame_to_node:
                        node = self._frame_to_node[frame_id]
                        node["step_end"] = self._step
                        node["duration_ms"] = round(
                            (time.perf_counter() - node.get("_start_time", self._timer))
                            * 1000,
                            4,
                        )
                        try:
                            node["return_value"] = (
                                self._repr(arg, max_len=300) if arg is not None else None
                            )
                        except Exception:
                            node["return_value"] = "<unrepresentable>"

                        # Pop from call stack
                        if self._call_stack and self._call_stack[-1] is node:
                            self._call_stack.pop()

                        # Cleanup tracking data for this frame
                        del self._frame_to_node[frame_id]
                        self._scope_vars.pop(frame_id, None)
                        self._prev_line.pop(frame_id, None)

        except Exception:
            pass  # Never crash the user's program

        self._timer = time.perf_counter()
        return self._run_tracer

    def _clean_node(self, node):
        """Remove internal fields and convert variables dict to list before saving."""
        if node is None:
            return None
        node.pop("_start_time", None)
        node.pop("_is_coro", None)
        node.pop("_orphan", None)
        node["variables"] = list(node["variables"].values())
        for child in node.get("calls", []):
            self._clean_node(child)
        return node

    def _save(self):
        """Save the structured trace data to JSON."""
        root = self._clean_node(self._root_node)

        data = {
            "metadata": {
                "script": self._script_path,
                "timestamp": datetime.now().isoformat(),
                "total_steps": self._step,
                "total_duration_ms": round(
                    (time.perf_counter() - self._start_time) * 1000, 4
                )
                if self._start_time
                else 0,
            },
            "call_tree": root,
        }

        export_dir = os.path.dirname(os.path.abspath(self._export_path))
        os.makedirs(export_dir, exist_ok=True)

        with open(self._export_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _initialize(self):
        """Initialize tracer state."""
        super()._initialize()
        self._call_stack = []
        self._root_node = None
        self._node_counter = 0
        self._frame_to_node = {}
        self._scope_vars = {}
        self._prev_line = {}
        self._start_time = time.perf_counter()
        self._coro_frame_nodes = {}
        self._coro_frames = {}
        self._orphan_parent = None

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.settrace(self._previous_trace)
        self._save()
        return False

    def trace(self, func):
        """Decorator to trace a function and export structured data."""

        def wrap(*args, **kwargs):
            self._initialize()
            code = getattr(func, "__code__", None)
            self._script_path = code.co_filename if code else str(func)
            sys.settrace(self._run_tracer)
            try:
                result = func(*args, **kwargs)
            finally:
                sys.settrace(None)
                self._save()
            return result

        return wrap