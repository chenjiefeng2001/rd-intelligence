"""Transport-layer tests (MCP / IDE).

Kept out of the core suite on purpose: these lock the *boundary* invariants
(transports must not import RenderDoc APIs, must not build a second domain
model, must return errors as JSON), and the assertions are about the
transport's own code. They are still part of the default test run.

This package marker exists so the directory is a real package for both
unittest and pytest discovery; without it `tests_transport/` had no
__init__.py while every sibling suite did, and pytest could collect its
modules by basename and collide with same-named core modules.
"""
