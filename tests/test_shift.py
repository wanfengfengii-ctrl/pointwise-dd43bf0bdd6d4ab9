from contextlib import closing
import sqlite3

from bench.staging import stage
from capture.session import collect
from planning.initialize import DEFAULT_RECIPE_ID
from receipt.readback import read_receipt
from reconcile.publish import shift_receipt
from reconcile.readback import find_signed_shift, read_shift_receipt
from reconcile.summary import MeasurementSummary
from storage import NotFound, connect_db
from tests.support import LedgerTest, force_commit_failure


class ShiftTests(LedgerTest):
    def test_close_with_missing_and_reopen(self):
        self.plan('Z', 'A02')
        self.plan('A', 'A01')
        reading = stage(self.local, self.device, 'Z', 11, 'bench-A', 'Z-1')
        item = collect(self.local, self.bench, 'Z').item
        manifest = shift_receipt(self.local, 'D1')
        self.assertEqual([(line.order_id, line.sample, line.position) for line in manifest.lines],
                         [('Z', 'A02', 1), ('A', 'A01', 2)])
        self.assertEqual(manifest.lines[0].item, item)
        self.assertTrue(manifest.lines[1].missing)
        self.assertEqual(manifest.missing_orders, ('A',))
        self.assertEqual(manifest.summary, MeasurementSummary(1, 25, 25))
        self.reopen(offline=True)
        self.assertEqual(find_signed_shift(self.local, 'D1'), manifest.number)
        self.assertEqual(read_shift_receipt(self.local, manifest.number), manifest)
        self.assertEqual(shift_receipt(self.local, 'D1'), manifest)
        self.assertEqual(read_receipt(self.local, token=item.token).origin, reading.origin)

    def test_zero_vs_missing(self):
        self.plan('U', 'A02', DEFAULT_RECIPE_ID)
        self.plan('T', 'A01')
        self.plan('W', 'A03')
        stage(self.local, self.device, 'T', 11, 'bench-A', 'T-1')
        stage(self.local, self.device, 'U', 0, 'bench-A', 'U-1')
        collect(self.local, self.bench, 'T')
        collect(self.local, self.bench, 'U')
        manifest = shift_receipt(self.local, 'D1')
        self.assertEqual([line.order_id for line in manifest.lines], ['U', 'T', 'W'])
        self.assertEqual([line.missing for line in manifest.lines], [False, False, True])
        self.assertEqual(manifest.lines[0].item.converted, 0)
        self.assertEqual(manifest.summary, MeasurementSummary(2, 0, 25))
        self.assertEqual(manifest.missing_orders, ('W',))

    def test_all_missing(self):
        self.plan()
        self.plan('U', 'A02')
        stage(self.local, self.device, 'T', 11, 'bench-A', 'T-1')
        manifest = shift_receipt(self.local, 'D1')
        self.assertEqual(manifest.missing_orders, ('T', 'U'))
        self.assertEqual(manifest.summary, MeasurementSummary(0, None, None))
        self.assertTrue(all(line.item is None for line in manifest.lines))
        self.reopen(offline=True)
        self.assertEqual(read_shift_receipt(self.local, manifest.number), manifest)

    def test_close_rollback(self):
        self.plan()
        with self.assertRaises(NotFound):
            shift_receipt(self.local, 'UNKNOWN')
        self.assertIsNone(read_shift_receipt(self.local, 'S/UNKNOWN'))
        with force_commit_failure(self.local, 'signed_shift_lines'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                shift_receipt(self.local, 'D1')
            with closing(connect_db(self.local_path)) as observer:
                self.assertIsNone(find_signed_shift(observer, 'D1'))
                self.assertIsNone(read_shift_receipt(observer, 'S/D1'))
                self.assertEqual(observer.execute('SELECT count(*) FROM signed_shift_lines').fetchone()[0], 0)
        manifest = shift_receipt(self.local, 'D1')
        self.assertEqual(manifest.missing_orders, ('T',))
        self.assertEqual(read_shift_receipt(self.local, manifest.number), manifest)

    def test_snapshot_after_late_receipt(self):
        self.plan('A', 'A01')
        self.plan('B', 'A02')
        stage(self.local, self.device, 'A', 7, 'bench-A', 'A-1')
        late_reading = stage(self.local, self.device, 'B', 11, 'bench-A', 'B-1')
        first = collect(self.local, self.bench, 'A').item
        with force_commit_failure(self.local, 'receipt_tokens'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                collect(self.local, self.bench, 'B')
        frozen = shift_receipt(self.local, 'D1')
        self.assertEqual(frozen.summary, MeasurementSummary(1, 17, 17))
        self.assertEqual(frozen.missing_orders, ('B',))
        self.reopen(offline=True)
        late = collect(self.local, None, 'B').item
        self.assertEqual((late.raw, late.converted, late.origin), (11, 25, late_reading.origin))
        self.reopen(offline=True)
        old = read_shift_receipt(self.local, frozen.number)
        self.assertEqual(old, frozen)
        self.assertEqual(old.lines[0].item, first)
        self.assertIsNone(old.lines[1].item)
        self.assertEqual(shift_receipt(self.local, 'D1'), frozen)
        self.assertEqual(read_receipt(self.local, token=late.token), late)
