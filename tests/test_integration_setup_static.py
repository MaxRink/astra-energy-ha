from __future__ import annotations

import ast
from pathlib import Path


def test_unload_callbacks_do_not_register_task_cancel_directly() -> None:
    """Task.cancel returns bool, which Home Assistant may try to schedule."""
    source = (
        Path(__file__).parents[1] / "custom_components" / "astra_energy" / "__init__.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "async_on_unload":
            continue
        assert node.args, "async_on_unload callback is missing"
        callback = node.args[0]
        assert not (
            isinstance(callback, ast.Attribute) and callback.attr == "cancel"
        ), "Wrap Task.cancel so the unload callback returns None"
