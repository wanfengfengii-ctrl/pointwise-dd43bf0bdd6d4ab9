import sqlite3

from bench.outcomes import HandoffOutcome
from capture.attempts import get_attempt
from planning.orders import get_order
from receipt.candidates import ReceiptCandidate, get_candidate
from receipt.conversion import convert_reading
from receipt.readback import ReceivedItem, read_receipt
from storage import Conflict, NotFound, atomic, encode_integer, identifier, positive_revision


def create_confirmations(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipt_confirmations (
            order_id TEXT PRIMARY KEY NOT NULL,
            revision INTEGER NOT NULL,
            operation_id TEXT NOT NULL UNIQUE REFERENCES capture_attempts(operation_id),
            FOREIGN KEY (order_id, revision) REFERENCES receipt_candidates(order_id, revision)
        )
    ''')


def _get_confirmation(connection: sqlite3.Connection, order_id: str) -> sqlite3.Row | None:
    return connection.execute(
        'SELECT revision, operation_id FROM receipt_confirmations WHERE order_id = ?', (order_id,)
    ).fetchone()


def confirm_candidate(connection: sqlite3.Connection, outcome: HandoffOutcome) -> ReceiptCandidate:
    identifier(outcome.operation_id)
    identifier(outcome.order_id)
    positive_revision(outcome.revision)
    if outcome.status != 'transferred':
        raise Conflict('only a successful handoff can qualify a candidate')
    with atomic(connection):
        attempt = get_attempt(connection, outcome.operation_id)
        if attempt is None or attempt.state != 'confirmed' or attempt.outcome() != outcome:
            raise Conflict('candidate qualification requires the exact verified operation')
        candidate = get_candidate(connection, outcome.order_id, outcome.revision)
        if candidate is None:
            raise Conflict('no original evidence for the confirmed revision')
        confirmation = _get_confirmation(connection, outcome.order_id)
        if confirmation is None:
            connection.execute(
                'INSERT INTO receipt_confirmations VALUES (?, ?, ?)',
                (outcome.order_id, outcome.revision, outcome.operation_id),
            )
        elif (confirmation['revision'], confirmation['operation_id']) != (outcome.revision, outcome.operation_id):
            raise Conflict('another handoff already qualified this order')
        return candidate


def finalize_receipt(connection: sqlite3.Connection, order_id: str) -> ReceivedItem:
    identifier(order_id)
    with atomic(connection):
        existing = read_receipt(connection, order_id=order_id)
        if existing is not None:
            return existing
        order = get_order(connection, order_id)
        if order is None:
            raise NotFound(f'unknown order {order_id!r}')
        proof = _get_confirmation(connection, order_id)
        if proof is None:
            raise Conflict('receipt has no confirmed handoff')
        # Sign the revision that was actually handed off. Older preserved
        # candidates stay in the ledger as original evidence but are never
        # published once a newer revision wins the handoff.
        candidate = get_candidate(connection, order_id, proof['revision'])
        if candidate is None:
            raise Conflict('confirmed candidate is unavailable')
        converted = convert_reading(connection, order, candidate.raw)
        token = f'R/{order_id}'
        origin = candidate.origin
        connection.execute('INSERT INTO received_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (
            order_id, candidate.revision, proof['operation_id'], order.recipe_id,
            encode_integer(candidate.raw), encode_integer(converted), origin.instrument, origin.record,
            origin.initial_record,
        ))
        connection.execute('INSERT INTO receipt_tokens VALUES (?, ?)', (token, order_id))
        return ReceivedItem(order_id, candidate.revision, proof['operation_id'], order.recipe_id,
                            candidate.raw, converted, origin, token)
