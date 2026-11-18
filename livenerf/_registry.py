"""Inspect entry point (see [project.entry-points.inspect_ai] in pyproject.toml)."""

from inspect_ai.model import modelapi


@modelapi(name="claudecode")
def claudecode():
    from .providers.claudecode import ClaudeCodeAPI

    return ClaudeCodeAPI


@modelapi(name="codex")
def codex():
    from .providers.codex import CodexAPI

    return CodexAPI


@modelapi(name="codex-study")
def codex_study():
    from .providers.codex.instrument import DriftCodexAPI

    return DriftCodexAPI
