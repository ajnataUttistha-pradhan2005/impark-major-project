"""LangChain callback dispatch helpers for agent executions."""

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def emit_agent_start(
    callbacks: Any, name: str, input_str: str, run_id: Optional[str] = None
) -> None:
    if not callbacks:
        return
    handlers = callbacks if isinstance(callbacks, list) else [callbacks]
    for handler in handlers:
        if hasattr(handler, "on_tool_start"):
            try:
                handler.on_tool_start(
                    serialized={"name": name},
                    input_str=input_str,
                    run_id=run_id or name,
                )
            except Exception as err:
                logger.debug("Callback on_tool_start exception: %s", err)


def emit_agent_end(
    callbacks: Any,
    name: str,
    output: Any,
    run_id: Optional[str] = None,
    latency_ms: Optional[float] = None,
    context_snippets: Optional[List[str]] = None,
) -> None:
    if not callbacks:
        return
    handlers = callbacks if isinstance(callbacks, list) else [callbacks]
    for handler in handlers:
        if hasattr(handler, "on_tool_end"):
            try:
                handler.on_tool_end(output, run_id=run_id or name)
            except Exception as err:
                logger.debug("Callback on_tool_end exception: %s", err)
        if latency_ms is not None and hasattr(handler, "record_node"):
            try:
                handler.record_node(name, latency_ms)
            except Exception as err:
                logger.debug("Callback record_node exception: %s", err)
        if context_snippets and hasattr(handler, "add_context"):
            for snippet in context_snippets:
                try:
                    handler.add_context(snippet)
                except Exception as err:
                    logger.debug("Callback add_context exception: %s", err)


def emit_agent_error(
    callbacks: Any,
    name: str,
    error: BaseException,
    run_id: Optional[str] = None,
    latency_ms: Optional[float] = None,
) -> None:
    if not callbacks:
        return
    handlers = callbacks if isinstance(callbacks, list) else [callbacks]
    for handler in handlers:
        if hasattr(handler, "on_tool_error"):
            try:
                handler.on_tool_error(error, run_id=run_id or name)
            except Exception as err:
                logger.debug("Callback on_tool_error exception: %s", err)
        if latency_ms is not None and hasattr(handler, "record_node"):
            try:
                handler.record_node(name, latency_ms)
            except Exception as err:
                logger.debug("Callback record_node exception: %s", err)
