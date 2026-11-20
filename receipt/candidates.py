from dataclasses import dataclass
import sqlite3

from bench.origins import ReadingOrigin
from storage import Conflict, decode_integer, encode_integer, identifier, positive_revision, require_transaction


@dataclass(frozen=True)
class ReceiptCandidate:
    order_id: str
    revision: int
    raw: int
    origin: ReadingOrigin


def create_candidates(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipt_candidates (
            order_id TEXT NOT NULL REFERENCES work_orders(order_id),
            revision INTEGER NOT NULL CHECK (revision > 0),
            raw TEXT NOT NULL,
            instrument TEXT NOT NULL,
            record TEXT NOT NULL,
            initial_record TEXT NOT NULL,
            PRIMARY KEY (order_id, revision)
        )
    ''')


def get_candidate(connection: sqlite3.Connection, order_id: str, revision: int) -> ReceiptCandidate | None:
    row = connection.execute(
        'SELECT * FROM receipt_candidates WHERE order_id = ? AND revision = ?', (order_id, revision)
    ).fetchone()
    if row is None:
        return None
    origin = ReadingOrigin(order_id, revision, row['instrument'], row['record'], row['initial_record'])
    return ReceiptCandidate(order_id, revision, decode_integer(row['raw']), origin)


def save_candidate(connection: sqlite3.Connection, candidate: ReceiptCandidate) -> ReceiptCandidate:
    require_transaction(connection)
    origin = candidate.origin
    if (origin.order_id, origin.revision) != (candidate.order_id, candidate.revision):
        raise Conflict('candidate has a different origin identity')
    identifier(candidate.order_id)
    positive_revision(candidate.revision)
    positive_revision(origin.revision)
    raw = encode_integer(candidate.raw)
    for value in (origin.instrument, origin.record, origin.initial_record):
        identifier(value)
    existing = get_candidate(connection, candidate.order_id, candidate.revision)
    if existing is not None:
        if existing != candidate:
            raise Conflict('candidate already holds different original evidence')
        return existing
    connection.execute('INSERT INTO receipt_candidates VALUES (?, ?, ?, ?, ?, ?)', (
        candidate.order_id, candidate.revision, raw, origin.instrument, origin.record, origin.initial_record,
    ))
    return candidate
