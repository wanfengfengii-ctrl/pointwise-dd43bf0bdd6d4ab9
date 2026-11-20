from bench.staging import stage
from capture.session import collect
from planning.initialize import DEFAULT_RECIPE_ID, initialize_planning
from planning.orders import get_order, list_shift_orders, open_order
from planning.recipes import Recipe, get_recipe, register_recipe
from planning.shifts import get_shift
from receipt.readback import read_receipt
from storage import Conflict, NotFound
from tests.support import LedgerTest


class PlanTests(LedgerTest):
    def test_reinitialize(self):
        order = self.plan()
        self.reopen()
        self.assertEqual(get_order(self.local, 'T'), order)
        self.assertEqual(list_shift_orders(self.local, 'D1'), (order,))
        self.assertEqual(get_shift(self.local, 'D1').next_position, 2)
        self.assertEqual(get_recipe(self.local, 'strip-v1'), Recipe('strip-v1', 2, 3))
        self.assertEqual(get_recipe(self.local, DEFAULT_RECIPE_ID), Recipe(DEFAULT_RECIPE_ID, 1, 0))

    def test_history_after_reinitialize(self):
        order = self.plan()
        self.plan('U', 'A02')
        stage(self.local, self.device, 'T', 7, 'bench-A', 'T-1')
        historical = collect(self.local, self.bench, 'T').item
        new_recipe = register_recipe(self.local, 'strip-v2', 5, -2)
        self.reopen()
        initialize_planning(self.local)
        self.assertEqual(get_order(self.local, 'T'), order)
        self.assertEqual(get_recipe(self.local, order.recipe_id), Recipe('strip-v1', 2, 3))
        self.assertEqual(get_recipe(self.local, 'strip-v2'), new_recipe)
        self.assertEqual(read_receipt(self.local, token=historical.token), historical)
        self.assertEqual((historical.raw, historical.converted), (7, 17))
        stage(self.local, self.device, 'U', 7, 'bench-A', 'U-1')
        self.assertEqual(collect(self.local, self.bench, 'U').item.converted, 17)

    def test_conflicting_order(self):
        original = self.plan()
        self.assertEqual(self.plan(), original)
        with self.assertRaises(Conflict):
            self.plan(sample='A02')
        with self.assertRaises(Conflict):
            self.plan(shift_id='other')
        self.reopen()
        self.assertEqual(get_order(self.local, 'T'), original)
        self.assertEqual(list_shift_orders(self.local, 'D1'), (original,))
        self.assertIsNone(get_shift(self.local, 'other'))
        self.assertEqual(self.plan('U', 'A02').position, 2)

    def test_invalid_recipe_atomic(self):
        with self.assertRaises(NotFound):
            open_order(self.local, 'new-shift', 'T', 'A01', 'missing')
        self.assertIsNone(get_shift(self.local, 'new-shift'))
        self.assertIsNone(get_order(self.local, 'T'))
        first = self.plan()
        with self.assertRaises(NotFound):
            self.plan('U', 'A02', 'missing')
        self.assertEqual(list_shift_orders(self.local, 'D1'), (first,))
        self.assertEqual(self.plan('W', 'A03').position, 2)
