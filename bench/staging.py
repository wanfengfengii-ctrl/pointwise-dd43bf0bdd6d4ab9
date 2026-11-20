from dataclasses import dataclass
import sqlite3

from bench.origins import ReadingOrigin, initial_origin
from bench.outcomes import get_successful_handoff
from planning.orders import get_order
from storage import Conflict, NotFound, atomic, decode_integer, encode_integer, identifier, require_transaction


@dataclass(frozen=True)
class StagedReading:
    order_id: str
    revision: int
    raw: int
    origin: ReadingOrigin


def create_staging(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS staged_readings (
            order_id TEXT PRIMARY KEY NOT NULL,
            revision INTEGER NOT NULL CHECK (revision > 0),
            raw TEXT NOT NULL,
            instrument TEXT NOT NULL,
            record TEXT NOT NULL,
            initial_record TEXT NOT NULL
        )
    ''')


def get_staged_reading(connection: sqlite3.Connection, order_id: str) -> StagedReading | None:
    row = connection.execute('SELECT * FROM staged_readings WHERE order_id = ?', (order_id,)).fetchone()
    if row is None:
        return None
    origin = ReadingOrigin(
        row['order_id'], row['revision'], row['instrument'], row['record'], row['initial_record']
    )
    return StagedReading(row['order_id'], row['revision'], decode_integer(row['raw']), origin)


def stage(
    local: sqlite3.Connection, device: sqlite3.Connection, order_id: str, raw: int,
    instrument: str, record: str,
) -> StagedReading:
    identifier(order_id)
    if get_order(local, order_id) is None:
        raise NotFound(f'unknown order {order_id!r}')
    encoded_raw = encode_integer(raw)
    origin = initial_origin(order_id, instrument, record)
    with atomic(device):
        if get_successful_handoff(device, order_id) is not None:
            raise Conflict(f'order {order_id!r} was already handed off')
        if get_staged_reading(device, order_id) is not None:
            raise Conflict(f'order {order_id!r} already has a staged reading')
        device.execute(
            'INSERT INTO staged_readings VALUES (?, ?, ?, ?, ?, ?)',
            (order_id, 1, encoded_raw, origin.instrument, origin.record, origin.initial_record),
        )
    return StagedReading(order_id, 1, raw, origin)


def replace_staged_reading(
    connection: sqlite3.Connection, expected_revision: int, reading: StagedReading
) -> None:
    require_transaction(connection)
    cursor = connection.execute('''
        UPDATE staged_readings SET revision = ?, raw = ?, record = ?
        WHERE order_id = ? AND revision = ?
    ''', (reading.revision, encode_integer(reading.raw), reading.origin.record, reading.order_id, expected_revision))
    if cursor.rowcount != 1:
        raise Conflict('staged revision changed')


def clear_staged_reading(connection: sqlite3.Connection, order_id: str, revision: int) -> None:
    require_transaction(connection)
    cursor = connection.execute(
        'DELETE FROM staged_readings WHERE order_id = ? AND revision = ?', (order_id, revision)
    )
    if cursor.rowcount != 1:
        raise Conflict('staged revision changed before handoff')
