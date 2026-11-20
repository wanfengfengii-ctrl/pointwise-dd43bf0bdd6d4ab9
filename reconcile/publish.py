import sqlite3

from reconcile.manifest import ShiftManifest, build_manifest
from reconcile.readback import find_signed_shift, read_shift_receipt
from storage import atomic, encode_integer, identifier, require_transaction


def create_manifests(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS signed_shifts (
            number TEXT PRIMARY KEY NOT NULL,
            shift_id TEXT NOT NULL UNIQUE REFERENCES shifts(shift_id),
            valid_count INTEGER NOT NULL CHECK (valid_count >= 0),
            minimum TEXT,
            maximum TEXT,
            CHECK ((valid_count = 0 AND minimum IS NULL AND maximum IS NULL)
                OR (valid_count > 0 AND minimum IS NOT NULL AND maximum IS NOT NULL))
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS signed_shift_lines (
            number TEXT NOT NULL REFERENCES signed_shifts(number),
            position INTEGER NOT NULL,
            order_id TEXT NOT NULL REFERENCES work_orders(order_id),
            sample TEXT NOT NULL,
            recipe_id TEXT NOT NULL REFERENCES recipes(recipe_id),
            receipt_token TEXT REFERENCES receipt_tokens(token),
            PRIMARY KEY (number, position),
            UNIQUE (number, order_id)
        )
    ''')


def publish_manifest(connection: sqlite3.Connection, manifest: ShiftManifest) -> None:
    require_transaction(connection)
    summary = manifest.summary
    connection.execute('INSERT INTO signed_shifts VALUES (?, ?, ?, ?, ?)', (
        manifest.number, manifest.shift_id, summary.count,
        encode_integer(summary.minimum) if summary.minimum is not None else None,
        encode_integer(summary.maximum) if summary.maximum is not None else None,
    ))
    connection.executemany('INSERT INTO signed_shift_lines VALUES (?, ?, ?, ?, ?, ?)', (
        (manifest.number, line.position, line.order_id, line.sample, line.recipe_id,
         line.item.token if line.item is not None else None)
        for line in manifest.lines
    ))


def shift_receipt(connection: sqlite3.Connection, shift_id: str) -> ShiftManifest:
    identifier(shift_id)
    with atomic(connection):
        signed_number = find_signed_shift(connection, shift_id)
        if signed_number is not None:
            return read_shift_receipt(connection, signed_number)
        manifest = build_manifest(connection, shift_id)
        publish_manifest(connection, manifest)
        return manifest
