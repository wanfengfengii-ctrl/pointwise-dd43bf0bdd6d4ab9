from contextlib import contextmanager
import sqlite3


class Conflict(ValueError):
    """The request disagrees with an immutable identity or current state."""


class NotFound(LookupError):
    """The request names an unknown planned object."""


def identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('identifiers must be nonempty strings')
    return value


def positive_revision(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError('revision must be a positive integer')
    return value


def encode_integer(value: int) -> str:
    if type(value) is not int:
        raise ValueError('measurements and coefficients must be integers')
    return format(value, 'x')


def decode_integer(value: str) -> int:
    return int(value, 16)


def connect_db(path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def atomic(connection: sqlite3.Connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def require_transaction(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise RuntimeError('this write requires a caller-owned transaction')


def initialize_local(connection: sqlite3.Connection) -> None:
    from capture.attempts import create_attempts
    from planning.initialize import initialize_planning
    from receipt.candidates import create_candidates
    from receipt.finalize import create_confirmations
    from receipt.readback import create_receipts
    from reconcile.publish import create_manifests

    initialize_planning(connection)
    with atomic(connection):
        create_candidates(connection)
        create_attempts(connection)
        create_confirmations(connection)
        create_receipts(connection)
        create_manifests(connection)
