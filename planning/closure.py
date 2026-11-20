import sqlite3

from planning.orders import Order, list_shift_orders
from planning.shifts import get_shift
from storage import NotFound, identifier


def load_closure_plan(connection: sqlite3.Connection, shift_id: str) -> tuple[Order, ...]:
    identifier(shift_id)
    if get_shift(connection, shift_id) is None:
        raise NotFound(f'unknown shift {shift_id!r}')
    return list_shift_orders(connection, shift_id)
