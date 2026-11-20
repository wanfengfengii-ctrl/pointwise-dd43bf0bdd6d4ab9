import sqlite3

from bench.outcomes import HandoffOutcome, create_outcomes, get_outcome, get_successful_handoff, store_outcome
from bench.staging import StagedReading, clear_staged_reading, create_staging, get_staged_reading
from storage import Conflict, atomic, identifier, positive_revision


class ReplyLost(TimeoutError):
    """The caller has no reply and must check the original operation."""


def initialize_bench(connection: sqlite3.Connection) -> None:
    with atomic(connection):
        create_staging(connection)
        create_outcomes(connection)


def transfer(
    connection: sqlite3.Connection, order_id: str, revision: int, operation_id: str
) -> HandoffOutcome:
    identifier(order_id)
    identifier(operation_id)
    positive_revision(revision)
    with atomic(connection):
        previous = get_outcome(connection, operation_id)
        if previous is not None:
            if (previous.order_id, previous.revision) != (order_id, revision):
                raise Conflict('operation identity was used with different parameters')
            return previous
        current = get_staged_reading(connection, order_id)
        if get_successful_handoff(connection, order_id) is not None:
            status = 'already_transferred'
        elif current is None:
            status = 'empty'
        elif current.revision != revision:
            status = 'stale'
        else:
            clear_staged_reading(connection, order_id, revision)
            status = 'transferred'
        outcome = HandoffOutcome(operation_id, order_id, revision, status)
        store_outcome(connection, outcome)
        return outcome


def query_transfer(connection: sqlite3.Connection, operation_id: str) -> HandoffOutcome | None:
    return get_outcome(connection, identifier(operation_id))


class SQLiteBench:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def read(self, order_id: str) -> StagedReading | None:
        return get_staged_reading(self.connection, order_id)

    def transfer(self, order_id: str, revision: int, operation_id: str) -> HandoffOutcome:
        return transfer(self.connection, order_id, revision, operation_id)

    def query(self, operation_id: str) -> HandoffOutcome | None:
        return query_transfer(self.connection, operation_id)
