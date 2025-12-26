import sys
import os
import time
import inspect


class Tracer:
    def __init__(self, filter_workspace=True, log_dir=".tracer"):
        self.workspace = os.path.dirname(os.path.abspath(inspect.stack()[-1].filename))
        self.filter_workspace = filter_workspace

        self.log_path = os.path.join(log_dir, "tracer.log")
        if os.path.exists(self.log_path):
            counter = 1
            while os.path.exists(
                        os.path.join(log_dir, f"tracer_{counter}.log")
                    ):
                counter += 1
            self.log_path = os.path.join(log_dir, f"tracer_{counter}.log")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.timer = None

    def _is_tracable(self, filename):
        if filename.startswith("<") or filename == __file__:
            return False

        if self.filter_workspace:
            if not filename.startswith(self.workspace):
                return False

            if "site-packages" in filename or filename == "built-in":
                return False

        return True

    def _is_tracable_var(self, var):
        if "builtin" in type(var).__name__:
            return False
        return True

    def _file(self, frame):
        files = []
        frame_co = frame
        while frame_co.f_back:
            frame_co = frame_co.f_back
            files.append(frame_co)
        files.reverse()

        text = ""
        for file in files[2:]:
            text += f"{file.f_code.co_filename}::{file.f_code.co_name} -- line {file.f_lineno}\n"

        text += f"{frame.f_code.co_filename}::{frame.f_code.co_name} -- line {frame.f_lineno}\n"
        return text

    def _variables(self, variables):
        text = ""
        for key, value in variables.items():
            if key.startswith("__") and key.endswith("__"):
                continue
            if isinstance(value, Tracer) or value == Tracer or not self._is_tracable_var(value):
                continue
            if hasattr(value, "__spec__") and not self._is_tracable(value.__spec__.origin):
                continue

            text += f"{key}: {type(value).__name__} :: {value}\n"
        return text

    def _all_variables(self, frame):
        text = ""
        global_vars = self._variables(frame.f_globals)
        local_vars = self._variables(frame.f_locals)
        if global_vars:
            text += f"------> Global variables <------\n{self._variables(frame.f_globals)}\n"
        if local_vars:
            text += f"------> Local variables <------\n{self._variables(frame.f_locals)}\n"
        return text

    def _log(self, frame):
        if not self._is_tracable(frame.f_code.co_filename):
            return
        self.step += 1
        step_root = self._file(frame)
        text = (
            f"--------------------- Step {self.step} ---------------------\n"
            f"Runtime: {(time.perf_counter() - self.timer) * 1000:.4f} ms\n"
            f"{step_root}\n"
            f"{self._all_variables(frame)}"
        )
        with open(self.log_path, "a") as f:
            f.write(text)

    def _run_tracer(self, frame, event, arg):
        if event == "line":
            try:
                self._log(frame)
            except Exception as e:
                print(e)
        self.timer = time.perf_counter()
        return self._run_tracer

    def __enter__(self):
        self.step = 0
        self.timer = time.perf_counter()
        self._previous_trace = sys.gettrace()
        sys.settrace(self._run_tracer)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.settrace(self._previous_trace)
        return False

    def trace(self, func):
        def wrap():
            self.step = 0
            self.timer = time.perf_counter()
            sys.settrace(self._run_tracer)
            func()
            sys.settrace(None)

        return wrap
