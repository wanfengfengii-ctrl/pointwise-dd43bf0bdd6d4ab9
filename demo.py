from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from bench.corrections import correct
from bench.handoff import SQLiteBench, initialize_bench
from bench.staging import stage
from capture.session import collect
from planning.orders import open_order
from planning.recipes import register_recipe
from receipt.readback import read_receipt
from reconcile.publish import shift_receipt
from reconcile.readback import read_shift_receipt
from storage import connect_db, initialize_local


def main() -> None:
    sample = json.loads(Path(__file__).with_name('demo-data.json').read_text(encoding='utf-8'))
    recipe = sample['recipe']
    with TemporaryDirectory() as directory:
        local_path = Path(directory) / 'ledger.sqlite'
        device_path = Path(directory) / 'bench.sqlite'
        with closing(connect_db(local_path)) as local, closing(connect_db(device_path)) as device:
            initialize_local(local)
            initialize_bench(device)
            register_recipe(local, recipe['id'], recipe['multiplier'], recipe['offset'])
            bench = SQLiteBench(device)
            for entry in sample['orders']:
                order_id = entry['id']
                open_order(local, sample['shift_id'], order_id, entry['sample'], recipe['id'])
                reading = entry['reading']
                if reading is None:
                    continue
                staged = stage(local, device, order_id, reading['raw'], sample['instrument'], reading['record'])
                correction = reading.get('correction')
                if correction is not None:
                    correct(device, order_id, staged.revision, correction['raw'], correction['record'])
                if collect(local, bench, order_id).status != 'received':
                    raise AssertionError(f'demo order {order_id} remains unreceived')
            number = shift_receipt(local, sample['shift_id']).number
        with closing(connect_db(local_path)) as offline:
            manifest = read_shift_receipt(offline, number)
            actual = []
            for line in manifest.lines:
                if line.item is None:
                    actual.append({'order': line.order_id, 'sample': line.sample, 'missing': True})
                    continue
                item = read_receipt(offline, token=line.item.token)
                if item != line.item:
                    raise AssertionError('shift line does not match its first receipt')
                actual.append({
                    'order': line.order_id, 'sample': line.sample, 'raw': item.raw, 'converted': item.converted,
                    'revision': item.revision, 'record': item.origin.record, 'token': item.token,
                })
            downstream = {'summary': asdict(manifest.summary), 'missing': list(manifest.missing_orders)}
        expected = [
            {'order': 'T', 'sample': 'A01', 'raw': 11, 'converted': 25, 'revision': 2,
             'record': 'sheet-T-2', 'token': 'R/T'},
            {'order': 'U', 'sample': 'A02', 'raw': 0, 'converted': 3, 'revision': 1,
             'record': 'sheet-U-1', 'token': 'R/U'},
            {'order': 'W', 'sample': 'A03', 'missing': True},
        ]
        downstream_expected = {'summary': {'count': 2, 'minimum': 3, 'maximum': 25}, 'missing': ['W']}
        if actual != expected or downstream != downstream_expected:
            raise AssertionError(f'unexpected closed-shift readback: {actual!r}, {downstream!r}')
        print(f'班账 {manifest.number}，有效 {manifest.summary.count} 件，'
              f'极值 {manifest.summary.minimum}–{manifest.summary.maximum} μm，缺测 {", ".join(manifest.missing_orders)}')
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v8.zero_vs_missing', 'input': sample, 'expected': expected, 'actual': actual,
            'downstream_expected': downstream_expected, 'downstream_actual': downstream,
            'code_paths': ['bench/corrections.py', 'capture/session.py', 'receipt/conversion.py',
                           'reconcile/summary.py', 'reconcile/publish.py', 'reconcile/readback.py'],
            'oracle': '手算 2×11+3=25、2×0+3=3。W 无正式件，按 T、U、W 的登记顺序核对。',
        }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
