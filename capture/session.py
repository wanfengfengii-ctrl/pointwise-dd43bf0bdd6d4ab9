from dataclasses import dataclass
import sqlite3

from bench.handoff import SQLiteBench
from capture.attempts import get_current_attempt
from capture.resume import resume_transfer
from capture.transfer import prepare_transfer
from planning.orders import get_order
from receipt.finalize import confirm_candidate, finalize_receipt
from receipt.readback import ReceivedItem, read_receipt
from storage import Conflict, NotFound, identifier


@dataclass(frozen=True)
class CollectResult:
    status: str
    item: ReceivedItem | None = None
    operation_id: str | None = None


def collect(local: sqlite3.Connection, bench: SQLiteBench | None, order_id: str) -> CollectResult:
    if local.in_transaction:
        raise RuntimeError('collect requires an idle connection')
    order = get_order(local, identifier(order_id))
    if order is None:
        raise NotFound(f'unknown order {order_id!r}')
    while True:
        signed = read_receipt(local, order_id=order_id)
        if signed is not None:
            return CollectResult('received', signed, signed.operation_id)
        attempt = get_current_attempt(local, order_id)
        reading = bench.read(order_id) if bench is not None else None
        if attempt is not None and attempt.terminal_status is None:
            # An operation for this order is still in flight. Drive it to its
            # terminal result before touching any newer staged revision: the
            # original request continues under its own operation id, and a
            # missing reply keeps it pending for another executor to resolve.
            outcome = resume_transfer(local, bench, attempt)
            if outcome is None:
                return CollectResult('pending', operation_id=attempt.operation_id)
            if outcome.status == 'stale':
                continue
            if outcome.status != 'transferred':
                raise Conflict(f'operation {outcome.operation_id!r} ended with {outcome.status}')
            confirm_candidate(local, outcome)
            signed = finalize_receipt(local, order_id)
            return CollectResult('received', signed, signed.operation_id)
        if reading is not None and (attempt is None or reading.revision > attempt.revision):
            # Only start a new operation once every older operation has a
            # durable terminal outcome, so stale replies belong to their own
            # operation and can never overwrite the newer one.
            attempt = prepare_transfer(local, order, reading)
            continue
        if attempt is not None and attempt.terminal_status is not None:
            outcome = attempt.outcome()
            if outcome.status == 'transferred':
                # A verified handoff whose receipt publication previously
                # failed can still be finalized, including with the bench
                # offline: all required evidence is already local.
                confirm_candidate(local, outcome)
                signed = finalize_receipt(local, order_id)
                return CollectResult('received', signed, signed.operation_id)
            # A terminal non-success (stale/blocked) with nothing newer to
            # pursue leaves the order waiting for a fresh staged reading.
            return CollectResult('awaiting_reading')
        return CollectResult('awaiting_reading')
