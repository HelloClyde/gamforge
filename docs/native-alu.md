# NATIVE-ALU-1：共享寄存器基础运行库

## 范围

根据 OTHER-PROFILE-1 真机日志，先优化通用语义 helper，而非特定游戏函数。
`compiler/fast_helpers.py` 生成 13 个短 S1C33 实现：

- `sem_cmp8`、`sem_adc8`、`sem_sbc8`。
- `sem_asl_a`、`sem_lsr_a`。
- `sem_store16_imm`、`runtime_cmp_int`。
- 普通 RAM 的 `sem_inc_m/dec_m/asl_m/lsr_m/rol_m/ror_m`。

原路径为原生游戏函数 → 全寄存器 C 桥接 → C 语义函数 → 写回共享状态。
新路径为原生游戏函数 → 直接使用共享寄存器的 S1C33 leaf → 返回。
没有增加解释器、运行时翻译或游戏特定签名。

本轮不修改图片合成算法、游戏延时循环、Timer 参数、输入轮询或退出流程。
普通构建仍输出轻量 PERF 5，build 为 `NATIVE-ALU-1`；不启用 `--profile-other`。

## ABI 与边界

- A/X/Y/SP/NZ/P/software-SP/RAM 仍分别驻留 R4/R5/R6/R7/R8/R9/R10/R14。
- R0–R3 可能已经保存部分求值完成的调用参数，临时使用时必须 push/pop。
- R11/R12/R13 仅按原 C 语义修改；例如读改写只更新 R13，不破坏 R12 地址。
- R15 始终保留固件 DP；helper 不禁用中断，不改变系统调度模式。
- RMW 先截断地址为 16 位，再检查 DATA、bank、只读固件页、折行 LCD、
  `$021B/$2028` 等副作用地址。失败时在读取前恢复 scratch，进入原 C 桥接。
- `store16_imm` 操作编译器临时区，沿用 `semantic_put16` 语义：
  `$28` 更新 R10 而非过期 RAM 影子；`$FF` 的高字节位于 `$100`，不是 `$00`。
- `runtime_cmp_int` 保留原 C6502 返回契约：A=P，X=非零差值字节数，
  R8 为 0/1/0x80；不能改成普通 C 比较布尔值。
- ADC/SBC 等价于当前 C 运行库，未在本轮额外引入 BCD 规则。

探针发现原编码工具把 32 位取反掩码用于三条 EXT 的寄存器形式时，目标会
截去高位。新 helper 使用短正数 OR/XOR 清位，保留完整 P 值；不依赖
“实际游戏里 P 通常只有 8 位”掩盖问题。

## 验证

`scripts/build_native_alu_probe.py` 从运行库提取原 C switch 和比较逻辑作为
参考，编译为独立 S1C33 ELF，同时链接本轮生成的真实汇编 helper。

2026-09-06，bbk9288-emulator 的独立暂停启动实例执行 **724,800** 组并通过：

| 测试 | 组数 |
| --- | ---: |
| ADC / SBC / CMP：所有 8 位操作数组合、两种 carry | 393,216 |
| ASL / LSR：0–511 输入、所有 8 位 P 值 | 262,144 |
| 16 位比较：覆盖所有左操作数，随机右值和 P | 65,536 |
| 16 位立即数存储：所有低 8 位目的地址，含 $28 / $FF | 1,024 |
| 6 种 RMW：30 个普通/边界/副作用地址、16 种数值 | 2,880 |

逐项比较全部 16 个寄存器；内存型测试另比较完整 32 KiB RAM。
RMW 非法快速路径使用哨兵检查“未读取、未写入、寄存器已恢复”，真正慢路径
仍由原 C 运行库处理。该探针不是性能基准，不用于预测真机提速。

生成探针（使用项目的 9288 GNU33 ABI 工具链）：

```powershell
$env:PYTHONPATH = 'src'
python scripts/build_native_alu_probe.py --toolchain <llvm-s1c33> --output-dir <probe-dir>
```

在独立、以 `-S` 启动的 9288 模拟器中加载 `probe.bin` 到 `0x02700000`，
用 ELF 符号设置 PC=`probe_start`，PSR=0，SP=`0x027E0000`；
运行到 `probe_done`，读取 `report`：`[0]=0x50415353`、`[1]=724800`、`[2]=0`。
不要在用户正在游玩的实例上注入；也不要在固件已 HALT 后仅清 IE 再改 PC，
那会因 CPU 仍处于睡眠而不执行测试，不能算 helper 失败。

## 如何比较性能

用 NATIVE-ALU-1 与非重采样的 BLIT-ROW-1 运行相同路线、相同输入。
OTHER-PROFILE-1 的边界采样有可观额外开销，不作为速度基线。
比较相同阶段的 `elapsed`、帧间隔、`other` 和最大按键采样间隔；
不要把不同游戏进度的整段日志直接视为加速比。

`--profile-other` 仍可用于后续诊断，但这 13 个 helper 的成功快速路径不再
经过 C profiler；它们会计入相邻原生边界的间隔。RMW 回退仍正常被计数。
因此新旧 `helper_calls` 不能直接用来推算性能提升。
