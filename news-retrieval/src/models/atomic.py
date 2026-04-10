"""Atomic operation context for multi-step model operations.

Importing from here keeps the business logic layer decoupled from the
database implementation. If the underlying transaction mechanism
changes, only this module needs updating.
"""
from db import transaction as atomic

__all__ = ["atomic"]
