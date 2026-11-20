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
