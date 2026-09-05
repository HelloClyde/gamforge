# S1C33 / 9288 GNU33 工具链

本项目需要 `clang`、`ld.lld`、`llvm-objcopy`、`llvm-readelf`。
普通 LLVM 没有 S1C33 后端，未修正的 P/ECE ABI 也不能直接用于 9288。

上游：<https://github.com/autch/llvm-s1c33>。
固定源代码提交和 ABI 说明见 `manifest.json`，补丁在 `9288-gnu33-abi.patch`。
构建后仍会执行参数寄存器/返回值/delay-slot 探针，不只是检查编译器名字。

## GitHub Actions

手动运行 **Build S1C33 toolchain**。它在 Windows x64 上用 MSVC / CMake / Ninja
构建固定提交、应用补丁，校验 ABI，产出独立的工具链 ZIP。
这是较重的构建，不在每次 GUI 提交时重复执行；首次可能耗时较长。
下载 artifact 后解压，在转换器的“编译环境”中选择含 `bin` 的目录。

## 本地

安装 MSVC x64、CMake、Ninja、Git 和本项目 Python 环境，在 VS x64 开发环境执行：

```shell
python scripts/build_toolchain.py --jobs 2
```

脚本只在项目 `build/toolchain` 下创建源代码与构建目录，不重置用户的现有 LLVM checkout。
输出为 `dist/s1c33-9288-toolchain.zip`。分发时保留上游许可证、固定提交和补丁。
9288 SDK 是独立依赖，不包含在这个工具链 ZIP 中。
