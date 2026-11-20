import sqlite3

from bench.handoff import ReplyLost, SQLiteBench
from bench.outcomes import HandoffOutcome
from capture.attempts import TransferAttempt, get_attempt, mark_pending
from capture.transfer import apply_outcome, send_transfer
from storage import Conflict, atomic


def resume_transfer(
    local: sqlite3.Connection, bench: SQLiteBench | None, attempt: TransferAttempt
) -> HandoffOutcome | None:
    stored = get_attempt(local, attempt.operation_id)
    if stored is None or (stored.order_id, stored.revision) != (attempt.order_id, attempt.revision):
        raise Conflict('no matching persisted operation to resume')
    outcome = stored.outcome()
    if outcome is not None or bench is None:
        return outcome
    if local.in_transaction:
        raise RuntimeError('handoff lookup requires an idle local connection')
    try:
        observed = bench.query(stored.operation_id)
    except ReplyLost:
        with atomic(local):
            return mark_pending(local, stored.operation_id).outcome()
    if observed is not None:
        return apply_outcome(local, stored, observed)
    return send_transfer(local, bench, stored)
