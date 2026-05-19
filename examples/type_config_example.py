"""
Example type config for steptrace --type-config.

This file tells the structured tracer which extra attributes and functions
to record for specific types.  Each key is a type, and each value is a
list of attribute names.

  - **Attributes / properties** are read directly (e.g. ``shape``).
  - **Zero-argument methods** are *called* and their return value is
    recorded (e.g. ``sum``).  Methods that require arguments are
    silently skipped.

Usage:
    python -m steptrace run examples/simple_script.py \
        --export --type-config examples/type_config_example.py

    python -m steptrace view
"""

import numpy as np

# For user-defined classes that are defined in the traced script,
# you can create a stub class with the same name — the tracer matches
# by class name, not by identity.

class Vector2D:
    """Stub — matches the Vector2D class in simple_script.py."""
    pass


class Sprite:
    """Stub — matches the Sprite class in simple_script.py."""
    pass


CONFIG = {
    # numpy ndarray: track shape (property) and sum (function call)
    np.ndarray: ["shape", "dtype", "sum"],

    # User-defined classes: track @property values
}
