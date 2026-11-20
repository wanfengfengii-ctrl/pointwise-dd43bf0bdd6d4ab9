from dataclasses import dataclass
import sqlite3

from storage import NotFound, identifier, require_transaction


@dataclass(frozen=True)
class Shift:
    shift_id: str
    next_position: int


def create_shifts(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            shift_id TEXT PRIMARY KEY NOT NULL,
            next_position INTEGER NOT NULL DEFAULT 1 CHECK (next_position > 0)
        )
    ''')


def get_shift(connection: sqlite3.Connection, shift_id: str) -> Shift | None:
    row = connection.execute('SELECT * FROM shifts WHERE shift_id = ?', (shift_id,)).fetchone()
    return Shift(row['shift_id'], row['next_position']) if row is not None else None


def ensure_shift(connection: sqlite3.Connection, shift_id: str) -> Shift:
    require_transaction(connection)
    identifier(shift_id)
    connection.execute('INSERT INTO shifts (shift_id) VALUES (?) ON CONFLICT DO NOTHING', (shift_id,))
    return get_shift(connection, shift_id)


def allocate_order_position(connection: sqlite3.Connection, shift_id: str) -> int:
    require_transaction(connection)
    shift = get_shift(connection, shift_id)
    if shift is None:
        raise NotFound(f'unknown shift {shift_id!r}')
    connection.execute(
        'UPDATE shifts SET next_position = next_position + 1 WHERE shift_id = ?', (shift_id,)
    )
    return shift.next_position
