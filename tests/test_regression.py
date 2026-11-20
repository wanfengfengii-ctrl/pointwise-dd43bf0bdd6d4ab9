"""Regression tests for the corrected-winner and late-rejection incidents.

These cases pin down the repairs without weakening any pre-existing assertion:

* a transfer that wins on a newer revision signs that revision, never the
  preserved older raw reading;
* a late ``stale`` outcome belongs to its own operation and cannot erase a
  newer operation's verified handoff, so the confirmed transfer can still be
  signed after the bench goes offline;
* terminal operation states are immutable;
* while an operation is still in flight, no newer revision is prepared first.
"""
from contextlib import closing

from bench.corrections import correct
from bench.handoff import query_transfer
from bench.staging import get_staged_reading, stage
from capture.attempts import get_attempt, get_current_attempt
from capture.session import collect
from receipt.candidates import get_candidate
from receipt.readback import read_receipt
from storage import Conflict, connect_db
from tests.support import ControlledBench, LedgerTest


class CorrectedWinnerRegressionTests(LedgerTest):
    def test_late_stale_rejection_keeps_verified_newer_handoff(self):
        self.plan()
        stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')

        def second_executor_holds_old_reply(operation_id):
            correct(self.device, 'T', 1, 11, 'T-2')
            # The old operation receives its rejection only after the newer
            # revision has already been verified and signed.
            stale = query_transfer(self.device, operation_id)
            self.assertIsNone(stale)
            with closing(connect_db(self.local_path)) as local, \
                    closing(connect_db(self.device_path)) as device:
                result = collect(local, ControlledBench(device), 'T')
                self.assertEqual((result.status, result.item.raw), ('received', 11))
            self.assertEqual(query_transfer(self.device, operation_id).status, 'stale')

        self.bench.before['T', 1] = second_executor_holds_old_reply
        first = collect(self.local, self.bench, 'T')

        # The late rejection is recorded on the old operation only and does
        # not touch the newer, verified operation.
        old_operation = f'capture/1/T/1'
        self.assertEqual(get_attempt(self.local, old_operation).state, 'stale')
        self.assertEqual(get_current_attempt(self.local, 'T').state, 'confirmed')
        self.assertEqual(first.item.operation_id, f'capture/1/T/2')

        # Only the actually transferred revision is claimable, by order id and
        # by the first-executor token, with identical results.
        self.assertIsNone(get_staged_reading(self.device, 'T'))
        by_order = read_receipt(self.local, order_id='T')
        by_token = read_receipt(self.local, token='R/T')
        self.assertEqual(by_order, by_token)
        self.assertEqual((by_order.revision, by_order.raw, by_order.converted), (2, 11, 25))
        self.assertEqual((by_order.origin.instrument, by_order.origin.record,
                          by_order.origin.initial_record), ('bench-A', 'T-2', 'T-1'))
        # The older raw reading and its provenance remain preserved as evidence.
        self.assertEqual(get_candidate(self.local, 'T', 1).raw, 7)
        self.assertEqual(get_candidate(self.local, 'T', 2).origin.record, 'T-2')
        self.assertEqual(self.local.execute('SELECT count(*) FROM receipt_tokens').fetchone()[0], 1)

        # Reopen with the bench stopped: the verified handoff still re-signs.
        self.reopen(offline=True)
        offline = collect(self.local, None, 'T')
        self.assertEqual((offline.status, offline.item), ('received', by_order))
        self.assertEqual(read_receipt(self.local, token='R/T'), by_order)

    def test_stale_only_order_stays_awaiting_without_a_claim(self):
        self.plan()
        stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')

        def reject_before_transfer(operation_id):
            correct(self.device, 'T', 1, 11, 'T-2')

        self.bench.before['T', 1] = reject_before_transfer
        result = collect(self.local, self.bench, 'T')
        self.assertEqual((result.item.revision, result.item.raw), (2, 11))
        self.assertEqual(get_attempt(self.local, f'capture/1/T/1').state, 'stale')
        self.assertEqual(get_current_attempt(self.local, 'T').state, 'confirmed')
        # The stale operation produced no receipt; the single token belongs to r2.
        item = read_receipt(self.local, order_id='T')
        self.assertEqual((item.revision, item.token), (2, 'R/T'))
        self.assertEqual(read_receipt(self.local, token='R/T'), item)
        self.assertEqual(self.local.execute('SELECT count(*) FROM receipt_tokens').fetchone()[0], 1)

    def test_terminal_attempt_state_is_immutable(self):
        from bench.outcomes import HandoffOutcome
        from capture.attempts import save_outcome
        from storage import atomic

        self.plan()
        stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')
        collect(self.local, self.bench, 'T')
        confirmed = get_current_attempt(self.local, 'T')
        self.assertEqual(confirmed.state, 'confirmed')

        with atomic(self.local):
            with self.assertRaises(Conflict):
                save_outcome(
                    self.local,
                    HandoffOutcome(confirmed.operation_id, 'T', 1, 'stale'),
                )
        # The verified state survives the conflicting late reply.
        self.assertEqual(get_current_attempt(self.local, 'T').state, 'confirmed')

    def test_inflight_operation_settles_before_newer_revision_is_prepared(self):
        self.plan()
        stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')

        def correct_and_observe(operation_id):
            # Hook fires while the revision-1 transfer is being sent: at this
            # point revision 1 has its durable operation and revision 2 does not.
            self.assertEqual(get_attempt(self.local, operation_id).revision, 1)
            self.assertIsNone(get_attempt(self.local, 'capture/1/T/2'))
            correct(self.device, 'T', 1, 11, 'T-2')

        self.bench.before['T', 1] = correct_and_observe
        result = collect(self.local, self.bench, 'T')
        self.assertEqual((result.item.revision, result.item.raw), (2, 11))
        # The first wire call settles the revision-1 operation as stale before
        # the revision-2 operation is prepared and sent.
        self.assertEqual([call[:2] for call in self.bench.sent], [('T', 1), ('T', 2)])
        self.assertEqual(get_attempt(self.local, 'capture/1/T/1').state, 'stale')
        self.assertEqual(get_attempt(self.local, 'capture/1/T/2').state, 'confirmed')
