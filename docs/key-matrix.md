# KEY-MATRIX-1：右键偶发被当作退出键

## 现象与证据边界

2026-09-07 用户反馈：长按右键偶尔打开系统菜单，随后补充短按也会发生。
不能将其归因于方向键自动连发。当前队列和翻译映射分别保持
Right=`0x39`、Exit=`0x2E`，没有把连发转换成退出的代码。

扫描矩阵中 Right 位于 row 7 / column 6，Exit 的两个别名在 row 0 和 row 5 /
column 6，Enter 在 row 1 / column 6。旧实现选通一行后立即读取列线，未设
全行释放或稳定读。当固件先前选中过 row 7，列线还保留右键的低电平时，
私有扫描第一次读 row 0 就可能将它归到 Exit。

这是代码中可识别、且已在受控延迟模型复现的风险，不是已经采集到的真机
电气波形。模拟器默认矩阵即时响应，不能自然证明或排除硬件稳定时间问题。

## 修改

新增通用 `c6502_native_matrix.h`，不改游戏、键值表、连发规则或性能 helper：

1. 每次换行先写 `0xFF` 释放所有行，进行 4 对 K5/P0 的 volatile 丢弃读取。
2. 选通目标行，再进行 4 对丢弃读取，然后取两份列样本。
3. 不一致的位保持上次状态，留待下一扫描确认，避免毛刺制造按下或松开边沿。
4. 新的 Enter/Exit 候选在全矩阵扫描后重新独立选行确认。
5. 结束扫描先释放行、稳定，再由原调用方完整恢复行/端口/PSR 和新增 IRQ 因子。

不屏蔽真正的 Right+Exit/Enter 组合；确认/退出仍不连发。稳定读取在一次扫描内
完成，不使用 `Sleep`、GUI Timer 或额外的毫秒级按下延迟。扫描仍受 CTM 门限控制。
它增加少量固定 MMIO 工作量；真机开销与是否彻底解决串键仍需复测。

## 回归

`tests/test_matrix.py` 执行实际 C 扫描器，并模拟行切换后的 0–8 次列读取滞后。
旧直接读取方式在 row7→row0 条件下实际得到 `0x2E`。
新代码覆盖每种滞后下 200 次右键短按、2000 次持有扫描，检查只能产生 Right；
还覆盖两个 Exit 别名、Right+Enter/Exit、单样本毛刺、首次选行时两样本毛刺、
启动键基线与 PSR/端口恢复。该模型是控制实验，不代表真机已复现同一内部状态。

完整回归 81 项通过；保留 NATIVE-ALU-1 的 13 个共享寄存器 helper。

## 轻量日志

构建标记为 `KEY-MATRIX-1`，不启用 OTHER-PROFILE 重采样。

- `key_matrix_unstable_rows`：同一行两份样本不同的次数。
- `key_matrix_action_checks`：Enter/Exit 新候选独立复核次数（含启动基线）。
- `key_matrix_action_rejected`：复核未成立而丢弃的候选数。
- `key_matrix_trace_overwritten`：超出最近 8 项环形记录的条数。
- `key_matrix_action,seq,tick,row,first,verify,right`：按时间顺序输出最近 8 次候选，
  最后三项为十进制 7-bit 行掩码；`right` 是同轮 row 7 快照。

例如 `row=0,first=64,verify=0,right=64` 表示右键存在时，一个 Exit 候选被复核
否决。计数为零不能证明没有电气毛刺：稳定阶段丢弃的样本不会计数。
该记录也不能证明游戏已消费该键；应与 `key_edges/keys_consumed` 和实际现象结合。
