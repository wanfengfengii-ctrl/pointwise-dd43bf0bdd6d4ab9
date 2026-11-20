from contextlib import contextmanager
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from bench.handoff import ReplyLost, SQLiteBench, initialize_bench
from planning.orders import open_order
from planning.recipes import register_recipe
from storage import connect_db, initialize_local


class ControlledBench(SQLiteBench):
    def __init__(self, connection):
        super().__init__(connection)
        self.before = {}
        self.after = {}
        self.lose = set()
        self.sent = []
        self.queried = []

    def query(self, operation_id):
        self.queried.append(operation_id)
        return super().query(operation_id)

    def transfer(self, order_id, revision, operation_id):
        key = (order_id, revision)
        self.sent.append((order_id, revision, operation_id))
        before = self.before.pop(key, None)
        if before is not None:
            before(operation_id)
        result = super().transfer(order_id, revision, operation_id)
        after = self.after.pop(key, None)
        if after is not None:
            after(result)
        if key in self.lose and result.status == 'transferred':
            self.lose.remove(key)
            raise ReplyLost(operation_id)
        return result


@contextmanager
def force_commit_failure(connection: sqlite3.Connection, table: str):
    if table not in {'receipt_candidates', 'receipt_tokens', 'signed_shift_lines'}:
        raise ValueError(table)
    connection.executescript(f'''
        CREATE TABLE fixture_parent (id INTEGER PRIMARY KEY);
        CREATE TABLE fixture_child (
            id INTEGER REFERENCES fixture_parent(id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE TRIGGER fixture_fail_commit AFTER INSERT ON {table}
        BEGIN INSERT INTO fixture_child VALUES (1); END;
    ''')
    try:
        yield
    finally:
        connection.executescript('''
            DROP TRIGGER fixture_fail_commit;
            DROP TABLE fixture_child;
            DROP TABLE fixture_parent;
        ''')


class LedgerTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.local_path = Path(directory.name) / 'ledger.sqlite'
        self.device_path = Path(directory.name) / 'bench.sqlite'
        self.reopen()
        register_recipe(self.local, 'strip-v1', 2, 3)

    def reopen(self, *, offline=False):
        if hasattr(self, 'local'):
            self.local.close()
        if getattr(self, 'device', None) is not None:
            self.device.close()
        self.local = connect_db(self.local_path)
        self.addCleanup(self.local.close)
        initialize_local(self.local)
        self.device = None
        self.bench = None
        if not offline:
            self.device = connect_db(self.device_path)
            self.addCleanup(self.device.close)
            initialize_bench(self.device)
            self.bench = ControlledBench(self.device)

    def plan(self, order_id='T', sample='A01', recipe_id='strip-v1', shift_id='D1'):
        return open_order(self.local, shift_id, order_id, sample, recipe_id)
