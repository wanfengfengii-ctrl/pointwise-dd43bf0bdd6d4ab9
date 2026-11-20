from contextlib import closing
from dataclasses import replace
import sqlite3

from bench.handoff import query_transfer
from bench.staging import get_staged_reading, stage
from capture.attempts import get_current_attempt
from capture.session import collect
from planning.recipes import register_recipe
from receipt.candidates import ReceiptCandidate, get_candidate, save_candidate
from receipt.finalize import confirm_candidate, finalize_receipt
from receipt.readback import read_receipt
from storage import Conflict, atomic, connect_db
from tests.support import LedgerTest, force_commit_failure


class ReceiptTests(LedgerTest):
    def test_publish_failure_and_retry(self):
        self.plan()
        reading = stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')
        with force_commit_failure(self.local, 'receipt_tokens'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                collect(self.local, self.bench, 'T')
            attempt = get_current_attempt(self.local, 'T')
            self.assertEqual(attempt.state, 'confirmed')
            self.assertEqual(query_transfer(self.device, attempt.operation_id).status, 'transferred')
            self.assertIsNone(get_staged_reading(self.device, 'T'))
            self.assertEqual(get_candidate(self.local, 'T', 1).origin, reading.origin)
            self.assertIsNone(read_receipt(self.local, order_id='T'))
            self.assertIsNone(read_receipt(self.local, token='R/T'))
        self.reopen(offline=True)
        result = collect(self.local, None, 'T')
        self.assertEqual((result.status, result.operation_id), ('received', attempt.operation_id))
        self.assertEqual((result.item.raw, result.item.converted, result.item.origin), (7, 17, reading.origin))
        self.assertEqual(read_receipt(self.local, token=result.item.token), result.item)
        self.assertEqual(collect(self.local, None, 'T'), result)

    def test_atomic_visibility(self):
        self.plan()
        self.plan('U', 'A02')
        stage(self.local, self.device, 'U', 0, 'bench-A', 'U-1')
        historical = collect(self.local, self.bench, 'U').item
        stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')
        with force_commit_failure(self.local, 'receipt_tokens'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                collect(self.local, self.bench, 'T')
            with closing(connect_db(self.local_path)) as observer:
                self.assertEqual(observer.execute('SELECT order_id FROM received_items').fetchone()[0], 'U')
                self.assertEqual(observer.execute('SELECT count(*) FROM received_items').fetchone()[0], 1)
                self.assertEqual(observer.execute('SELECT count(*) FROM receipt_tokens').fetchone()[0], 1)
                self.assertEqual(observer.execute('SELECT count(*) FROM receipt_confirmations').fetchone()[0], 2)
                self.assertIsNone(read_receipt(observer, order_id='T'))
                self.assertIsNone(read_receipt(observer, token='R/T'))
                self.assertEqual(read_receipt(observer, token=historical.token), historical)
        self.reopen(offline=True)
        item = collect(self.local, None, 'T').item
        self.assertEqual(read_receipt(self.local, order_id='T'), item)
        self.assertEqual(read_receipt(self.local, token=item.token), item)
        self.assertEqual(self.local.execute('SELECT count(*) FROM received_items WHERE order_id = ?', ('T',)).fetchone()[0], 1)
        self.assertEqual(self.local.execute('SELECT count(*) FROM receipt_tokens WHERE order_id = ?', ('T',)).fetchone()[0], 1)

    def test_confirmation_requires_exact_success(self):
        self.plan()
        stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')
        self.bench.lose.add(('T', 1))
        pending = collect(self.local, self.bench, 'T')
        outcome = query_transfer(self.device, pending.operation_id)
        with self.assertRaises(Conflict):
            confirm_candidate(self.local, outcome)
        with self.assertRaises(Conflict):
            finalize_receipt(self.local, 'T')
        item = collect(self.local, self.bench, 'T').item
        for inconsistent in (replace(outcome, revision=2), replace(outcome, operation_id='unknown'),
                             replace(outcome, status='stale')):
            with self.assertRaises(Conflict):
                confirm_candidate(self.local, inconsistent)
        self.assertEqual(read_receipt(self.local, token=item.token), item)

    def test_candidate_identity_is_immutable(self):
        self.plan()
        reading = stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')
        candidate = ReceiptCandidate(reading.order_id, reading.revision, reading.raw, reading.origin)
        with atomic(self.local):
            self.assertEqual(save_candidate(self.local, candidate), candidate)
            self.assertEqual(save_candidate(self.local, candidate), candidate)
            with self.assertRaises(Conflict):
                save_candidate(self.local, replace(candidate, raw=11))
        self.assertEqual(get_candidate(self.local, 'T', 1), candidate)
        self.assertIsNone(read_receipt(self.local, order_id='T'))
        self.assertEqual(collect(self.local, self.bench, 'T').item.raw, 7)

    def test_zero_and_repeat(self):
        self.plan('U', 'A02')
        reading = stage(self.local, self.device, 'U', 0, 'bench-A', 'U-1')
        result = collect(self.local, self.bench, 'U')
        self.assertEqual(result.status, 'received')
        self.assertEqual((result.item.raw, result.item.converted, result.item.origin), (0, 3, reading.origin))
        self.assertEqual(read_receipt(self.local, order_id='U'), result.item)
        self.assertIsNone(read_receipt(self.local, token='unknown'))
        self.reopen(offline=True)
        self.assertEqual(read_receipt(self.local, token=result.item.token), result.item)
        self.assertEqual(collect(self.local, None, 'U'), result)

    def test_frozen_recipe(self):
        self.plan()
        register_recipe(self.local, 'strip-v2', 10, -4)
        with self.assertRaises(Conflict):
            register_recipe(self.local, 'strip-v1', 10, -4)
        self.plan('U', 'A02', 'strip-v2')
        stage(self.local, self.device, 'T', 0, 'bench-A', 'T-1')
        stage(self.local, self.device, 'U', 7, 'bench-A', 'U-1')
        first = collect(self.local, self.bench, 'T').item
        second = collect(self.local, self.bench, 'U').item
        self.assertEqual((first.recipe_id, first.converted), ('strip-v1', 3))
        self.assertEqual((second.recipe_id, second.converted), ('strip-v2', 66))

    def test_integer_measurement_round_trip(self):
        self.plan()
        value = -(1 << 100)
        stage(self.local, self.device, 'T', value, 'bench-A', 'T-1')
        token = collect(self.local, self.bench, 'T').item.token
        self.reopen(offline=True)
        item = read_receipt(self.local, token=token)
        self.assertEqual(item.raw, value)
        self.assertEqual(item.converted, -(1 << 101) + 3)
