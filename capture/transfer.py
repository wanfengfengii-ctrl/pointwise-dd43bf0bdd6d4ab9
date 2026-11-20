import sqlite3

from bench.handoff import ReplyLost, SQLiteBench
from bench.outcomes import HandoffOutcome
from bench.staging import StagedReading
from capture.attempts import TransferAttempt, mark_pending, register_attempt, save_outcome
from capture.provenance import verify_provenance
from planning.orders import Order
from receipt.candidates import ReceiptCandidate, save_candidate
from storage import Conflict, atomic


def prepare_transfer(local: sqlite3.Connection, order: Order, reading: StagedReading) -> TransferAttempt:
    verify_provenance(order, reading)
    with atomic(local):
        save_candidate(local, ReceiptCandidate(reading.order_id, reading.revision, reading.raw, reading.origin))
        return register_attempt(local, reading.order_id, reading.revision)


def apply_outcome(
    local: sqlite3.Connection, attempt: TransferAttempt, outcome: HandoffOutcome
) -> HandoffOutcome:
    if (outcome.operation_id, outcome.order_id, outcome.revision) != (
        attempt.operation_id, attempt.order_id, attempt.revision
    ):
        raise Conflict('result belongs to a different handoff operation')
    with atomic(local):
        save_outcome(local, outcome)
    return outcome


def send_transfer(
    local: sqlite3.Connection, bench: SQLiteBench, attempt: TransferAttempt
) -> HandoffOutcome | None:
    if local.in_transaction:
        raise RuntimeError('handoff requires a committed candidate and an idle local connection')
    try:
        outcome = bench.transfer(attempt.order_id, attempt.revision, attempt.operation_id)
    except ReplyLost:
        with atomic(local):
            return mark_pending(local, attempt.operation_id).outcome()
    return apply_outcome(local, attempt, outcome)
