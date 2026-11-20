# 工单 T 的两次实收重演

白班先保全 T 的 7 μm 原读，台架在移交成立前更正为 11 μm。台架拒绝旧版，实际交出新版，清除暂存后丢失成功回包。未查实时，工单号和首执号均领不到正式件。重开后目前会领到 7 μm。正确成果是新版原读 11 μm、按冻结规程换算的 25 μm、T-2 出处及原首执 R/T。班内只有这一件，极值均为 25 μm。

```sh
python3 -B -m unittest tests.test_capture.CaptureTests.test_corrected_winner
```

另一轮中，接替者在原执行者收到旧版拒绝前查实新版已交出，但签发提交失败。旧版拒绝随后到达。台架关闭后，重开实收账目前无法重领或续签。提交故障解除后，应能停源续签刚才查实的新版，按工单号和首执号领取的成果应一致。失败期间两种领取均为空。

```sh
python3 -B -m unittest tests.test_handoff_incident.HandoffIncidentTests.test_late_rejection_cannot_erase_verified_handoff
```

接口、完整核验和正常班账演示均沿用 README.md。正常演示中的 T 在采集前已更正，U 为零，W 缺测。事故样例中的更正发生在旧版原读已经保全之后。

## 根因与修复

1. **实收错签旧版（重开领到 7 μm）**：`receipt/finalize.py` 原先按 `MIN(revision)` 取候选，签出的是最早保全的原读，而不是 `receipt_confirmations` 里实际移交成功的版次。改为按确认记录中的 `revision` 取候选；旧版候选与出处仍保留为证据，但新版胜出后不再发布。
2. **迟到旧版拒绝覆盖新版终局（停源无法续签）**：操作状态原存放在按工单唯一的 `capture_progress`，旧操作的迟到 `stale` 会改写同一行，把新版已 `confirmed` 的状态冲掉。现将 `state/terminal_status` 下沉到 `capture_attempts`，每个操作（工单+版次）各自持有不可变终局；`save_outcome`/`mark_pending` 对已终局操作只做幂等确认，迟到结果只归原操作。
3. **在途操作未先终局就备办新版**：`capture/session.py` 重排为：先把在途（无终局）操作查实或重试到终局，再为更新暂存备办新操作；回包不明维持 `pending`，待查/签发失败不可领取。已 `confirmed` 而签发失败的，台架停源（`bench=None`）时凭本地成功证据仍可续签。

回归：新增 `tests/test_regression.py`（迟到拒绝不擦除新版、纯 stale 不可领取、终局不可变、在途先终局再备新版）。原 28 条断言全部保留并通过，现共 32 条；`python3 -B check_project.py` 与 `python3 -B demo.py` 均通过，演示只领到 T 的 11 μm/25 μm、T-2 出处与一份首执 `R/T`。
