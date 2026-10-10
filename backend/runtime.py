"""Portable asyncio entry point, including psycopg-compatible Windows sockets."""

import asyncio


def loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
