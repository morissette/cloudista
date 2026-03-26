"""
pytest configuration — installs asyncpg and boto3 stubs before any app module
is imported, so route tests run without the real packages installed locally.
CI will have the real packages (installed from Pipfile).
"""
import os
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

# Provide required env vars before any settings module loads
os.environ.setdefault("BLOG_DB_PASSWORD", "test-password")
os.environ.setdefault("BLOG_DB_HOST", "localhost")
os.environ.setdefault("TURNSTILE_SECRET", "")
os.environ.setdefault("ADMIN_KEY", "test-admin-key")


def _make_asyncpg_stub():
    """Build a minimal asyncpg module stub sufficient for import-time use."""
    mod = ModuleType("asyncpg")

    # Exception hierarchy
    class PostgresError(Exception):
        pass

    class IntegrityConstraintViolationError(PostgresError):
        constraint_name: str | None = None

    class UniqueViolationError(IntegrityConstraintViolationError):
        pass

    class TooManyConnectionsError(PostgresError):
        pass

    mod.PostgresError = PostgresError
    mod.IntegrityConstraintViolationError = IntegrityConstraintViolationError
    mod.UniqueViolationError = UniqueViolationError
    mod.TooManyConnectionsError = TooManyConnectionsError

    # Pool / Connection stubs (runtime use is via mocks in individual tests)
    mod.Pool = MagicMock
    mod.Connection = MagicMock

    # create_pool — not used directly in tests (init_pool is patched)
    mod.create_pool = AsyncMock(return_value=MagicMock())

    return mod


def _make_boto3_stub():
    mod = ModuleType("boto3")
    client_mock = MagicMock()
    client_mock.send_email = MagicMock(return_value={})
    mod.client = MagicMock(return_value=client_mock)
    return mod


def _make_botocore_stub():
    mod = ModuleType("botocore")
    exceptions_mod = ModuleType("botocore.exceptions")

    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        pass

    exceptions_mod.BotoCoreError = BotoCoreError
    exceptions_mod.ClientError = ClientError
    mod.exceptions = exceptions_mod
    sys.modules["botocore.exceptions"] = exceptions_mod
    return mod


# Install stubs only if the real packages aren't present
if "asyncpg" not in sys.modules:
    try:
        import asyncpg  # noqa: F401
    except ModuleNotFoundError:
        sys.modules["asyncpg"] = _make_asyncpg_stub()

if "boto3" not in sys.modules:
    try:
        import boto3  # noqa: F401
    except ModuleNotFoundError:
        sys.modules["boto3"] = _make_boto3_stub()

if "botocore" not in sys.modules:
    try:
        import botocore  # noqa: F401
    except ModuleNotFoundError:
        stub = _make_botocore_stub()
        sys.modules["botocore"] = stub
