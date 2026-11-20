from dataclasses import dataclass
import sqlite3

from storage import require_transaction


@dataclass(frozen=True)
class HandoffOutcome:
    operation_id: str
    order_id: str
    revision: int
    status: str


def create_outcomes(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS handoff_outcomes (
            operation_id TEXT PRIMARY KEY NOT NULL,
            order_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision > 0),
            status TEXT NOT NULL CHECK (status IN ('transferred', 'stale', 'empty', 'already_transferred'))
        )
    ''')
    connection.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS handoff_one_success
        ON handoff_outcomes (order_id) WHERE status = 'transferred'
    ''')


def _from_row(row: sqlite3.Row | None) -> HandoffOutcome | None:
    if row is None:
        return None
    return HandoffOutcome(row['operation_id'], row['order_id'], row['revision'], row['status'])


def get_outcome(connection: sqlite3.Connection, operation_id: str) -> HandoffOutcome | None:
    return _from_row(connection.execute(
        'SELECT * FROM handoff_outcomes WHERE operation_id = ?', (operation_id,)
    ).fetchone())


def store_outcome(connection: sqlite3.Connection, outcome: HandoffOutcome) -> None:
    require_transaction(connection)
    connection.execute(
        'INSERT INTO handoff_outcomes VALUES (?, ?, ?, ?)',
        (outcome.operation_id, outcome.order_id, outcome.revision, outcome.status),
    )


def get_successful_handoff(connection: sqlite3.Connection, order_id: str) -> HandoffOutcome | None:
    return _from_row(connection.execute(
        "SELECT * FROM handoff_outcomes WHERE order_id = ? AND status = 'transferred'", (order_id,)
    ).fetchone())
