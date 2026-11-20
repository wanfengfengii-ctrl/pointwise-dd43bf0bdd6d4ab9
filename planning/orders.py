from dataclasses import dataclass
import sqlite3

from planning.recipes import get_recipe
from planning.shifts import allocate_order_position, ensure_shift
from storage import Conflict, NotFound, atomic, identifier


@dataclass(frozen=True)
class Order:
    shift_id: str
    order_id: str
    sample: str
    recipe_id: str
    position: int


def create_orders(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS work_orders (
            order_id TEXT PRIMARY KEY NOT NULL,
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            sample TEXT NOT NULL,
            recipe_id TEXT NOT NULL REFERENCES recipes(recipe_id),
            position INTEGER NOT NULL CHECK (position > 0),
            UNIQUE (shift_id, position)
        )
    ''')


def _from_row(row: sqlite3.Row) -> Order:
    return Order(row['shift_id'], row['order_id'], row['sample'], row['recipe_id'], row['position'])


def get_order(connection: sqlite3.Connection, order_id: str) -> Order | None:
    row = connection.execute('SELECT * FROM work_orders WHERE order_id = ?', (order_id,)).fetchone()
    return _from_row(row) if row is not None else None


def open_order(
    connection: sqlite3.Connection, shift_id: str, order_id: str, sample: str, recipe_id: str
) -> Order:
    for value in (shift_id, order_id, sample, recipe_id):
        identifier(value)
    with atomic(connection):
        existing = get_order(connection, order_id)
        if existing is not None:
            if (existing.shift_id, existing.sample, existing.recipe_id) != (shift_id, sample, recipe_id):
                raise Conflict(f'order {order_id!r} already has a different plan')
            return existing
        if get_recipe(connection, recipe_id) is None:
            raise NotFound(f'unknown recipe {recipe_id!r}')
        ensure_shift(connection, shift_id)
        position = allocate_order_position(connection, shift_id)
        connection.execute(
            'INSERT INTO work_orders (order_id, shift_id, sample, recipe_id, position) VALUES (?, ?, ?, ?, ?)',
            (order_id, shift_id, sample, recipe_id, position),
        )
        return Order(shift_id, order_id, sample, recipe_id, position)


def list_shift_orders(connection: sqlite3.Connection, shift_id: str) -> tuple[Order, ...]:
    rows = connection.execute(
        'SELECT * FROM work_orders WHERE shift_id = ? ORDER BY position', (shift_id,)
    )
    return tuple(_from_row(row) for row in rows)
