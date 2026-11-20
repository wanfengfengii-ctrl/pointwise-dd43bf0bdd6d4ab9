# 带材复测室实收与班账

白班用计划登记应采样位，台架操作员暂存和更正厚度，采集员接管一次性原读，夜班按实收核对漏测。台架和计划实收分别使用 SQLite 文件。调用台架时，本地写事务已经结束。关掉台架后仍可按号领已签成果，也可完成已有本地成功证据的待签实收。

## 运行

使用 Python 3.11 标准库。在项目根目录运行平台提供的完整核验入口和演示。

```sh
python3 -B check_project.py
python3 -B demo.py
```

可直接发现同一完整套件。

```sh
python3 -B -m unittest discover -s tests -t .
```

演示用 `demo-data.json` 和临时目录中的两本账。T 原读由 7 更正为 11 μm，U 原读为 0，W 缺测。冻结规程为倍率 2、偏移 3，T 和 U 的正式换算值为 25 和 3 μm，班账依次列 T、U、W，有效 2 件，极值为 3 和 25 μm。

## 一天的操作

1. `storage.connect_db(path)` 打开账本连接。分别调用 `storage.initialize_local(local)` 和 `bench.handoff.initialize_bench(device)` 补建结构。初始化可重复执行。账本需成对使用，每名执行者使用自己的连接。默认规程 `identity-v1` 的倍率为 1、偏移为 0。
2. `planning.recipes.register_recipe(local, recipe_id, multiplier, offset)` 登记规程版本。`planning.orders.open_order(local, shift_id, order_id, sample, recipe_id)` 登记应采工单并返回 `Order`。同参重试沿用原位置，同号异参拒绝。工单固定样位和一个规程版本，后登记的版本供新工单选用。
3. `bench.staging.stage(local, device, order_id, raw, instrument, record)` 录入初版。`bench.corrections.correct(device, order_id, expected_revision, raw, record)` 按期望版次更正。两者返回 `StagedReading`。版次为从 1 开始的整数。出处包含设备、当前记录、初始记录、工单及版次。已暂存工单的变更走 `correct`，过期或已交出的暂存不可更正。
4. `capture.session.collect(local, SQLiteBench(device), order_id)` 接管。原采集请求以工单号续办，内部操作号绑定该工单的一版。核对工单及出处后，本地同时保全该版候选与操作，然后按版移交。台架的低层端口 `bench.handoff.transfer(device, order_id, revision, operation_id)` 返回 `HandoffOutcome`，状态为 `transferred`、`stale`、`empty` 或 `already_transferred`。`query_transfer(device, operation_id)` 取原终局，未知操作返回 `None`。同号异参拒绝。正常业务由采集器调用移交端口，以保证先保全原据。成功终局与暂存清除一起提交。
5. 回包不明时 `collect` 返回状态 `pending` 和操作号。另一执行者可沿原操作查实或安全重试。过期拒绝后采集现行版。无可读暂存且无待办操作时返回 `awaiting_reading`。已签返回 `received`，包含固定的 `item`。停源时传入 `bench=None`，本地已有成功证据的操作可继续签发，未决操作保持待查。
6. `receipt.readback.read_receipt(local, order_id=...)` 或 `read_receipt(local, token=...)` 领取固定 `ReceivedItem`，二者择一。未知或未签发返回 `None`。首执是账本内的标识，待查及发布失败时不可领取。原读及规程系数必须是整数，换算用 `倍率 × 原读 + 偏移`，结果以 μm 计。零是有效值，持久化保留完整整数精度。
7. `reconcile.publish.shift_receipt(local, shift_id)` 签出一个固定班账。每行保留应采工单、样位、规程、位置及正式件或缺测。只对已实收的换算值计数和取极值。已确认待签仍是缺测，全缺测的极值均为 `None`。未知班次拒绝，提交失败后可重试。
8. `reconcile.readback.read_shift_receipt(local, number)` 按原班账号领取，未知号返回 `None`。重复签发会交还同一班账。班账按固定行和首执读回，晚来的实收可单独领取，签发时的缺测及计量保持原样。

标识为非空字符串，参数形状无效时抛 `ValueError`，未知计划或班次抛 `storage.NotFound`，身份冲突及不允许的状态抛 `storage.Conflict`，来源不符抛 `capture.provenance.SourceMismatch`。数据库异常向调用方传播，所属事务回滚。设备回包丢失通过 `bench.handoff.ReplyLost` 表达，设备端已有终局仍可查询。公开业务入口接收由 `connect_db` 打开的空闲连接。低层写函数如 `allocate_order_position`、`save_candidate`、`register_attempt` 和 `publish_manifest` 接收调用方已开启的事务。
