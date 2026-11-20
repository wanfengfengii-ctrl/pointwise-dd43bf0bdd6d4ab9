from contextlib import closing
import sqlite3

from bench.corrections import correct
from bench.handoff import query_transfer, transfer
from bench.outcomes import get_successful_handoff
from bench.staging import get_staged_reading, stage
from capture.session import collect
from receipt.readback import read_receipt
from reconcile.publish import shift_receipt
from storage import connect_db
from tests.support import ControlledBench, LedgerTest


class HandoffIncidentTests(LedgerTest):
    def test_late_rejection_cannot_erase_verified_handoff(self):
        self.plan()
        stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')
        self.local.executescript('''
            CREATE TABLE incident_parent (id INTEGER PRIMARY KEY);
            CREATE TABLE incident_child (
                id INTEGER REFERENCES incident_parent(id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER incident_reject_confirmation AFTER INSERT ON receipt_confirmations
            BEGIN INSERT INTO incident_child VALUES (1); END;
        ''')

        def second_executor_while_old_reply_is_held(operation_id):
            correct(self.device, 'T', 1, 11, 'T-2')
            stale = transfer(self.device, 'T', 1, operation_id)
            self.assertEqual(stale.status, 'stale')
            with closing(connect_db(self.local_path)) as local, closing(connect_db(self.device_path)) as device:
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                    collect(local, ControlledBench(device), 'T')
                self.assertIsNone(read_receipt(local, order_id='T'))
                self.assertIsNone(read_receipt(local, token='R/T'))
            self.assertEqual(query_transfer(self.device, operation_id), stale)

        self.bench.before['T', 1] = second_executor_while_old_reply_is_held
        try:
            collect(self.local, self.bench, 'T')
        except sqlite3.IntegrityError as error:
            self.assertIn('FOREIGN KEY constraint failed', str(error))
        finally:
            self.local.execute('DROP TRIGGER incident_reject_confirmation')
        actual = get_successful_handoff(self.device, 'T')
        self.assertEqual(actual.revision, 2)
        self.assertIsNone(get_staged_reading(self.device, 'T'))
        self.assertIsNone(read_receipt(self.local, order_id='T'))
        self.assertIsNone(read_receipt(self.local, token='R/T'))
        self.reopen(offline=True)
        item = collect(self.local, None, 'T').item
        self.assertIsNotNone(item, 'LOST_CONFIRMED_TRANSFER')
        self.assertEqual((item.revision, item.raw, item.converted, item.origin.record), (2, 11, 25, 'T-2'))
        self.assertEqual(item.operation_id, actual.operation_id)
        self.assertEqual(read_receipt(self.local, token=item.token), item)
        self.assertEqual(shift_receipt(self.local, 'D1').lines[0].item, item)
