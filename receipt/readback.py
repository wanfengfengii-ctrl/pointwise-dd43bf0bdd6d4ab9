from dataclasses import dataclass
import sqlite3

from bench.origins import ReadingOrigin
from storage import decode_integer, identifier


@dataclass(frozen=True)
class ReceivedItem:
    order_id: str
    revision: int
    operation_id: str
    recipe_id: str
    raw: int
    converted: int
    origin: ReadingOrigin
    token: str


def create_receipts(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS received_items (
            order_id TEXT PRIMARY KEY NOT NULL REFERENCES receipt_confirmations(order_id),
            revision INTEGER NOT NULL CHECK (revision > 0),
            operation_id TEXT NOT NULL UNIQUE REFERENCES capture_attempts(operation_id),
            recipe_id TEXT NOT NULL REFERENCES recipes(recipe_id),
            raw TEXT NOT NULL,
            converted TEXT NOT NULL,
            instrument TEXT NOT NULL,
            record TEXT NOT NULL,
            initial_record TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipt_tokens (
            token TEXT PRIMARY KEY NOT NULL,
            order_id TEXT NOT NULL UNIQUE REFERENCES received_items(order_id)
        )
    ''')


_SELECT = '''
    SELECT item.*, token.token
    FROM received_items AS item JOIN receipt_tokens AS token ON token.order_id = item.order_id
'''


def _from_row(row: sqlite3.Row) -> ReceivedItem:
    origin = ReadingOrigin(
        row['order_id'], row['revision'], row['instrument'], row['record'], row['initial_record']
    )
    return ReceivedItem(
        row['order_id'], row['revision'], row['operation_id'], row['recipe_id'],
        decode_integer(row['raw']), decode_integer(row['converted']), origin, row['token'],
    )


def read_receipt(
    connection: sqlite3.Connection, *, order_id: str | None = None, token: str | None = None
) -> ReceivedItem | None:
    if (order_id is None) == (token is None):
        raise ValueError('provide exactly one receipt lookup key')
    if order_id is not None:
        row = connection.execute(_SELECT + ' WHERE item.order_id = ?', (identifier(order_id),)).fetchone()
    else:
        row = connection.execute(_SELECT + ' WHERE token.token = ?', (identifier(token),)).fetchone()
    return _from_row(row) if row is not None else None


def list_received_items(connection: sqlite3.Connection, shift_id: str) -> tuple[ReceivedItem, ...]:
    rows = connection.execute(_SELECT + '''
        JOIN work_orders AS planned ON planned.order_id = item.order_id
        WHERE planned.shift_id = ? ORDER BY planned.position
    ''', (identifier(shift_id),))
    return tuple(_from_row(row) for row in rows)
