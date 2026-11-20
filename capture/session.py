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
        if reading is not None and (attempt is None or reading.revision > attempt.revision):
            attempt = prepare_transfer(local, order, reading)
        elif attempt is None or attempt.state == 'stale':
            if get_current_attempt(local, order_id) != attempt:
                continue
            return CollectResult('awaiting_reading')
        outcome = resume_transfer(local, bench, attempt)
        if outcome is None:
            signed = read_receipt(local, order_id=order_id)
            if signed is not None:
                return CollectResult('received', signed, signed.operation_id)
            return CollectResult('pending', operation_id=attempt.operation_id)
        if outcome.status == 'stale':
            continue
        if outcome.status != 'transferred':
            raise Conflict(f'operation {outcome.operation_id!r} ended with {outcome.status}')
        confirm_candidate(local, outcome)
        signed = finalize_receipt(local, order_id)
        return CollectResult('received', signed, signed.operation_id)
