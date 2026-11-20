import sqlite3

from receipt.readback import read_receipt
from reconcile.manifest import ShiftManifest
from reconcile.missing import ManifestLine, list_missing_orders
from reconcile.summary import MeasurementSummary
from storage import Conflict, decode_integer, identifier


def find_signed_shift(connection: sqlite3.Connection, shift_id: str) -> str | None:
    row = connection.execute(
        'SELECT number FROM signed_shifts WHERE shift_id = ?', (identifier(shift_id),)
    ).fetchone()
    return row['number'] if row is not None else None


def _read_line(connection: sqlite3.Connection, row: sqlite3.Row) -> ManifestLine:
    token = row['receipt_token']
    item = None
    if token is not None:
        item = read_receipt(connection, token=token)
        if item is None or (item.order_id, item.recipe_id) != (row['order_id'], row['recipe_id']):
            raise Conflict('signed manifest has a mismatched receipt reference')
    return ManifestLine(row['order_id'], row['sample'], row['recipe_id'], row['position'], item)


def read_shift_receipt(connection: sqlite3.Connection, number: str) -> ShiftManifest | None:
    header = connection.execute(
        'SELECT * FROM signed_shifts WHERE number = ?', (identifier(number),)
    ).fetchone()
    if header is None:
        return None
    rows = connection.execute(
        'SELECT * FROM signed_shift_lines WHERE number = ? ORDER BY position', (number,)
    )
    lines = tuple(_read_line(connection, row) for row in rows)
    minimum = header['minimum']
    maximum = header['maximum']
    summary = MeasurementSummary(
        header['valid_count'], decode_integer(minimum) if minimum is not None else None,
        decode_integer(maximum) if maximum is not None else None,
    )
    return ShiftManifest(header['shift_id'], header['number'], lines, list_missing_orders(lines), summary)
