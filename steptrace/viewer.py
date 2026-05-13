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
        self.mode = "tree"  # "tree" | "variable"
        self.cur_var = None
        self.var_scroll = 0

    # ── Item list ───────────────────────────────────────────────────────

    def _items(self):
        """Return displayable items: calls then variables."""
        items = []
        if self.node is None:
            return items
        for c in self.node.get("calls", []):
            items.append(("call", c))
        for v in self.node.get("variables", []):
            items.append(("variable", v))
        return items

    # ── Navigation ──────────────────────────────────────────────────────

    def _enter(self):
        items = self._items()
        if not items or self.sel >= len(items):
            return
        kind, data = items[self.sel]
        if kind == "call":
            self.path_stack.append((self.node, self.sel, self.scroll))
            self.node = data
            self.sel = 0
            self.scroll = 0
        elif kind == "variable":
            self.mode = "variable"
            self.cur_var = data
            self.var_scroll = 0

    def _back(self):
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
            self.var_scroll = max(0, self.var_scroll - 1)
        else:
            if self.sel > 0:
                self.sel -= 1

    def _on_down(self, h):
        if self.mode == "variable":
            self.var_scroll += 1
        else:
            items = self._items()
            if self.sel < len(items) - 1:
                self.sel += 1

    def _go_top(self):
        if self.mode == "variable":
            self.var_scroll = 0
        else:
            self.sel = 0
            self.scroll = 0

    def _go_bottom(self):
        if self.mode != "variable":
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
        else:
            txt = " \u2191\u2193/jk Scroll | Esc/\u2190 Back | q Quit "
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

        # Items (calls + variables)
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

            # Find the transition index where calls end and variables begin
            first_var_idx = None
            for i, (k, _) in enumerate(items):
                if k == "variable":
                    first_var_idx = i
                    break

            drawn = 0
            for i in range(self.scroll, len(items)):
                if drawn >= content_h:
                    break
                y = content_top + drawn

                kind, data = items[i]
                is_sel = i == self.sel

                # Section separator before variables
                if i == first_var_idx and first_var_idx > 0:
                    if drawn < content_h:
                        _put(win, y, 3, "\u2500\u2500 Variables \u2500\u2500",
                             curses.color_pair(C_SEP) | curses.A_DIM)
                        drawn += 1
                        y += 1
                        if drawn >= content_h:
                            break

                if kind == "call":
                    self._draw_call_row(win, y, w, data, is_sel)
                else:
                    self._draw_var_row(win, y, w, data, is_sel)
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

        content_top = row
        content_h = h - content_top - 1

        # Clamp var_scroll
        max_scroll = max(0, len(history) * 2 - content_h)
        if self.var_scroll > max_scroll:
            self.var_scroll = max_scroll

        drawn = 0
        logical_row = 0  # counts rendered lines across all entries

        for entry in history:
            if drawn >= content_h:
                break

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

                info = f"  {str(step):<6}| {str(line_no):<6}| "
                _put(win, y, 0, info,
                     curses.color_pair(C_TYPE) | curses.A_DIM)
                off = len(info)

                _put(win, y, off, a_label,
                     curses.color_pair(a_color) | curses.A_BOLD)
                off += len(a_label)

                if action != "DELETE":
                    val_display = f"| {name} = {value}"
                    avail = w - off - 15
                    if avail > 3 and len(val_display) > avail:
                        val_display = val_display[: avail - 3] + "..."
                    _put(win, y, off, val_display,
                         curses.color_pair(C_VALUE))
                    off += min(len(val_display), w - off - 2)

                    type_tag = f"  ({val_type})"
                    _put(win, y, off, type_tag,
                         curses.color_pair(C_TYPE) | curses.A_DIM)

                drawn += 1

            logical_row += 1

            # Old-value line for modifications
            if old_value and action == "MODIFY":
                if logical_row >= self.var_scroll and drawn < content_h:
                    y = content_top + drawn
                    pad = "        " + " " * 8
                    old_str = f"{pad}  was: {old_value}"
                    if len(old_str) > w - 2:
                        old_str = old_str[: w - 5] + "..."
                    _put(win, y, 0, old_str,
                         curses.color_pair(C_CHANGE) | curses.A_DIM)
                    drawn += 1
                logical_row += 1

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