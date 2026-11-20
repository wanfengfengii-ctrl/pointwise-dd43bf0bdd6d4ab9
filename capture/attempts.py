from dataclasses import dataclass
import sqlite3

from bench.outcomes import HandoffOutcome
from storage import Conflict, require_transaction


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
    connection.execute('''
        CREATE TABLE IF NOT EXISTS capture_attempts (
            operation_id TEXT PRIMARY KEY NOT NULL,
            order_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            UNIQUE (order_id, revision),
            FOREIGN KEY (order_id, revision) REFERENCES receipt_candidates(order_id, revision)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS capture_progress (
            order_id TEXT PRIMARY KEY NOT NULL REFERENCES work_orders(order_id),
            state TEXT NOT NULL,
            terminal_status TEXT
        )
    ''')


_LOOKUP = '''
    SELECT attempt.*, progress.state, progress.terminal_status
    FROM capture_attempts AS attempt JOIN capture_progress AS progress USING (order_id)
'''


def _from_row(row: sqlite3.Row | None) -> TransferAttempt | None:
    if row is None:
        return None
    return TransferAttempt(row['order_id'], row['revision'], row['operation_id'], row['state'], row['terminal_status'])


def get_current_attempt(connection: sqlite3.Connection, order_id: str) -> TransferAttempt | None:
    row = connection.execute(_LOOKUP + '''
        WHERE attempt.order_id = ? ORDER BY attempt.revision DESC LIMIT 1
    ''', (order_id,)).fetchone()
    return _from_row(row)


def get_attempt(connection: sqlite3.Connection, operation_id: str) -> TransferAttempt | None:
    row = connection.execute(_LOOKUP + ' WHERE attempt.operation_id = ?', (operation_id,)).fetchone()
    return _from_row(row)


def register_attempt(connection: sqlite3.Connection, order_id: str, revision: int) -> TransferAttempt:
    require_transaction(connection)
    operation_id = f'capture/{len(order_id)}/{order_id}/{revision}'
    existing = get_attempt(connection, operation_id)
    if existing is not None:
        return existing
    connection.execute('INSERT INTO capture_attempts VALUES (?, ?, ?)', (operation_id, order_id, revision))
    connection.execute('''
        INSERT INTO capture_progress VALUES (?, 'prepared', NULL)
        ON CONFLICT(order_id) DO UPDATE SET state = excluded.state, terminal_status = NULL
    ''', (order_id,))
    return TransferAttempt(order_id, revision, operation_id, 'prepared', None)


def mark_pending(connection: sqlite3.Connection, operation_id: str) -> TransferAttempt:
    require_transaction(connection)
    attempt = get_attempt(connection, operation_id)
    if attempt is None:
        raise Conflict('no persisted operation for the missing reply')
    connection.execute('''
        UPDATE capture_progress SET state = 'pending' WHERE order_id = ? AND state = 'prepared'
    ''', (attempt.order_id,))
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
    connection.execute('''
        UPDATE capture_progress SET state = ?, terminal_status = ? WHERE order_id = ?
    ''', (state, outcome.status, attempt.order_id))
    return TransferAttempt(attempt.order_id, attempt.revision, attempt.operation_id, state, outcome.status)
