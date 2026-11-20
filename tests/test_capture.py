from contextlib import closing
from dataclasses import replace
import json
import sqlite3

from bench.corrections import correct
from bench.handoff import query_transfer, transfer
from bench.outcomes import get_successful_handoff
from bench.staging import get_staged_reading, stage
from capture.attempts import get_attempt, get_current_attempt
from capture.provenance import SourceMismatch, verify_provenance
from capture.session import collect
from capture.transfer import apply_outcome
from receipt.candidates import get_candidate
from receipt.readback import read_receipt
from reconcile.publish import shift_receipt
from storage import Conflict, NotFound, connect_db
from tests.support import ControlledBench, LedgerTest, force_commit_failure


class CaptureTests(LedgerTest):
    def setUp(self):
        super().setUp()
        self.order = self.plan()
        self.first = stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')

    def correct_t(self):
        return correct(self.device, 'T', 1, 11, 'T-2')

    def assert_not_released(self):
        self.assertIsNone(read_receipt(self.local, order_id='T'))
        self.assertIsNone(read_receipt(self.local, token='R/T'))

    def test_correct_before_handoff(self):
        def correct_after_preserving(operation_id):
            self.assertEqual(get_candidate(self.local, 'T', 1).raw, 7)
            self.assertEqual(get_attempt(self.local, operation_id).revision, 1)
            self.correct_t()

        self.bench.before['T', 1] = correct_after_preserving
        result = collect(self.local, self.bench, 'T')
        old_id = self.bench.sent[0][2]
        self.assertEqual(query_transfer(self.device, old_id).status, 'stale')
        self.assertEqual((result.item.revision, result.item.raw, result.item.converted), (2, 11, 25))
        self.assertEqual(result.item.origin.record, 'T-2')
        self.assertEqual(get_candidate(self.local, 'T', 1).origin, self.first.origin)
        self.assertEqual(read_receipt(self.local, token=result.item.token), result.item)

    def test_stale_rejected(self):
        corrected = self.correct_t()
        with self.assertRaises(Conflict):
            self.correct_t()
        with self.assertRaises(Conflict):
            stage(self.local, self.device, 'T', 99, 'bench-A', 'T-duplicate')
        with self.assertRaises(NotFound):
            stage(self.local, self.device, 'UNKNOWN', 7, 'bench-A', 'other')
        stale = transfer(self.device, 'T', 1, 'inspection-stale')
        self.assertEqual(stale.status, 'stale')
        self.assertEqual(query_transfer(self.device, 'inspection-stale'), stale)
        self.assertEqual(get_staged_reading(self.device, 'T'), corrected)
        self.assertIsNone(get_successful_handoff(self.device, 'T'))
        item = collect(self.local, self.bench, 'T').item
        self.assertEqual((item.revision, item.raw, item.origin), (2, 11, corrected.origin))

    def test_origin_mismatch(self):
        self.plan('U', 'A02')
        foreign = stage(self.local, self.device, 'U', 7, 'bench-A', 'U-1')
        with self.assertRaises(SourceMismatch):
            verify_provenance(self.order, foreign)
        with self.assertRaises(SourceMismatch):
            verify_provenance(self.order, replace(self.first, origin=replace(self.first.origin, revision=2)))
        self.assertIsNone(get_candidate(self.local, 'T', 1))
        self.assertIsNone(get_successful_handoff(self.device, 'T'))
        self.assertEqual(collect(self.local, self.bench, 'T').item.origin, self.first.origin)

    def test_resume_lost_reply(self):
        self.bench.lose.add(('T', 1))
        pending = collect(self.local, self.bench, 'T')
        self.assertEqual(pending.status, 'pending')
        self.assertEqual(get_current_attempt(self.local, 'T').state, 'pending')
        self.assertIsNone(get_staged_reading(self.device, 'T'))
        self.assert_not_released()
        actual = query_transfer(self.device, pending.operation_id)
        self.assertEqual((actual.order_id, actual.revision, actual.status), ('T', 1, 'transferred'))
        self.reopen()
        finished = collect(self.local, self.bench, 'T')
        self.assertEqual((finished.status, finished.operation_id), ('received', pending.operation_id))
        self.assertEqual((finished.item.raw, finished.item.converted, finished.item.origin), (7, 17, self.first.origin))
        self.assertEqual(self.bench.sent, [])
        self.assertEqual(self.bench.queried, [pending.operation_id])
        self.reopen(offline=True)
        self.assertEqual(read_receipt(self.local, token=finished.item.token), finished.item)
        self.assertEqual(collect(self.local, None, 'T'), finished)

    def test_corrected_winner(self):
        self.bench.before['T', 1] = lambda operation_id: self.correct_t()
        self.bench.lose.add(('T', 2))
        pending = collect(self.local, self.bench, 'T')
        self.assertEqual(pending.status, 'pending')
        self.assertIsNone(get_staged_reading(self.device, 'T'))
        self.assert_not_released()
        real_handoff = get_successful_handoff(self.device, 'T')
        self.assertEqual((real_handoff.revision, real_handoff.operation_id), (2, pending.operation_id))
        with closing(connect_db(self.local_path)) as observer:
            self.assertEqual((get_candidate(observer, 'T', 1).raw, get_candidate(observer, 'T', 2).raw), (7, 11))
        self.reopen()
        item = collect(self.local, self.bench, 'T').item
        self.assertIsNotNone(item, 'no confirmed receipt after checking the completed handoff')
        self.assertEqual(item.raw, 11, 'WRONG_RECEIVED_REVISION')
        self.assertEqual((item.revision, item.operation_id, item.converted), (2, real_handoff.operation_id, 25))
        self.assertEqual((item.origin.instrument, item.origin.record, item.origin.initial_record), ('bench-A', 'T-2', 'T-1'))
        self.assertEqual(self.bench.queried, [real_handoff.operation_id])
        self.assertEqual(self.bench.sent, [])
        reread = read_receipt(self.local, token=item.token)
        self.assertEqual(reread, item)
        self.assertEqual(self.local.execute('SELECT count(*) FROM receipt_tokens').fetchone()[0], 1)
        manifest = shift_receipt(self.local, 'D1')
        self.assertEqual(manifest.lines[0].item, reread)
        self.assertEqual((manifest.summary.count, manifest.summary.minimum, manifest.summary.maximum), (1, 25, 25))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v4.corrected_winner',
            'input': {'order': 'T', 'staged': [7, 11], 'lost_reply': True, 'multiplier': 2, 'offset': 3},
            'expected': {'revision': 2, 'raw': 11, 'converted': 25, 'record': 'T-2', 'token': 'R/T'},
            'actual': {'revision': item.revision, 'raw': item.raw, 'converted': item.converted,
                       'record': item.origin.record, 'token': item.token},
            'downstream_expected': [1, 25, 25],
            'downstream_actual': [manifest.summary.count, manifest.summary.minimum, manifest.summary.maximum],
            'code_paths': ['bench/handoff.py', 'capture/resume.py', 'receipt/finalize.py', 'reconcile/publish.py'],
            'oracle': '原台架终局为 r2，独立手算 2×11+3=25，班内只有这件正式实收。',
        }, ensure_ascii=False, sort_keys=True))

    def test_operation_identity(self):
        pending_order = collect(self.local, self.bench, 'T')
        outcome = query_transfer(self.device, pending_order.operation_id)
        self.assertEqual(transfer(self.device, 'T', 1, outcome.operation_id), outcome)
        with self.assertRaises(Conflict):
            transfer(self.device, 'T', 2, outcome.operation_id)
        with self.assertRaises(Conflict):
            transfer(self.device, 'U', 1, outcome.operation_id)
        self.assertEqual(query_transfer(self.device, outcome.operation_id), outcome)
        self.assertIsNone(query_transfer(self.device, 'unknown'))
        self.assertEqual(transfer(self.device, 'T', 1, 'another-operation').status, 'already_transferred')
        with self.assertRaises(Conflict):
            apply_outcome(self.local, get_current_attempt(self.local, 'T'), replace(outcome, revision=2))

    def test_handoff_wins(self):
        def late_correction(outcome):
            self.assertEqual(outcome.status, 'transferred')
            with self.assertRaises(Conflict):
                self.correct_t()
            self.assertIsNone(get_staged_reading(self.device, 'T'))
            self.assert_not_released()

        self.bench.after['T', 1] = late_correction
        self.bench.lose.add(('T', 1))
        first = collect(self.local, self.bench, 'T')
        self.assertEqual(first.status, 'pending')
        self.reopen()
        item = collect(self.local, self.bench, 'T').item
        self.assertEqual((item.revision, item.raw, item.origin), (1, 7, self.first.origin))
        self.assertEqual(item.operation_id, first.operation_id)
        self.assertIsNone(get_candidate(self.local, 'T', 2))

    def test_two_executors(self):
        second_results = []

        def collect_while_first_waits(outcome):
            self.assertEqual(outcome.status, 'transferred')
            self.assert_not_released()
            self.assertFalse(self.local.in_transaction)
            with closing(connect_db(self.local_path)) as local, closing(connect_db(self.device_path)) as device:
                second_bench = ControlledBench(device)
                second_results.append(collect(local, second_bench, 'T'))
                self.assertEqual(second_bench.queried, [outcome.operation_id])
                self.assertEqual(second_bench.sent, [])

        self.bench.after['T', 1] = collect_while_first_waits
        self.bench.lose.add(('T', 1))
        first = collect(self.local, self.bench, 'T')
        self.assertEqual(first, second_results[0])
        self.assertEqual((first.status, first.item.raw, first.item.origin.record), ('received', 7, 'T-1'))
        self.assertEqual(get_current_attempt(self.local, 'T').state, 'confirmed')
        self.assertEqual(self.device.execute(
            "SELECT count(*) FROM handoff_outcomes WHERE status = 'transferred'"
        ).fetchone()[0], 1)
        self.assertEqual(self.local.execute('SELECT count(*) FROM receipt_tokens').fetchone()[0], 1)

    def test_late_stale_reply_keeps_newer_progress(self):
        second_results = []

        def correct_and_resume(operation_id):
            self.correct_t()
            with closing(connect_db(self.local_path)) as local, closing(connect_db(self.device_path)) as device:
                second_results.append(collect(local, ControlledBench(device), 'T'))
                self.assertEqual(query_transfer(device, operation_id).status, 'stale')

        self.bench.before['T', 1] = correct_and_resume
        first = collect(self.local, self.bench, 'T')
        self.assertEqual(first, second_results[0])
        self.assertEqual((first.item.revision, first.item.raw), (2, 11))
        self.assertEqual(get_current_attempt(self.local, 'T').operation_id, first.operation_id)

    def test_candidate_write_failure(self):
        with force_commit_failure(self.local, 'receipt_candidates'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                collect(self.local, self.bench, 'T')
            with closing(connect_db(self.local_path)) as observer:
                self.assertIsNone(get_candidate(observer, 'T', 1))
                self.assertIsNone(get_current_attempt(observer, 'T'))
            self.assertEqual(self.bench.sent, [])
            self.assertEqual(self.device.execute('SELECT count(*) FROM handoff_outcomes').fetchone()[0], 0)
            self.assertEqual(get_staged_reading(self.device, 'T'), self.first)
            self.assert_not_released()
        self.assertEqual(collect(self.local, self.bench, 'T').item.raw, 7)

    def test_durable_before_clear(self):
        def check_durable_candidate(operation_id):
            self.assertEqual(get_staged_reading(self.device, 'T'), self.first)
            self.assertIsNone(query_transfer(self.device, operation_id))
            self.assertFalse(self.local.in_transaction)
            with closing(connect_db(self.local_path)) as other:
                self.assertEqual(get_candidate(other, 'T', 1).origin, self.first.origin)
                attempt = get_attempt(other, operation_id)
                self.assertEqual((attempt.order_id, attempt.revision, attempt.state), ('T', 1, 'prepared'))

        self.bench.before['T', 1] = check_durable_candidate
        item = collect(self.local, self.bench, 'T').item
        self.assertIsNone(get_staged_reading(self.device, 'T'))
        self.assertEqual(get_successful_handoff(self.device, 'T').operation_id, item.operation_id)
