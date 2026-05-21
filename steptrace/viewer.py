"""
Interactive TUI viewer for structured steptrace data.

Displays the call tree with navigable function calls and variable history.
Uses curses for terminal rendering with color-coded output.

Usage:
    python -m steptrace view [trace.json]
"""

import curses
import glob
import json
import os
import sys


def load_trace(filepath):
    """Load trace data from a JSON file."""
    with open(filepath) as f:
        return json.load(f)


def find_latest_trace(log_dir=".tracer"):
    """Find the most recent trace JSON file in the log directory."""
    pattern = os.path.join(log_dir, "trace*.json")
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


# ── Color pair IDs ──────────────────────────────────────────────────────────

C_FUNC = 1
C_METHOD = 2
C_VAR = 3
C_VALUE = 4
C_TYPE = 5
C_PATH = 6
C_CHANGE = 7
C_HEADER = 8
C_SEP = 9
C_ARG = 10


def _init_colors():
    """Initialize curses color pairs."""
    curses.use_default_colors()
    curses.init_pair(C_FUNC, curses.COLOR_CYAN, -1)
    curses.init_pair(C_METHOD, curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_VAR, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_VALUE, curses.COLOR_GREEN, -1)
    curses.init_pair(C_TYPE, curses.COLOR_WHITE, -1)
    curses.init_pair(C_PATH, curses.COLOR_BLUE, -1)
    curses.init_pair(C_CHANGE, curses.COLOR_RED, -1)
    curses.init_pair(C_HEADER, curses.COLOR_WHITE, -1)
    curses.init_pair(C_SEP, curses.COLOR_WHITE, -1)
    curses.init_pair(C_ARG, curses.COLOR_BLUE, -1)


# ── Safe drawing helpers ────────────────────────────────────────────────────


def _put(win, y, x, text, attr=0):
    """Safely draw text, truncating to fit the window."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    max_len = w - x - 1
    if max_len <= 0:
        return
    try:
        win.addstr(y, x, text[:max_len], attr)
    except curses.error:
        pass


def _hline(win, y, w, char="\u2500"):
    """Draw a horizontal rule."""
    _put(win, y, 0, char * (w - 1), curses.color_pair(C_SEP) | curses.A_DIM)


# ── Viewer class ────────────────────────────────────────────────────────────


class Viewer:
    """Interactive trace viewer powered by curses."""

    def __init__(self, data):
        self.data = data
        self.meta = data.get("metadata", {})
        self.root = data.get("call_tree")

        # Navigation state
        self.path_stack = []  # [(node, selected_idx, scroll_offset)]
        self.node = self.root
        self.sel = 0
        self.scroll = 0
        self.mode = "tree"  # "tree" | "variable" | "instance"
        self.cur_var = None
        self.var_sel = 0
        self.var_scroll = 0

        # Instance inspection state
        self.instance_stack = []   # [(data, keys, sel, scroll)]
        self.instance_data = None
        self.instance_keys = []
        self.instance_sel = 0
        self.instance_scroll = 0
        self.instance_path = []    # [(name, type)] breadcrumb

        # Exception inspection state
        self.cur_exception = None

    # ── Item list ───────────────────────────────────────────────────────

    def _items(self):
        """Return displayable items in step order: calls, variable events, exceptions."""
        items = []
        if self.node is None:
            return items

        # Collect calls with their step numbers
        for c in self.node.get("calls", []):
            step = c.get("step_start", 0)
            items.append((step, "call", c, None))

        # Collect individual variable history events
        for v in self.node.get("variables", []):
            for h in v.get("history", []):
                step = h.get("step", 0)
                items.append((step, "var_event", v, h))

        # Collect exception events
        for exc in self.node.get("exceptions", []):
            step = exc.get("step", 0)
            items.append((step, "exception", exc, None))

        # Sort by step number
        items.sort(key=lambda x: x[0])

        # Return as 3-tuples: (kind, data, extra)
        return [(kind, data, extra) for _, kind, data, extra in items]

    # ── Navigation ──────────────────────────────────────────────────────

    def _enter(self):
        if self.mode == "tree":
            items = self._items()
            if not items or self.sel >= len(items):
                return
            kind, data, extra = items[self.sel]
            if kind == "call":
                self.path_stack.append((self.node, self.sel, self.scroll))
                self.node = data
                self.sel = 0
                self.scroll = 0
            elif kind == "var_event":
                self.mode = "variable"
                self.cur_var = data
                # Jump to the specific history entry the user clicked on
                idx = 0
                for i, h in enumerate(data.get("history", [])):
                    if h is extra:
                        idx = i
                        break
                self.var_sel = idx
                self.var_scroll = 0
            elif kind == "exception":
                self.mode = "exception"
                self.cur_exception = data
        elif self.mode == "variable":
            if self.cur_var:
                history = self.cur_var.get("history", [])
                if 0 <= self.var_sel < len(history):
                    entry = history[self.var_sel]
                    value_data = entry.get("value_data")
                    if value_data:
                        self.mode = "instance"
                        self.instance_stack = []
                        self.instance_data = value_data
                        self.instance_keys = list(value_data.keys())
                        self.instance_sel = 0
                        self.instance_scroll = 0
                        var_name = self.cur_var.get("name", "?")
                        val_type = entry.get("value_type", "?")
                        self.instance_path = [(var_name, val_type)]
        elif self.mode == "instance":
            if (self.instance_keys
                    and 0 <= self.instance_sel < len(self.instance_keys)):
                key = self.instance_keys[self.instance_sel]
                attr = self.instance_data.get(key, {})
                nested = attr.get("attrs")
                if nested:
                    self.instance_stack.append(
                        (self.instance_data, self.instance_keys,
                         self.instance_sel, self.instance_scroll))
                    self.instance_data = nested
                    self.instance_keys = list(nested.keys())
                    self.instance_sel = 0
                    self.instance_scroll = 0
                    self.instance_path.append(
                        (key, attr.get("type", "?")))

    def _back(self):
        if self.mode == "exception":
            self.mode = "tree"
            self.cur_exception = None
            return
        if self.mode == "instance":
            if self.instance_stack:
                (self.instance_data, self.instance_keys,
                 self.instance_sel, self.instance_scroll
                 ) = self.instance_stack.pop()
                self.instance_path.pop()
            else:
                self.mode = "variable"
                self.instance_data = None
                self.instance_keys = []
                self.instance_path = []
            return
        if self.mode == "variable":
            self.mode = "tree"
            self.cur_var = None
            return
        if self.path_stack:
            self.node, self.sel, self.scroll = self.path_stack.pop()

    def _breadcrumb(self):
        parts = []
        for nd, _, _ in self.path_stack:
            n = nd.get("name", "?")
            cls = nd.get("class_name")
            parts.append(f"{cls}.{n}" if cls else n)
        n = self.node.get("name", "?") if self.node else "?"
        cls = self.node.get("class_name") if self.node else None
        parts.append(f"{cls}.{n}" if cls else n)
        return " > ".join(parts)

    # ── Main loop ───────────────────────────────────────────────────────

    def run(self):
        curses.wrapper(self._main)

    def _main(self, stdscr):
        curses.curs_set(0)
        _init_colors()
        stdscr.timeout(-1)

        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()

            if h < 8 or w < 30:
                _put(stdscr, 0, 0, "Terminal too small! (min 30x8)",
                     curses.A_BOLD)
                stdscr.refresh()
                if stdscr.getch() == ord("q"):
                    break
                continue

            if self.mode == "tree":
                self._draw_tree(stdscr, h, w)
            elif self.mode == "exception":
                self._draw_exception_detail(stdscr, h, w)
            elif self.mode == "instance":
                self._draw_instance(stdscr, h, w)
            else:
                self._draw_variable(stdscr, h, w)

            stdscr.refresh()
            key = stdscr.getch()

            if key == ord("q") or key == ord("Q"):
                break
            elif key == curses.KEY_UP or key == ord("k"):
                self._on_up(h)
            elif key == curses.KEY_DOWN or key == ord("j"):
                self._on_down(h)
            elif key in (10, curses.KEY_ENTER, curses.KEY_RIGHT, ord("l")):
                self._enter()
            elif key in (27, curses.KEY_BACKSPACE, curses.KEY_LEFT, 127,
                         ord("h")):
                self._back()
            elif key == ord("g"):
                self._go_top()
            elif key == ord("G"):
                self._go_bottom()

    # ── Key handlers ────────────────────────────────────────────────────

    def _on_up(self, h):
        if self.mode == "variable":
            if self.var_sel > 0:
                self.var_sel -= 1
        elif self.mode == "instance":
            if self.instance_sel > 0:
                self.instance_sel -= 1
        else:
            if self.sel > 0:
                self.sel -= 1

    def _on_down(self, h):
        if self.mode == "variable":
            if self.cur_var:
                history = self.cur_var.get("history", [])
                if self.var_sel < len(history) - 1:
                    self.var_sel += 1
        elif self.mode == "instance":
            if self.instance_sel < len(self.instance_keys) - 1:
                self.instance_sel += 1
        else:
            items = self._items()
            if self.sel < len(items) - 1:
                self.sel += 1

    def _go_top(self):
        if self.mode == "variable":
            self.var_sel = 0
            self.var_scroll = 0
        elif self.mode == "instance":
            self.instance_sel = 0
            self.instance_scroll = 0
        else:
            self.sel = 0
            self.scroll = 0

    def _go_bottom(self):
        if self.mode == "variable":
            if self.cur_var:
                history = self.cur_var.get("history", [])
                if history:
                    self.var_sel = len(history) - 1
        elif self.mode == "instance":
            if self.instance_keys:
                self.instance_sel = len(self.instance_keys) - 1
        else:
            items = self._items()
            if items:
                self.sel = len(items) - 1

    # ── Drawing: shared ─────────────────────────────────────────────────

    def _draw_header(self, win, h, w):
        """Draw title bar and metadata. Returns next row."""
        # Title bar
        title = " STEPTRACE VIEWER "
        _put(win, 0, 0, " " * (w - 1),
             curses.color_pair(C_HEADER) | curses.A_REVERSE)
        _put(win, 0, 0, title,
             curses.color_pair(C_HEADER) | curses.A_BOLD | curses.A_REVERSE)

        # Metadata
        script = os.path.basename(self.meta.get("script", "unknown"))
        steps = self.meta.get("total_steps", 0)
        dur = self.meta.get("total_duration_ms", 0)
        info = f" {script}  |  {steps} steps  |  {dur:.2f} ms"
        _put(win, 1, 0, info, curses.color_pair(C_TYPE))
        _hline(win, 2, w)
        return 3

    def _draw_footer(self, win, h, w):
        """Draw the keybinding footer."""
        row = h - 1
        _put(win, row, 0, " " * (w - 1), curses.A_REVERSE)
        if self.mode == "tree":
            txt = " \u2191\u2193/jk Navigate | Enter/\u2192 Open | Esc/\u2190 Back | g/G Top/Bottom | q Quit "
        elif self.mode == "exception":
            txt = " Esc/\u2190 Back | q Quit "
        elif self.mode == "instance":
            txt = " \u2191\u2193/jk Navigate | Enter/\u2192 Expand | Esc/\u2190 Back | g/G Top/Bottom | q Quit "
        else:
            txt = " \u2191\u2193/jk Navigate | Enter/\u2192 Inspect | Esc/\u2190 Back | g/G Top/Bottom | q Quit "
        _put(win, row, 0, txt, curses.A_REVERSE)

    # ── Drawing: tree view ──────────────────────────────────────────────

    def _draw_tree(self, win, h, w):
        row = self._draw_header(win, h, w)

        # Breadcrumb
        _put(win, row, 1, "Path: ",
             curses.color_pair(C_TYPE) | curses.A_DIM)
        _put(win, row, 7, self._breadcrumb(),
             curses.color_pair(C_PATH) | curses.A_BOLD)
        row += 1
        _hline(win, row, w)
        row += 1

        # Current node summary
        nd = self.node
        if nd:
            kind = nd.get("kind", "function")
            name = nd.get("name", "?")
            cls = nd.get("class_name")
            color = C_METHOD if cls else C_FUNC
            label = f"{cls}.{name}" if cls else name
            file_info = f"{nd.get('file', '?')}:{nd.get('line_start', '?')}"
            dur = nd.get("duration_ms")
            dur_str = f"  {dur:.2f} ms" if dur else ""

            _put(win, row, 1, label,
                 curses.color_pair(color) | curses.A_BOLD)
            off = len(label) + 1
            _put(win, row, off + 1, f"({kind})",
                 curses.color_pair(C_TYPE) | curses.A_DIM)
            off += len(f"({kind})") + 2
            _put(win, row, off + 1, f"[{file_info}]{dur_str}",
                 curses.color_pair(C_TYPE) | curses.A_DIM)
            row += 1

            # Args
            if nd.get("args"):
                args_str = ", ".join(f"{k}={v}" for k, v in nd["args"].items())
                if len(args_str) > w - 12:
                    args_str = args_str[: w - 15] + "..."
                _put(win, row, 3, "args: ",
                     curses.color_pair(C_TYPE) | curses.A_DIM)
                _put(win, row, 9, args_str,
                     curses.color_pair(C_ARG))
                row += 1

            # Return value
            ret = nd.get("return_value")
            if ret is not None:
                ret_str = str(ret)
                if len(ret_str) > w - 14:
                    ret_str = ret_str[: w - 17] + "..."
                _put(win, row, 3, "returns: ",
                     curses.color_pair(C_TYPE) | curses.A_DIM)
                _put(win, row, 12, ret_str,
                     curses.color_pair(C_VALUE))
                row += 1

        _hline(win, row, w)
        row += 1

        # Items (calls + variable events + exceptions, in step order)
        items = self._items()
        content_top = row
        content_h = h - content_top - 1  # leave 1 for footer

        if not items:
            _put(win, row + 1, 3, "No calls or variables recorded.",
                 curses.color_pair(C_TYPE) | curses.A_DIM)
        else:
            # Adjust scroll so selected item is visible
            if self.sel < self.scroll:
                self.scroll = self.sel
            if self.sel >= self.scroll + content_h:
                self.scroll = self.sel - content_h + 1

            drawn = 0
            for i in range(self.scroll, len(items)):
                if drawn >= content_h:
                    break
                y = content_top + drawn

                kind, data, extra = items[i]
                is_sel = i == self.sel

                if kind == "call":
                    self._draw_call_row(win, y, w, data, is_sel)
                elif kind == "var_event":
                    self._draw_var_event_row(win, y, w, data, extra, is_sel)
                elif kind == "exception":
                    self._draw_exception_row(win, y, w, data, is_sel)
                drawn += 1

        self._draw_footer(win, h, w)

    def _draw_call_row(self, win, y, w, data, selected):
        """Draw one function-call row."""
        attr = curses.A_REVERSE if selected else 0
        if selected:
            _put(win, y, 0, " " * (w - 1), attr)

        prefix = " \u25b6 " if selected else "   "
        _put(win, y, 0, prefix, attr)

        name = data.get("name", "?")
        cls = data.get("class_name")
        label = f"{cls}.{name}" if cls else name
        color = C_METHOD if cls else C_FUNC
        off = len(prefix)

        _put(win, y, off, label,
             curses.color_pair(color) | curses.A_BOLD | attr)
        off += len(label)

        kind_str = f" ({data.get('kind', 'function')})"
        _put(win, y, off, kind_str,
             curses.color_pair(C_TYPE) | curses.A_DIM | attr)
        off += len(kind_str)

        # Exception indicator for calls that raised
        exceptions = data.get("exceptions", [])
        if exceptions:
            exc_type = exceptions[0].get("type", "Exception")
            exc_str = f" !! {exc_type}"
            _put(win, y, off, exc_str,
                 curses.color_pair(C_CHANGE) | curses.A_BOLD | attr)
        else:
            # Inline args preview
            args = data.get("args")
            if args:
                args_str = ", ".join(f"{k}={v}" for k, v in args.items())
                avail = w - off - 4
                if avail > 5:
                    if len(args_str) > avail:
                        args_str = args_str[: avail - 3] + "..."
                    _put(win, y, off + 2, args_str,
                         curses.color_pair(C_VALUE) | curses.A_DIM | attr)

    def _draw_var_row(self, win, y, w, data, selected):
        """Draw one variable row."""
        attr = curses.A_REVERSE if selected else 0
        if selected:
            _put(win, y, 0, " " * (w - 1), attr)

        prefix = " \u25b6 " if selected else "   "
        _put(win, y, 0, prefix, attr)
        off = len(prefix)

        name = data.get("name", "?")
        _put(win, y, off, name,
             curses.color_pair(C_VAR) | curses.A_BOLD | attr)
        off += len(name)

        vtype = data.get("type", "?")
        type_str = f" ({vtype})"
        _put(win, y, off, type_str,
             curses.color_pair(C_TYPE) | curses.A_DIM | attr)
        off += len(type_str)

        # Final value
        val = data.get("final_value", "?")
        val_str = f" = {val}"
        avail = w - off - 20
        if avail > 3:
            if len(val_str) > avail:
                val_str = val_str[: avail - 3] + "..."
            _put(win, y, off, val_str,
                 curses.color_pair(C_VALUE) | attr)
            off += len(val_str)

        # Change count badge
        history = data.get("history", [])
        mods = sum(1 for h in history if h.get("action") == "modify")
        if mods > 0:
            badge = f" [{mods}x changed]"
            _put(win, y, off + 1, badge,
                 curses.color_pair(C_CHANGE) | attr)

    def _draw_var_event_row(self, win, y, w, var, entry, selected):
        """Draw one variable event row (inline in step-ordered list)."""
        attr = curses.A_REVERSE if selected else 0
        if selected:
            _put(win, y, 0, " " * (w - 1), attr)

        prefix = " \u25b6 " if selected else "   "
        _put(win, y, 0, prefix, attr)
        off = len(prefix)

        name = var.get("name", "?")
        action = entry.get("action", "assign")
        value = entry.get("value", "?")
        val_type = entry.get("value_type", "?")

        # Variable name
        _put(win, y, off, name,
             curses.color_pair(C_VAR) | curses.A_BOLD | attr)
        off += len(name)

        # Value
        val_str = f" = {value}"
        type_str = f" ({val_type})"
        reserve = len(type_str) + 4
        avail = w - off - reserve
        if avail > 3 and len(val_str) > avail:
            val_str = val_str[: avail - 3] + "..."
        _put(win, y, off, val_str,
             curses.color_pair(C_VALUE) | attr)
        off += min(len(val_str), w - off - len(type_str) - 2)

        # Type
        _put(win, y, off, type_str,
             curses.color_pair(C_TYPE) | curses.A_DIM | attr)
        off += len(type_str)

        # Action badge for modifications
        if action == "modify":
            badge = " [modified]"
            _put(win, y, off, badge,
                 curses.color_pair(C_CHANGE) | curses.A_DIM | attr)

    def _draw_exception_row(self, win, y, w, exc, selected):
        """Draw one exception row in the step-ordered list."""
        attr = curses.A_REVERSE if selected else 0
        if selected:
            _put(win, y, 0, " " * (w - 1), attr)

        prefix = " \u25b6 " if selected else "   "
        _put(win, y, 0, prefix, attr)
        off = len(prefix)

        exc_type = exc.get("type", "Exception")
        exc_msg = exc.get("message", "")
        line = exc.get("line", "?")

        _put(win, y, off, "!! ",
             curses.color_pair(C_CHANGE) | curses.A_BOLD | attr)
        off += 3

        _put(win, y, off, exc_type,
             curses.color_pair(C_CHANGE) | curses.A_BOLD | attr)
        off += len(exc_type)

        msg_str = f": {exc_msg}" if exc_msg else ""
        avail = w - off - 15
        if avail > 3 and len(msg_str) > avail:
            msg_str = msg_str[: avail - 3] + "..."
        if msg_str:
            _put(win, y, off, msg_str,
                 curses.color_pair(C_CHANGE) | attr)
            off += len(msg_str)

        line_str = f"  (line {line})"
        _put(win, y, off, line_str,
             curses.color_pair(C_TYPE) | curses.A_DIM | attr)

    # ── Drawing: exception detail view ──────────────────────────────────

    def _draw_exception_detail(self, win, h, w):
        """Draw exception detail view (after clicking on an exception)."""
        row = self._draw_header(win, h, w)

        exc = self.cur_exception
        if not exc:
            return

        exc_type = exc.get("type", "Exception")
        exc_msg = exc.get("message", "")
        line = exc.get("line", "?")
        step = exc.get("step", "?")

        # Exception title
        _put(win, row, 1, "Exception: ",
             curses.color_pair(C_TYPE))
        _put(win, row, 12, exc_type,
             curses.color_pair(C_CHANGE) | curses.A_BOLD)
        row += 1

        # Message
        if exc_msg:
            _put(win, row, 1, "Message: ",
                 curses.color_pair(C_TYPE))
            msg_avail = w - 11
            msg_display = exc_msg[:msg_avail] if len(exc_msg) > msg_avail else exc_msg
            _put(win, row, 10, msg_display,
                 curses.color_pair(C_VALUE))
            row += 1

        # Location
        _put(win, row, 1, f"Line: {line}  |  Step: {step}",
             curses.color_pair(C_TYPE) | curses.A_DIM)
        row += 1

        # Context breadcrumb
        _put(win, row, 1, "in: ",
             curses.color_pair(C_TYPE) | curses.A_DIM)
        _put(win, row, 5, self._breadcrumb(),
             curses.color_pair(C_PATH) | curses.A_DIM)
        row += 1

        _hline(win, row, w)
        row += 1

        # Traceback
        tb_lines = exc.get("traceback", [])
        if tb_lines:
            _put(win, row, 1, "Traceback:",
                 curses.color_pair(C_HEADER) | curses.A_BOLD)
            row += 1

            for tb_line in tb_lines:
                for sub_line in tb_line.rstrip().split('\n'):
                    if row >= h - 1:
                        break
                    _put(win, row, 3, sub_line,
                         curses.color_pair(C_TYPE) | curses.A_DIM)
                    row += 1
        else:
            _put(win, row, 3, "No traceback available.",
                 curses.color_pair(C_TYPE) | curses.A_DIM)

        self._draw_footer(win, h, w)

    # ── Drawing: variable history view ──────────────────────────────────

    def _draw_variable(self, win, h, w):
        row = self._draw_header(win, h, w)

        var = self.cur_var
        if not var:
            return

        name = var.get("name", "?")
        vtype = var.get("type", "?")

        # Variable title
        _put(win, row, 1, "Variable: ",
             curses.color_pair(C_TYPE))
        _put(win, row, 11, name,
             curses.color_pair(C_VAR) | curses.A_BOLD)
        _put(win, row, 11 + len(name), f" ({vtype})",
             curses.color_pair(C_TYPE) | curses.A_DIM)
        row += 1

        # Context breadcrumb
        _put(win, row, 1, "in: ",
             curses.color_pair(C_TYPE) | curses.A_DIM)
        _put(win, row, 5, self._breadcrumb(),
             curses.color_pair(C_PATH) | curses.A_DIM)
        row += 1
        _hline(win, row, w)
        row += 1

        # Column header
        hdr = "  {:<6} | {:<6} | {:<9} | {}".format(
            "Step", "Line", "Action", "Value")
        _put(win, row, 0, hdr,
             curses.color_pair(C_HEADER) | curses.A_BOLD)
        row += 1
        _hline(win, row, w, "\u2500")
        row += 1

        history = var.get("history", [])
        if not history:
            _put(win, row + 1, 3, "No history recorded.",
                 curses.color_pair(C_TYPE) | curses.A_DIM)
            self._draw_footer(win, h, w)
            return

        # Clamp var_sel
        if self.var_sel >= len(history):
            self.var_sel = len(history) - 1
        if self.var_sel < 0:
            self.var_sel = 0

        content_top = row
        content_h = h - content_top - 1

        # Compute line offsets per entry for scroll management
        total_lines = 0
        sel_line_start = 0
        sel_line_end = 0
        for i, entry in enumerate(history):
            if i == self.var_sel:
                sel_line_start = total_lines
            lines = 1
            if (entry.get("old_value")
                    and entry.get("action", "").upper() == "MODIFY"):
                lines += 1
            total_lines += lines
            if i == self.var_sel:
                sel_line_end = total_lines

        # Adjust scroll to keep selected entry visible
        if sel_line_start < self.var_scroll:
            self.var_scroll = sel_line_start
        if sel_line_end > self.var_scroll + content_h:
            self.var_scroll = sel_line_end - content_h
        max_scroll = max(0, total_lines - content_h)
        self.var_scroll = max(0, min(self.var_scroll, max_scroll))

        drawn = 0
        logical_row = 0

        for i, entry in enumerate(history):
            if drawn >= content_h:
                break

            is_sel = (i == self.var_sel)
            has_data = bool(entry.get("value_data"))

            line_no = entry.get("line", "?")
            step = entry.get("step", "?")
            action = entry.get("action", "?").upper()
            value = entry.get("value", "")
            val_type = entry.get("value_type", "")
            old_value = entry.get("old_value")

            # Action styling
            if action == "ASSIGN":
                a_color = C_FUNC
                a_label = "ASSIGNED "
            elif action == "MODIFY":
                a_color = C_CHANGE
                a_label = "MODIFIED "
            elif action == "DELETE":
                a_color = C_CHANGE
                a_label = "DELETED  "
            elif action == "ARG":
                a_color = C_ARG
                a_label = "ARGUMENT "
            else:
                a_color = C_TYPE
                a_label = f"{action:<9}"

            # Main line
            if logical_row >= self.var_scroll:
                y = content_top + drawn
                sel_attr = curses.A_REVERSE if is_sel else 0

                if is_sel:
                    _put(win, y, 0, " " * (w - 1), sel_attr)

                info = f"  {str(step):<6}| {str(line_no):<6}| "
                _put(win, y, 0, info,
                     curses.color_pair(C_TYPE) | curses.A_DIM | sel_attr)
                off = len(info)

                _put(win, y, off, a_label,
                     curses.color_pair(a_color) | curses.A_BOLD | sel_attr)
                off += len(a_label)

                if action != "DELETE":
                    val_display = f"| {name} = {value}"
                    reserve = 15 + (4 if has_data else 0)
                    avail = w - off - reserve
                    if avail > 3 and len(val_display) > avail:
                        val_display = val_display[: avail - 3] + "..."
                    _put(win, y, off, val_display,
                         curses.color_pair(C_VALUE) | sel_attr)
                    off += min(len(val_display), w - off - 8)

                    type_tag = f"  ({val_type})"
                    _put(win, y, off, type_tag,
                         curses.color_pair(C_TYPE) | curses.A_DIM | sel_attr)
                    off += len(type_tag)

                    # Expand indicator for class instances
                    if has_data:
                        _put(win, y, off + 1, "\u25b6",
                             curses.color_pair(C_FUNC) | curses.A_BOLD
                             | sel_attr)

                drawn += 1

            logical_row += 1

            # Old-value line for modifications
            if old_value and action == "MODIFY":
                if logical_row >= self.var_scroll and drawn < content_h:
                    y = content_top + drawn
                    sel_attr = curses.A_REVERSE if is_sel else 0
                    if is_sel:
                        _put(win, y, 0, " " * (w - 1), sel_attr)
                    pad = "        " + " " * 8
                    old_str = f"{pad}  was: {old_value}"
                    if len(old_str) > w - 2:
                        old_str = old_str[: w - 5] + "..."
                    _put(win, y, 0, old_str,
                         curses.color_pair(C_CHANGE) | curses.A_DIM
                         | sel_attr)
                    drawn += 1
                logical_row += 1

        self._draw_footer(win, h, w)


    # ── Drawing: instance inspection view ──────────────────────────────

    def _draw_instance(self, win, h, w):
        row = self._draw_header(win, h, w)

        # Instance path breadcrumb
        if self.instance_path:
            path_str = ".".join(n for n, _ in self.instance_path)
            cur_type = self.instance_path[-1][1]
        else:
            path_str = "?"
            cur_type = "?"

        _put(win, row, 1, "Instance: ",
             curses.color_pair(C_TYPE))
        _put(win, row, 11, path_str,
             curses.color_pair(C_VAR) | curses.A_BOLD)
        _put(win, row, 11 + len(path_str), f"  ({cur_type})",
             curses.color_pair(C_TYPE) | curses.A_DIM)
        row += 1

        # Context breadcrumb
        _put(win, row, 1, "in: ",
             curses.color_pair(C_TYPE) | curses.A_DIM)
        _put(win, row, 5, self._breadcrumb(),
             curses.color_pair(C_PATH) | curses.A_DIM)
        row += 1
        _hline(win, row, w)
        row += 1

        # Column header
        _put(win, row, 0, "  Attribute",
             curses.color_pair(C_HEADER) | curses.A_BOLD)
        row += 1
        _hline(win, row, w, "\u2500")
        row += 1

        keys = self.instance_keys
        if not keys:
            _put(win, row + 1, 3, "No attributes found.",
                 curses.color_pair(C_TYPE) | curses.A_DIM)
            self._draw_footer(win, h, w)
            return

        # Clamp selection
        if self.instance_sel >= len(keys):
            self.instance_sel = len(keys) - 1
        if self.instance_sel < 0:
            self.instance_sel = 0

        content_top = row
        content_h = h - content_top - 1

        # Adjust scroll
        if self.instance_sel < self.instance_scroll:
            self.instance_scroll = self.instance_sel
        if self.instance_sel >= self.instance_scroll + content_h:
            self.instance_scroll = self.instance_sel - content_h + 1

        drawn = 0
        for i in range(self.instance_scroll, len(keys)):
            if drawn >= content_h:
                break
            y = content_top + drawn
            key = keys[i]
            attr = self.instance_data.get(key, {})
            is_sel = (i == self.instance_sel)
            has_children = bool(attr.get("attrs"))

            sel_attr = curses.A_REVERSE if is_sel else 0
            if is_sel:
                _put(win, y, 0, " " * (w - 1), sel_attr)

            prefix = " \u25b6 " if is_sel else "   "
            _put(win, y, 0, prefix, sel_attr)
            off = len(prefix)

            # Attribute name (append "()" for function-sourced values)
            source = attr.get("source", "")
            display_key = f"{key}()" if source == "function" else key
            _put(win, y, off, display_key,
                 curses.color_pair(C_VAR) | curses.A_BOLD | sel_attr)
            off += len(display_key)

            # Type
            type_str = f" ({attr.get('type', '?')})"
            _put(win, y, off, type_str,
                 curses.color_pair(C_TYPE) | curses.A_DIM | sel_attr)
            off += len(type_str)

            # Value
            val = attr.get("value", "?")
            val_str = f" = {val}"
            reserve = 4 if has_children else 1
            avail = w - off - reserve
            if avail > 3:
                if len(val_str) > avail:
                    val_str = val_str[: avail - 3] + "..."
                _put(win, y, off, val_str,
                     curses.color_pair(C_VALUE) | sel_attr)
                off += min(len(val_str), w - off - reserve)

            # Expand indicator for nested instances
            if has_children:
                _put(win, y, off + 1, "\u25b6",
                     curses.color_pair(C_FUNC) | curses.A_BOLD | sel_attr)

            drawn += 1

        self._draw_footer(win, h, w)


# ── Entry point ─────────────────────────────────────────────────────────────


def main(filepath=None):
    """Run the viewer on a trace file."""
    if filepath is None:
        filepath = find_latest_trace()
        if filepath is None:
            print(
                "No trace file found. Run with --export first:\n"
                "  python -m steptrace run script.py --export\n"
                "Or specify a file:\n"
                "  python -m steptrace view path/to/trace.json"
            )
            return 1
        print(f"Auto-detected: {filepath}")

    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return 1

    try:
        data = load_trace(filepath)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
        return 1

    if "call_tree" not in data or data["call_tree"] is None:
        print("Error: No call tree data found in trace file.")
        return 1

    viewer = Viewer(data)
    viewer.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())