"""Shared store for MA and Alexa routes.

This module provides a centralized store so that both the Music Assistant
API (mounted at /ma) and the Alexa API (mounted at /alexa) can access
the same stream metadata.
"""

_store = None
_version = 0
