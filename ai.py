"""
ai.py - DEPRECATED: Backward Compatibility Wrapper

NOTE: This file is kept for backward compatibility only.
The ai/ package now contains all the functionality.

Python's import system will prioritize the ai/ package over this file,
so this file is effectively unused. It can be safely deleted.

All imports should use the ai package:
    from ai import filter_records_ai, chat_completion, clear_all_caches, close_http_client

This file will be removed in a future version.
"""

# Re-export everything from the package for any code that might
# try to import directly from this file
from ai import *  # noqa: F401, F403
