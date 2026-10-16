# S1C33 / 9288 GNU33 工具链

本项目需要 `clang`、`ld.lld`、`llvm-objcopy`、`llvm-readelf`。
普通 LLVM 没有 S1C33 后端，未修正的 P/ECE ABI 也不能直接用于 9288。

上游：<https://github.com/autch/llvm-s1c33>。
固定源代码提交和 ABI 说明见 `manifest.json`，补丁在 `9288-gnu33-abi.patch`。
构建后执行参数寄存器/返回值/delay-slot 探针，再用安装后的四个工具实际编译两个
S1C33 对象、链接 ELF、读取符号表、导出二进制，不只是检查编译器名字。

## GitHub Actions

手动运行 **Build S1C33 toolchain**（也可用 `workflow_call`）。三个独立原生 runner
分别构建 Windows x64、Apple Silicon 和 Intel Mac 工具链；不会把 Windows EXE 放进 Mac 包。
它们使用相同固定提交和 ABI 补丁，完成探针后，校验 ZIP 的 SHA256，重新解压再测试。
这属于大型 LLVM 构建，不在每次 GUI 提交时重复执行；首次应预留数十分钟至数小时，
具体时间以 runner 实测为准，workflow 上限 240 分钟，不是性能承诺。
后续 CI 可复用按宿主/源码/补丁/构建脚本隔离的工具缓存；命中后仍校验各文件哈希并重新运行原生探针。
下载 artifact 后解压，在转换器的“编译环境”中选择含 `bin` 的目录。

| 宿主 | Runner | ZIP |
| --- | --- | --- |
| Windows x64 | `windows-2022` | `s1c33-9288-toolchain-windows-x64.zip` |
| macOS Apple Silicon | `macos-15` | `s1c33-9288-toolchain-macos-arm64.zip` |
| macOS Intel | `macos-15-intel` | `s1c33-9288-toolchain-macos-x86_64.zip` |

每个 ZIP 旁有同名 `.sha256`。Mac 两包不是通用二进制；选择与宿主 CPU 一致的包。
runner 标签/架构以 [GitHub 官方说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
为依据，不能再假定 `macos-latest` 是 Intel。

## 本地

安装 MSVC x64、CMake、Ninja、Git 和本项目 Python 环境，在 VS x64 开发环境执行：

```shell
python scripts/build_toolchain.py --jobs 2
```

Mac 开发者需安装 Xcode Command Line Tools、CMake 3.20+（CI 固定 `<4`）、Ninja、Git
及本项目 Python 环境，然后同样运行上述命令。脚本明确使用 `/usr/bin/clang{,++}`、
Apple libc++、当前宿主架构和 `CMAKE_OSX_DEPLOYMENT_TARGET=11.0`，不依赖 Homebrew LLVM。
可用 `--deployment-target 12.0` 等提高最低版本，不支持低于 11.0。
固定上游为 LLVM 22.1.1，要求 C++17，源码声明 AppleClang 最低 10；这只是源码要求，
不能替代实际 Mac 构建。尚未通过对应 Mac runner 的产物不能称为已验证发行包。

脚本在 `build/toolchain/source` 和 `build/toolchain/build-<宿主>` 创建专用工作目录，
不会重置现有 LLVM checkout。源代码必须保持固定提交，不匹配会中止。
输出是 `dist/s1c33-9288-toolchain-<宿主>/` 和对应 ZIP；Windows 同时保留历史
`dist/s1c33-9288-toolchain.zip` 文件名供已有本地脚本使用。
分发时保留上游许可证、固定提交、补丁和 manifest。
9288 SDK 是独立依赖，不包含在这个工具链 ZIP 中。

```shell
# 已有产物需同时匹配源码、补丁、脚本、宿主和所有文件哈希；仍重新跑 ABI/链接探针。
python scripts/build_toolchain.py --jobs 2 --reuse
# 无需重新构建 LLVM，独立检查下载/解压后的工具链。
python scripts/build_toolchain.py --verify-only dist/s1c33-9288-toolchain-macos-arm64
```

Mac ZIP 保留可执行位，`ld.lld` 和 `llvm-readelf` 是正确命名的独立文件，不是会丢失
`argv[0]` 语义的 shell wrapper。前者必须选择 ELF 而非 macOS Mach-O 链接模式；后者
必须使用 GNU readelf 符号表格式。验证还检查 Mach-O 宿主架构及动态库依赖，拒绝
Homebrew/build-tree 路径。工具仍然输出 BBK 的 S1C33 代码，不是运行游戏的 Mac 模拟器。

## 帧地址展开与 PSR 依赖

`9288-gnu33-abi.patch` 也修正 `ADJFI` 的 `Uses = [SP]` / `Defs = [PSR]`。
该伪指令在调度后展开成 `LD SP + ADD`，ADD 会改变比较标志；不声明这个依赖，
就可能生成 `CMP → ADD → 条件跳转`，让绘图对齐等判断走错分支。

转换器同时在 C → 汇编 → 对象文件之间保护已识别的帧地址展开，兼容既有工具链。
因此源码更新后重新转换游戏即可使用修复，不要求用户先重建 LLVM；
现有 EXE 不会自动修复，旧的发布包也不会因此自动更新。
根因、验证方法和边界见 [代码生成正确性记录](../docs/compiler-correctness.md)。
