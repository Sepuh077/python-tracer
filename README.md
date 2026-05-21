# Steptrace

A lightweight Python execution tracer that records **line-by-line execution**, **call stack**, **runtime per step**, and **local/global variables** - all filtered to your workspace for clean, readable logs.

Designed for debugging, learning, and understanding program flow.

---

## Features

- Line-by-line execution tracing
- Call stack reconstruction
- Runtime per step (milliseconds)
- Local and global variable inspection
- **Configurable log levels** (DEBUG, INFO, WARNING, ERROR, SILENT)
- **Flexible output destinations** (FILE, STDOUT, STDERR, or combinations)
- **Variable tracking modes** (ALL, CHANGED, NONE)
- **Command-line interface** for running scripts directly
- **Configuration files** (YAML, TOML) support
- **Asyncio tracing** with await point duration tracking
- Automatically ignores:
  - Built-in modules
  - `site-packages`
  - Non-workspace files
- Auto-incrementing log files (no overwrites)
- Safe cleanup of `sys.settrace`
- Supports **context manager** and **decorator** usage

---

## Installation

```bash
pip install python-steptrace

# With YAML config support
pip install python-steptrace[yaml]

# With TOML config support (Python < 3.11)
pip install python-steptrace[toml]

# With all features
pip install python-steptrace[all]
```

---

## Quick Start

### Command-Line Interface (NEW!)

Run any Python script with tracing enabled:

```bash
# Basic usage
python -m steptrace run script.py

# With arguments to your script
python -m steptrace run script.py arg1 arg2

# With tracing options
python -m steptrace run script.py --log-output STDOUT --variable-mode CHANGED

# With configuration file
python -m steptrace run script.py --config steptrace.yaml

# With asyncio tracing
python -m steptrace run async_script.py --trace-async
```

### Context Manager (Recommended)

```python
from steptrace import Tracer

def main():
    a = 1
    b = 2
    print(a + b)

with Tracer():
    main()
```

### Decorator Usage

```python
from steptrace import Tracer

@Tracer().trace
def main():
    a = 1
    b = 2
    print(a + b)

main()
```

---

## Command-Line Interface

The CLI provides a convenient way to trace any Python script without modifying its code.

### Basic Usage

```bash
python -m steptrace run script.py
```

### CLI Options

```
Options:
  -c, --config FILE       Path to configuration file (YAML or TOML)
  --log-level LEVEL       Log verbosity: DEBUG, INFO, WARNING, ERROR, SILENT
  --log-output OUTPUT     Output destination: FILE, STDOUT, STDERR, FILE_STDOUT, FILE_STDERR
  --variable-mode MODE    Variable logging: ALL, CHANGED, NONE
  --log-dir DIR           Directory for log files (default: .tracer)
  --no-filter-workspace   Trace all files, not just workspace files
  --traceable-functions   List of function names to trace
  --trace-async           Enable asyncio coroutine tracing
  --async-threshold-ms    Only log awaits taking longer than this (ms)
```

### Examples

```bash
# Debug mode with stdout output
python -m steptrace run script.py --log-level DEBUG --log-output STDOUT

# Only track changed variables
python -m steptrace run script.py --variable-mode CHANGED --log-output STDOUT

# Trace specific functions
python -m steptrace run script.py --traceable-functions main process_data

# Async tracing with threshold
python -m steptrace run async_app.py --trace-async --async-threshold-ms 10
```

---

## Configuration Files

Steptrace supports configuration via YAML and TOML files, including `pyproject.toml`.

### YAML Configuration (steptrace.yaml)

```yaml
log_level: INFO
log_output: FILE
variable_mode: ALL
log_dir: .tracer
filter_workspace: true

# Asyncio options
trace_async: false
async_threshold_ms: 0.0

# Optional: trace only specific functions
# traceable_functions:
#   - main
#   - my_function
```

### TOML Configuration (steptrace.toml)

```toml
log_level = "INFO"
log_output = "FILE"
variable_mode = "ALL"
log_dir = ".tracer"
filter_workspace = true

trace_async = false
async_threshold_ms = 0.0
```

### pyproject.toml

Add a `[tool.steptrace]` section to your project's pyproject.toml:

```toml
[tool.steptrace]
log_level = "DEBUG"
log_output = "STDOUT"
variable_mode = "CHANGED"
```

### Using Config Files

```bash
# Explicit config file
python -m steptrace run script.py --config steptrace.yaml

# CLI options override config file settings
python -m steptrace run script.py --config steptrace.yaml --log-level DEBUG
```

---

## Asyncio Tracing (NEW!)

Steptrace can trace asyncio coroutines, await points, and their durations.

### Using AsyncTracer

```python
import asyncio
from steptrace import AsyncTracer, LogOutput

async def fetch_data(url):
    await asyncio.sleep(0.1)  # Simulate network request
    return {"url": url, "data": "..."}

async def main():
    data = await fetch_data("https://api.example.com")
    print(data)

# Create async tracer
tracer = AsyncTracer(
    log_output=LogOutput.STDOUT,
    await_threshold_ms=0.0,  # Log all awaits (0 = no threshold)
)

# Option 1: Decorator
@tracer.trace_async
async def traced_main():
    await main()

asyncio.run(traced_main())

# Option 2: run_async
async def run():
    await tracer.run_async(main())

asyncio.run(run())
```

### Tracing Concurrent Operations

```python
from steptrace import AsyncTracer

tracer = AsyncTracer(log_output=LogOutput.STDOUT)

async def example():
    # Traced gather
    results = await tracer.gather(
        fetch_data("url1"),
        fetch_data("url2"),
        fetch_data("url3"),
    )
    
    # Traced task creation
    task = tracer.wrap_task(fetch_data("url4"), "my_task")
    result = await task
    
    return results

asyncio.run(tracer.run_async(example()))
```

### Explicit Await Tracing

```python
async def example():
    # Trace specific awaits with custom labels
    result = await tracer.trace_await(
        some_async_call(),
        "some_async_call()"
    )
```

### Await Threshold

Only log awaits that take longer than a threshold:

```python
# Only log awaits taking > 10ms
tracer = AsyncTracer(await_threshold_ms=10.0)
```

### CLI Async Tracing

```bash
# Enable async tracing
python -m steptrace run async_app.py --trace-async

# With threshold (only log slow awaits)
python -m steptrace run async_app.py --trace-async --async-threshold-ms 50
```

### Async Log Output Example

```
--------------------- Async Step 1 ---------------------
Time: 0.1234 ms | CORO
🚀 COROUTINE START: fetch_data

--------------------- Async Step 2 ---------------------
Time: 0.5678 ms | AWAIT
⏳ AWAIT START: fetch_data
   File: /path/to/script.py:15
   Expression: sleep(0.1)

--------------------- Async Step 3 ---------------------
Time: 100.1234 ms | AWAIT
⌛ AWAIT END: fetch_data ✓
   File: /path/to/script.py:15
   Duration: 100.0123 ms

--------------------- Async Step 4 ---------------------
Time: 100.5678 ms | CORO
🏁 COROUTINE END: fetch_data ✓
   Total duration: 100.4321 ms
   Await points: 1
   Total await time: 100.0123 ms
```

---

## Configuration Options

### Log Level (Verbosity)

Control how much detail is logged:

```python
from steptrace import Tracer, LogLevel

# DEBUG - Most verbose: all details including call stack
with Tracer(log_level=LogLevel.DEBUG):
    main()

# INFO - Standard: step info, runtime, variables (default)
with Tracer(log_level=LogLevel.INFO):
    main()

# WARNING - Same as INFO (step info, runtime, variables)
with Tracer(log_level=LogLevel.WARNING):
    main()

# SILENT - No output at all
with Tracer(log_level=LogLevel.SILENT):
    main()
```

### Log Output Destination

Choose where to send log output:

```python
from steptrace import Tracer, LogOutput

# FILE - Log to file only (default)
with Tracer(log_output=LogOutput.FILE):
    main()

# STDOUT - Log to stdout only
with Tracer(log_output=LogOutput.STDOUT):
    main()

# STDERR - Log to stderr only
with Tracer(log_output=LogOutput.STDERR):
    main()

# FILE_STDOUT - Log to both file and stdout
with Tracer(log_output=LogOutput.FILE_STDOUT):
    main()

# FILE_STDERR - Log to both file and stderr
with Tracer(log_output=LogOutput.FILE_STDERR):
    main()
```

### Variable Logging Mode

Control how variables are logged:

```python
from steptrace import Tracer, VariableMode

# ALL - Log all variables at each step (default)
with Tracer(variable_mode=VariableMode.ALL):
    main()

# CHANGED - Log only new or changed variables
with Tracer(variable_mode=VariableMode.CHANGED):
    main()

# NONE - Don't log any variables
with Tracer(variable_mode=VariableMode.NONE):
    main()
```

### Combined Configuration

Mix and match options:

```python
from steptrace import Tracer, LogLevel, LogOutput, VariableMode

# Debug to console with only changed variables
with Tracer(
    log_level=LogLevel.DEBUG,
    log_output=LogOutput.STDOUT,
    variable_mode=VariableMode.CHANGED
):
    main()

# WARNING level (same as INFO) to file and stderr, no variables
with Tracer(
    log_level=LogLevel.WARNING,
    log_output=LogOutput.FILE_STDERR,
    variable_mode=VariableMode.NONE
):
    main()
```

---

## Log Output

Logs are written to:

```
.tracer/tracer.log
```

or, if a log already exists:

```
.tracer/tracer_1.log
.tracer/tracer_2.log
...
```

### Example Log Entry (ALL variables mode)

```
--------------------- Step 3 ---------------------
Runtime: 0.0841 ms
/path/to/file.py::main -- line 8

------> Global variables <------
x: int :: 5

------> Local variables <------
y: int :: 10
```

### Example Log Entry (CHANGED variables mode)

```
--------------------- Step 3 ---------------------
Runtime: 0.0841 ms
/path/to/file.py::main -- line 8

------> Local variable changes <------
[NEW] x: int :: 5
[CHANGED] y: int :: 5 -> 10
```

---

## How It Works

The tracer uses Python's `sys.settrace` to intercept execution **on every line** and logs:

- File name
- Function name
- Line number
- Execution time since last step
- Call stack
- Local and global variables

For async tracing, it wraps coroutines and tracks:

- Coroutine creation and completion
- Await points and their durations
- Task creation and completion
- Concurrent operations (gather, tasks)

Only files inside your project workspace are traced to keep output relevant.

---

## Context Manager Behavior

Using the tracer as a context manager ensures:

- Previous trace functions are restored
- Exceptions are **not suppressed**

```python
with Tracer():
    risky_code()
```

---

## When to Use

- Debugging complex logic
- Understanding unfamiliar codebases
- Teaching / learning Python execution flow
- Inspecting variable evolution over time
- **Profiling async applications**
- **Finding slow await points**

---

## Limitations

- Tracing every line may generate large log files
- Not intended for production use
- Performance overhead for long-running programs
- Async tracing requires explicit wrapping of coroutines

---

## Structured Export & Interactive Viewer

Export a structured JSON trace and view it in an interactive TUI:

```bash
# Export trace
python -m steptrace run script.py --export

# View latest trace
python -m steptrace view

# View specific trace file
python -m steptrace view .tracer/trace.json
```

### Type Config (Properties & Functions)

When using `--export`, you can specify a **type config** file that tells the
tracer which extra attributes and method results to record for each type.

Create a Python file (e.g. `type_config.py`):

```python
import numpy as np

# For user-defined classes in the traced script, create stub classes
# with the same name — the tracer matches by class name.
class Sprite:
    pass

CONFIG = {
    # Attributes are read directly; methods are called with no args
    np.ndarray: ["shape", "dtype", "sum"],
    Sprite:     ["is_alive"],
}
```

Run with the config:

```bash
python -m steptrace run script.py --export --type-config type_config.py
python -m steptrace view
```

#### How it works

| Config entry | Kind      | What is recorded |
|---|---|---|
| `"shape"` on `ndarray` | attribute | The value of `arr.shape` |
| `"sum"` on `ndarray`   | function  | The return value of `arr.sum()` |
| `"is_alive"` on `Sprite` | property | The computed value of `sprite.is_alive` |

- **Attributes and `@property`** values are read directly via `getattr`.
- **Zero-argument methods** are *called* and their return value is stored.
  Methods that require arguments are silently skipped.
- For **user-defined classes** in the traced script, matching works by
  class name (not by object identity), so stub classes in the config file
  work seamlessly.
- Config entries are tracked on **every assignment and modification** of the
  variable, not just the first time.
- Types without a useful `__dict__` (like `numpy.ndarray`) are fully
  supported — the config entries provide the attribute data.

See `examples/type_config_example.py` for a complete example.

---

## Testing

Run the test suite:

```bash
python tests/run_all_tests.py
```

Or run individual test files:

```bash
python tests/test_log_level.py
python tests/test_log_output.py
python tests/test_variable_mode.py
python tests/test_all_options.py
python tests/test_config.py
python tests/test_async_tracer.py
python tests/test_cli.py
python tests/test_class_filter_and_type_config.py
```

---

## License

MIT License - free to use, modify, and distribute.
