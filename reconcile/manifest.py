from dataclasses import dataclass
import sqlite3

from planning.closure import load_closure_plan
from receipt.readback import list_received_items
from reconcile.missing import ManifestLine, classify_manifest_line, list_missing_orders
from reconcile.summary import MeasurementSummary, summarize_measurements
from storage import require_transaction


@dataclass(frozen=True)
class ShiftManifest:
    shift_id: str
    number: str
    lines: tuple[ManifestLine, ...]
    missing_orders: tuple[str, ...]
    summary: MeasurementSummary


def build_manifest(connection: sqlite3.Connection, shift_id: str) -> ShiftManifest:
    require_transaction(connection)
    orders = load_closure_plan(connection, shift_id)
    receipts = {item.order_id: item for item in list_received_items(connection, shift_id)}
    lines = tuple(classify_manifest_line(order, receipts.get(order.order_id)) for order in orders)
    return ShiftManifest(
        shift_id, f'S/{shift_id}', lines, list_missing_orders(lines), summarize_measurements(lines)
    )
