import sqlite3

from bench.origins import corrected_origin
from bench.outcomes import get_successful_handoff
from bench.staging import StagedReading, get_staged_reading, replace_staged_reading
from storage import Conflict, atomic, encode_integer, identifier, positive_revision


def correct(
    connection: sqlite3.Connection, order_id: str, expected_revision: int, raw: int, record: str
) -> StagedReading:
    identifier(order_id)
    positive_revision(expected_revision)
    encode_integer(raw)
    with atomic(connection):
        if get_successful_handoff(connection, order_id) is not None:
            raise Conflict(f'order {order_id!r} was already handed off')
        current = get_staged_reading(connection, order_id)
        if current is None or current.revision != expected_revision:
            raise Conflict('expected revision is no longer staged')
        origin = corrected_origin(current.origin, record)
        updated = StagedReading(order_id, origin.revision, raw, origin)
        replace_staged_reading(connection, expected_revision, updated)
        return updated
