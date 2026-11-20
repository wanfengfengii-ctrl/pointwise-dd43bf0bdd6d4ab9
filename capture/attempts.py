from dataclasses import dataclass
import sqlite3

from bench.outcomes import HandoffOutcome
from storage import Conflict, require_transaction


# Lifecycle of a single capture operation (one order revision):
# prepared -> pending -> {confirmed, stale, blocked}
# Terminal states are immutable: a late reply for one operation must never
# overwrite the result recorded for another operation of the same order.
_TERMINAL_STATES = {'confirmed', 'stale', 'blocked'}


@dataclass(frozen=True)
class TransferAttempt:
    order_id: str
    revision: int
    operation_id: str
    state: str
    terminal_status: str | None

    def outcome(self) -> HandoffOutcome | None:
        if self.terminal_status is None:
            return None
        return HandoffOutcome(self.operation_id, self.order_id, self.revision, self.terminal_status)


def create_attempts(connection: sqlite3.Connection) -> None:
    # State and terminal status live on the operation itself so that several
    # revisions of one order can coexist and a late terminal reply for an old
    # revision cannot erase a newer revision's verified handoff.
    connection.execute('''
        CREATE TABLE IF NOT EXISTS capture_attempts (
            operation_id TEXT PRIMARY KEY NOT NULL,
            order_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            state TEXT NOT NULL,
            terminal_status TEXT,
            UNIQUE (order_id, revision),
            FOREIGN KEY (order_id, revision) REFERENCES receipt_candidates(order_id, revision)
        )
    ''')


_LOOKUP = 'SELECT * FROM capture_attempts'


def _from_row(row: sqlite3.Row | None) -> TransferAttempt | None:
    if row is None:
        return None
    return TransferAttempt(row['order_id'], row['revision'], row['operation_id'],
                          row['state'], row['terminal_status'])


def get_current_attempt(connection: sqlite3.Connection, order_id: str) -> TransferAttempt | None:
    row = connection.execute(
        _LOOKUP + ' WHERE order_id = ? ORDER BY revision DESC LIMIT 1', (order_id,)
    ).fetchone()
    return _from_row(row)


def get_attempt(connection: sqlite3.Connection, operation_id: str) -> TransferAttempt | None:
    row = connection.execute(_LOOKUP + ' WHERE operation_id = ?', (operation_id,)).fetchone()
    return _from_row(row)


def register_attempt(connection: sqlite3.Connection, order_id: str, revision: int) -> TransferAttempt:
    require_transaction(connection)
    operation_id = f'capture/{len(order_id)}/{order_id}/{revision}'
    existing = get_attempt(connection, operation_id)
    if existing is not None:
        return existing
    connection.execute(
        "INSERT INTO capture_attempts VALUES (?, ?, ?, 'prepared', NULL)",
        (operation_id, order_id, revision),
    )
    return TransferAttempt(order_id, revision, operation_id, 'prepared', None)


def mark_pending(connection: sqlite3.Connection, operation_id: str) -> TransferAttempt:
    require_transaction(connection)
    attempt = get_attempt(connection, operation_id)
    if attempt is None:
        raise Conflict('no persisted operation for the missing reply')
    if attempt.state in _TERMINAL_STATES:
        # A lost reply can only affect an operation that has not reached a
        # terminal decision; keep an already recorded outcome authoritative.
        return attempt
    connection.execute('''
        UPDATE capture_attempts SET state = 'pending'
        WHERE operation_id = ? AND state = 'prepared'
    ''', (operation_id,))
    return get_attempt(connection, operation_id)


def save_outcome(connection: sqlite3.Connection, outcome: HandoffOutcome) -> TransferAttempt:
    require_transaction(connection)
    attempt = get_attempt(connection, outcome.operation_id)
    if attempt is None or (attempt.order_id, attempt.revision) != (outcome.order_id, outcome.revision):
        raise Conflict('handoff result does not match a registered operation')
    states = {'transferred': 'confirmed', 'stale': 'stale', 'empty': 'blocked', 'already_transferred': 'blocked'}
    state = states.get(outcome.status)
    if state is None:
        raise Conflict('handoff result has no recognized terminal status')
    if attempt.state in _TERMINAL_STATES:
        if attempt.state != state or attempt.terminal_status != outcome.status:
            raise Conflict('operation already reached a different terminal status')
        return attempt
    connection.execute('''
        UPDATE capture_attempts SET state = ?, terminal_status = ? WHERE operation_id = ?
    ''', (state, outcome.status, outcome.operation_id))
    return TransferAttempt(attempt.order_id, attempt.revision, attempt.operation_id, state, outcome.status)
