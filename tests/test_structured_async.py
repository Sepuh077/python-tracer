#!/usr/bin/env python3
"""
Tests for async function handling in the StructuredTracer.

Verifies that:
- Coroutine resumptions are merged into a single node (no duplicates).
- Sequential awaits appear as children of the caller.
- asyncio.gather() children are nested under their logical parent.
- Mixed sync/async call trees are structured correctly.
- Async functions are labelled with distinct kind values.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steptrace.structured_tracer import StructuredTracer


# ── Helpers ──────────────────────────────────────────────────────────────────


def _trace_and_load(func, *args, **kwargs):
    """Run *func* under a StructuredTracer and return the parsed call tree."""
    log_dir = tempfile.mkdtemp(prefix="steptrace_test_async_")
    export_path = os.path.join(log_dir, "trace.json")
    try:
        tracer = StructuredTracer(
            export_path=export_path,
            script_path="<test>",
            log_dir=log_dir,
        )
        with tracer:
            func(*args, **kwargs)
        with open(export_path) as f:
            data = json.load(f)
        return data["call_tree"]
    finally:
        shutil.rmtree(log_dir, ignore_errors=True)


def _collect_names(node, depth=0):
    """Return a flat list of (depth, name, kind) tuples."""
    result = [(depth, node["name"], node["kind"])]
    for child in node.get("calls", []):
        result.extend(_collect_names(child, depth + 1))
    return result


def _find_nodes(node, name):
    """Find all nodes with the given name (recursive)."""
    found = []
    if node["name"] == name:
        found.append(node)
    for child in node.get("calls", []):
        found.extend(_find_nodes(child, name))
    return found


def _child_names(node):
    """Return direct children's names."""
    return [c["name"] for c in node.get("calls", [])]


# ── Async helper functions used by tests ─────────────────────────────────────


async def _fetch(name, delay=0.001):
    await asyncio.sleep(delay)
    return f"data-{name}"


async def _process(data):
    await asyncio.sleep(0.001)
    return data.upper()


# ── Tests ────────────────────────────────────────────────────────────────────


def test_single_async_function():
    """A single async function should appear exactly once with kind async_function."""
    async def single():
        await asyncio.sleep(0.001)
        return 42

    def run():
        asyncio.run(single())

    tree = _trace_and_load(run)
    nodes = _find_nodes(tree, "single")
    assert len(nodes) == 1, f"Expected 1 'single' node, got {len(nodes)}"
    assert nodes[0]["kind"] == "async_function", (
        f"Expected kind 'async_function', got '{nodes[0]['kind']}'"
    )
    print("  pass test_single_async_function")


def test_sequential_awaits():
    """Sequential awaits should all be children of the calling coroutine."""
    async def main_seq():
        a = await _fetch("first")
        b = await _fetch("second")
        c = await _fetch("third")
        return (a, b, c)

    def run():
        asyncio.run(main_seq())

    tree = _trace_and_load(run)

    # main_seq should appear exactly once
    main_nodes = _find_nodes(tree, "main_seq")
    assert len(main_nodes) == 1, (
        f"Expected 1 'main_seq' node, got {len(main_nodes)}"
    )

    # All three _fetch calls should be children of main_seq
    main_node = main_nodes[0]
    fetch_children = [c for c in main_node["calls"] if c["name"] == "_fetch"]
    assert len(fetch_children) == 3, (
        f"Expected 3 '_fetch' children, got {len(fetch_children)}"
    )
    print("  pass test_sequential_awaits")


def test_gather_children_nested_under_parent():
    """Coroutines started via asyncio.gather should be children of the caller."""
    async def main_gather():
        results = await asyncio.gather(
            _fetch("a"),
            _fetch("b"),
            _fetch("c"),
        )
        return results

    def run():
        asyncio.run(main_gather())

    tree = _trace_and_load(run)

    main_nodes = _find_nodes(tree, "main_gather")
    assert len(main_nodes) == 1, (
        f"Expected 1 'main_gather' node, got {len(main_nodes)}"
    )

    main_node = main_nodes[0]
    fetch_children = [c for c in main_node["calls"] if c["name"] == "_fetch"]
    assert len(fetch_children) == 3, (
        f"Expected 3 gathered '_fetch' children, got {len(fetch_children)}"
    )

    # None of the _fetch calls should be direct children of <module>
    if tree["name"] == "<module>":
        top_fetches = [c for c in tree["calls"] if c["name"] == "_fetch"]
        assert len(top_fetches) == 0, (
            f"Gathered _fetch should NOT be at module level, found {len(top_fetches)}"
        )
    print("  pass test_gather_children_nested_under_parent")


def test_mixed_sequential_and_gather():
    """Sequential awaits + gather in the same function should all be children."""
    async def main_mixed():
        a = await _fetch("seq1")
        b = await _fetch("seq2")
        gathered = await asyncio.gather(
            _fetch("g1"),
            _fetch("g2"),
        )
        return (a, b, gathered)

    def run():
        asyncio.run(main_mixed())

    tree = _trace_and_load(run)

    main_nodes = _find_nodes(tree, "main_mixed")
    assert len(main_nodes) == 1
    main_node = main_nodes[0]

    fetch_children = [c for c in main_node["calls"] if c["name"] == "_fetch"]
    assert len(fetch_children) == 4, (
        f"Expected 4 total '_fetch' children (2 seq + 2 gather), "
        f"got {len(fetch_children)}"
    )
    print("  pass test_mixed_sequential_and_gather")


def test_mixed_sync_and_async():
    """Sync functions called from async code should appear in the tree."""
    def sync_helper(x):
        return x * 2

    async def main_sync_async():
        a = sync_helper(5)
        b = await _fetch("data")
        c = sync_helper(a)
        return (a, b, c)

    def run():
        asyncio.run(main_sync_async())

    tree = _trace_and_load(run)

    main_nodes = _find_nodes(tree, "main_sync_async")
    assert len(main_nodes) == 1
    main_node = main_nodes[0]

    children = _child_names(main_node)
    assert "sync_helper" in children, (
        f"sync_helper should be a child of main_sync_async, got {children}"
    )
    assert "_fetch" in children, (
        f"_fetch should be a child of main_sync_async, got {children}"
    )

    # sync_helper is a regular function
    sync_nodes = _find_nodes(main_node, "sync_helper")
    for sn in sync_nodes:
        assert sn["kind"] == "function", (
            f"sync_helper should have kind 'function', got '{sn['kind']}'"
        )

    # _fetch is async
    fetch_nodes = _find_nodes(main_node, "_fetch")
    for fn in fetch_nodes:
        assert fn["kind"] == "async_function", (
            f"_fetch should have kind 'async_function', got '{fn['kind']}'"
        )
    print("  pass test_mixed_sync_and_async")


def test_nested_async_calls():
    """Nested async calls (await inside await) should be properly nested."""
    async def inner():
        await asyncio.sleep(0.001)
        return "inner_result"

    async def outer():
        result = await inner()
        return result

    async def top_level():
        return await outer()

    def run():
        asyncio.run(top_level())

    tree = _trace_and_load(run)

    # top_level → outer → inner (nested chain)
    top_nodes = _find_nodes(tree, "top_level")
    assert len(top_nodes) == 1
    top_node = top_nodes[0]

    outer_children = [c for c in top_node["calls"] if c["name"] == "outer"]
    assert len(outer_children) == 1, (
        f"Expected 'outer' as child of 'top_level', got "
        f"{_child_names(top_node)}"
    )

    inner_children = [c for c in outer_children[0]["calls"] if c["name"] == "inner"]
    assert len(inner_children) == 1, (
        f"Expected 'inner' as child of 'outer', got "
        f"{_child_names(outer_children[0])}"
    )
    print("  pass test_nested_async_calls")


def test_no_duplicate_main_with_sequential_awaits():
    """Reproduces the original bug: main() should appear exactly once."""
    async def fetch_data(name, delay=0.001):
        await asyncio.sleep(delay)
        return f"data-{name}"

    async def process_data(data):
        await asyncio.sleep(0.001)
        return data.upper()

    async def main():
        data1 = await fetch_data("first")
        data2 = await fetch_data("second")
        result1 = await process_data(data1)
        result2 = await process_data(data2)
        results = await asyncio.gather(
            fetch_data("a"),
            fetch_data("b"),
            fetch_data("c"),
        )
        return (result1, result2, results)

    def run():
        asyncio.run(main())

    tree = _trace_and_load(run)

    # main should appear exactly once (not 6 times like the old bug)
    main_nodes = _find_nodes(tree, "main")
    assert len(main_nodes) == 1, (
        f"Expected exactly 1 'main' node, got {len(main_nodes)}"
    )

    main_node = main_nodes[0]
    fetch_children = [c for c in main_node["calls"]
                      if c["name"] == "fetch_data"]
    process_children = [c for c in main_node["calls"]
                        if c["name"] == "process_data"]

    assert len(fetch_children) == 5, (
        f"Expected 5 fetch_data (2 seq + 3 gather), got {len(fetch_children)}"
    )
    assert len(process_children) == 2, (
        f"Expected 2 process_data, got {len(process_children)}"
    )
    print("  pass test_no_duplicate_main_with_sequential_awaits")


def test_sync_wrapper_around_async():
    """A sync function calling asyncio.run() should appear as parent."""
    async def async_work():
        await asyncio.sleep(0.001)
        return "done"

    def sync_entry():
        return asyncio.run(async_work())

    tree = _trace_and_load(sync_entry)

    # The sync_entry function should be traceable
    entry_nodes = _find_nodes(tree, "sync_entry")
    assert len(entry_nodes) == 1, (
        f"Expected 1 'sync_entry' node, got {len(entry_nodes)}"
    )

    # async_work should be somewhere in the tree
    work_nodes = _find_nodes(tree, "async_work")
    assert len(work_nodes) == 1, (
        f"Expected 1 'async_work' node, got {len(work_nodes)}"
    )
    assert work_nodes[0]["kind"] == "async_function"
    print("  pass test_sync_wrapper_around_async")


def test_async_variables_tracked():
    """Variable changes inside async functions should be captured."""
    async def compute():
        x = 10
        await asyncio.sleep(0.001)
        x = 20
        y = x + 5
        return y

    def run():
        asyncio.run(compute())

    tree = _trace_and_load(run)

    compute_nodes = _find_nodes(tree, "compute")
    assert len(compute_nodes) == 1
    node = compute_nodes[0]

    var_names = [v["name"] for v in node.get("variables", [])]
    assert "x" in var_names, f"Variable 'x' should be tracked, got {var_names}"
    assert "y" in var_names, f"Variable 'y' should be tracked, got {var_names}"
    print("  pass test_async_variables_tracked")


def test_async_return_value_captured():
    """The return value of an async function should be captured."""
    async def returns_value():
        await asyncio.sleep(0.001)
        return 42

    def run():
        asyncio.run(returns_value())

    tree = _trace_and_load(run)

    nodes = _find_nodes(tree, "returns_value")
    assert len(nodes) == 1
    assert nodes[0]["return_value"] == "42", (
        f"Expected return_value '42', got '{nodes[0]['return_value']}'"
    )
    print("  pass test_async_return_value_captured")


def test_async_args_captured():
    """Arguments to async functions should be captured."""
    async def with_args(name, count=3):
        await asyncio.sleep(0.001)
        return name * count

    async def main_args():
        return await with_args("hello", count=2)

    def run():
        asyncio.run(main_args())

    tree = _trace_and_load(run)

    nodes = _find_nodes(tree, "with_args")
    assert len(nodes) == 1
    args = nodes[0].get("args", {})
    assert "name" in args, f"Arg 'name' should be captured, got {args}"
    assert "count" in args, f"Arg 'count' should be captured, got {args}"
    print("  pass test_async_args_captured")


def test_module_level_not_duplicated():
    """<module> should remain a single root node even with async code."""
    async def simple():
        await asyncio.sleep(0.001)

    def run():
        asyncio.run(simple())

    tree = _trace_and_load(run)

    # Count <module> nodes at any depth
    module_nodes = _find_nodes(tree, "<module>")
    assert len(module_nodes) <= 1, (
        f"Expected at most 1 '<module>' node, got {len(module_nodes)}"
    )
    print("  pass test_module_level_not_duplicated")


# ── Entry point ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("Testing Structured Tracer — Async Support")
    print("=" * 50)
    test_single_async_function()
    test_sequential_awaits()
    test_gather_children_nested_under_parent()
    test_mixed_sequential_and_gather()
    test_mixed_sync_and_async()
    test_nested_async_calls()
    test_no_duplicate_main_with_sequential_awaits()
    test_sync_wrapper_around_async()
    test_async_variables_tracked()
    test_async_return_value_captured()
    test_async_args_captured()
    test_module_level_not_duplicated()
    print("=" * 50)
    print("All structured async tests passed!")
