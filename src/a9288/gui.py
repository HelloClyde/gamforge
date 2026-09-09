"""Local Windows desktop frontend for the actual C6502 -> S1C33 compiler."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from a9288.app_options import default_app_name, encode_app_name, icon_images, inspect_game
from a9288.cli import DEFAULT_SDK, DEFAULT_TOOLCHAIN
from a9288.compiler.boot import DEFAULT_ROM8, DEFAULT_ROME, bundled_helper
from a9288.paths import USER_DATA, WORK, child_environment, dependency_setting, task_command

SETTINGS = USER_DATA / "settings.json"
BG = "#f3f6fb"
INK = "#182a40"
MUTED = "#66758b"
BLUE = "#2563eb"


def python_console() -> str:
    path = Path(sys.executable)
    return str(path.with_name("python.exe")) if path.name.lower() == "pythonw.exe" else str(path)


@dataclass(frozen=True)
class Conversion:
    game: Path
    name: str
    icon: Path | None
    output: Path
    sdk: Path
    toolchain: Path
    rom8: Path = DEFAULT_ROM8
    rome: Path = DEFAULT_ROME
    external_resources: bool = False

    def validate(self):
        inspect_game(self.game)
        encode_app_name(self.name)
        if self.output.suffix.lower() != ".exe":
            raise ValueError("输出文件必须以 .exe 结尾。")
        if self.output.resolve() == self.game.resolve():
            raise ValueError("不能覆盖原始 GAM。")
        if not (self.sdk / "Down_Include").is_dir():
            raise ValueError("找不到 9288 SDK 的 Down_Include，请在「编译环境」中配置。")
        for name in ("clang", "llvm-objcopy", "ld.lld", "llvm-readelf"):
            if not any(
                (self.toolchain / p).is_file()
                for p in (name + ".exe", "bin/" + name + ".exe", name, "bin/" + name)
            ):
                raise ValueError(f"工具链缺少 {name}，请检查编译环境路径。")
        for path in (self.rom8, self.rome):
            if not path.is_file() or path.stat().st_size != 2 * 1024 * 1024:
                raise ValueError(f"请在「编译环境」中配置用户自备的 2 MiB 固件：{path.name}")
        if not bundled_helper().is_file() and not shutil.which("gcc"):
            raise ValueError("源码版需要 PC gcc；分发版自带启动状态生成工具。")
        icon_images(self.icon)

    def command(self, work: Path) -> list[str]:
        command = task_command(
            "cli",
            str(self.game),
            "--app-name",
            self.name,
            "--output",
            str(self.output),
            "--sdk",
            str(self.sdk),
            "--toolchain",
            str(self.toolchain),
            "--work-dir",
            str(work),
            "--rom8",
            str(self.rom8),
            "--rome",
            str(self.rome),
        )
        if self.icon:
            command += ["--icon", str(self.icon)]
        if self.external_resources:
            command.append("--external-resources")
        return command


class ConversionWorker:
    def __init__(self, events: queue.Queue):
        self.events = events
        self.cancelled = threading.Event()
        self.process = None
        self.lock = threading.Lock()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=20,
                )
            else:
                process.terminate()

    def run(self, config: Conversion):
        work = None
        try:
            config.validate()
            base = WORK / "jobs"
            base.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix="job-", dir=base))
            self.events.put(("logpath", str(work / "conversion.log")))
            if self.cancelled.is_set():
                self.events.put(("cancelled", None))
                return
            env = child_environment()
            with (work / "conversion.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    config.command(work),
                    cwd=work,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                with self.lock:
                    self.process = process
                if self.cancelled.is_set():
                    self.cancel()
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    self.events.put(("line", line))
                process.stdout.close()
                code = process.wait()
            if self.cancelled.is_set():
                self.events.put(("cancelled", None))
                return
            if code:
                raise RuntimeError(
                    f"编译器返回错误 {code}。请查看下方日志末尾；未生成新的有效 EXE。"
                )
            report = json.loads(
                config.output.with_suffix(".report.json").read_text(encoding="utf-8")
            )
            actual = hashlib.sha256(config.output.read_bytes()).hexdigest()
            if report.get("output_kf2_sha256") != actual:
                raise RuntimeError("输出校验失败，EXE 与转换报告不一致。")
            self.events.put(("success", report))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            with self.lock:
                self.process = None


class ConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("GAMForge · GAM 原生重编译器")
        root.configure(bg=BG)
        root.geometry("1120x900")
        root.minsize(980, 860)
        self.events = queue.Queue()
        self.worker = None
        self.running = False
        self.last_output = None
        self.log_path = None
        self.icon_path = None
        self.close_after_stop = False
        self.start_time = 0
        self.saved_states = []
        self.auto_output = True
        self.setting_output = False
        self.game = tk.StringVar()
        self.name = tk.StringVar()
        self.output = tk.StringVar()
        settings = {}
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.sdk = tk.StringVar(value=dependency_setting(settings.get("sdk"), DEFAULT_SDK))
        self.toolchain = tk.StringVar(
            value=dependency_setting(settings.get("toolchain"), DEFAULT_TOOLCHAIN)
        )
        self.rom8 = tk.StringVar(value=dependency_setting(settings.get("rom8"), DEFAULT_ROM8))
        self.rome = tk.StringVar(value=dependency_setting(settings.get("rome"), DEFAULT_ROME))
        self.external_resources = tk.BooleanVar(
            value=bool(settings.get("external_resources", False))
        )
        self.inputs = []
        self._style()
        self._layout()
        self._preview()
        self.name.trace_add("write", lambda *_: self._name_changed())
        self.output.trace_add("write", lambda *_: self._output_changed())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self.drain)

    def _style(self):
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TButton", padding=(14, 8), background="#eaf0f9", foreground=INK, borderwidth=0
        )
        style.map("TButton", background=[("active", "#dce7f8")])
        style.configure(
            "Accent.TButton",
            background=BLUE,
            foreground="white",
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", "#cad5e8"), ("active", "#1d4ed8")],
            foreground=[("disabled", "#74839b")],
        )
        style.configure("TEntry", padding=7, fieldbackground="white", bordercolor="#dce3ed")
        style.configure(
            "Horizontal.TProgressbar", background=BLUE, troughcolor="#e9eef6", borderwidth=0
        )

    def label(self, parent, text="", size=10, color=INK, bold=False, **kwargs):
        return tk.Label(
            parent,
            text=text,
            bg=parent.cget("bg"),
            fg=color,
            font=("Microsoft YaHei UI", size, "bold" if bold else "normal"),
            **kwargs,
        )

    def card(self, parent):
        return tk.Frame(
            parent,
            bg="white",
            highlightbackground="#e0e7f0",
            highlightthickness=1,
            padx=22,
            pady=18,
        )

    def button(self, parent, text, command, **kwargs):
        widget = ttk.Button(parent, text=text, command=command, **kwargs)
        self.inputs.append(widget)
        return widget

    def _layout(self):
        shell = tk.Frame(self.root, bg=BG, padx=28, pady=20)
        shell.pack(fill="both", expand=True)
        head = tk.Frame(shell, bg=BG)
        head.pack(fill="x", pady=(0, 18))
        self.label(head, "GAMForge", 23, bold=True).pack(side="left")
        self.label(head, "A 系列 GAM  →  BBK 9288 原生程序", 10, color=MUTED).pack(
            side="right", pady=9
        )
        content = tk.Frame(shell, bg=BG)
        content.pack(fill="x")
        content.columnconfigure(0, weight=1)
        left = self.card(content)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)
        self.label(left, "01   选择游戏", 12, bold=True).grid(row=0, column=0, sticky="w")
        self.button(left, "选择 GAM…", self.choose_game).grid(row=0, column=1, sticky="e")
        file_entry = ttk.Entry(left, textvariable=self.game, state="readonly")
        file_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 7))
        self.inputs.append(file_entry)
        self.game_info = self.label(
            left,
            "支持 A 系列 C6502 GAM。原文件不会被修改。",
            9,
            color=MUTED,
            anchor="w",
            justify="left",
        )
        self.game_info.grid(row=2, column=0, columnspan=2, sticky="w")
        self.label(left, "02   程序名称", 12, bold=True).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(21, 8)
        )
        entry = ttk.Entry(left, textvariable=self.name)
        entry.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.inputs.append(entry)
        self.name_hint = self.label(
            left, "写入 9288 桌面名称和窗口标题，最多 15 个 GBK 字节。", 9, color=MUTED
        )
        self.name_hint.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.label(left, "03   输出文件", 12, bold=True).grid(
            row=6, column=0, sticky="w", pady=(21, 8)
        )
        self.button(left, "另存为…", self.choose_output).grid(
            row=6, column=1, sticky="e", pady=(15, 5)
        )
        entry = ttk.Entry(left, textvariable=self.output)
        entry.grid(row=7, column=0, columnspan=2, sticky="ew")
        self.inputs.append(entry)
        self.label(
            left, "桌面名称取 EXE 文件名；分类为「娱乐」。附带报告、ELF、MAP。", 9, color=MUTED
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(7, 0))
        mode = ttk.Checkbutton(
            left, text="EXE＋外置资源文件（大游戏，按需缓存）", variable=self.external_resources
        )
        mode.grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.inputs.append(mode)
        self.label(left, "EXE 放 A:\\系统\\程序；RES 放 A:\\系统\\数据。", 9, color=MUTED).grid(
            row=10, column=0, columnspan=2, sticky="w"
        )

        right = self.card(content)
        right.grid(row=0, column=1, sticky="nsew")
        right.configure(width=285)
        self.label(right, "9288 桌面预览", 12, bold=True).pack(anchor="w")
        self.large = tk.Label(right, bg="white")
        self.large.pack(pady=(17, 5))
        self.preview_name = self.label(right, "程序名称", 11, bold=True)
        self.preview_name.pack()
        smallrow = tk.Frame(right, bg="white")
        smallrow.pack(pady=(13, 8))
        self.small = tk.Label(smallrow, bg="white")
        self.small.pack(side="left", padx=(0, 10))
        self.label(
            smallrow, "40 × 40 / 16 × 16\n四灰阶 · 保留系统边框", 9, color=MUTED, justify="left"
        ).pack(side="left")
        controls = tk.Frame(right, bg="white")
        controls.pack(fill="x", pady=(10, 0))
        self.button(controls, "替换图标…", self.choose_icon).pack(side="left", padx=(0, 6))
        self.button(controls, "默认", self.reset_icon).pack(side="left")
        self.icon_label = self.label(right, "使用默认图标", 9, color=MUTED, wraplength=230)
        self.icon_label.pack(pady=(8, 0))

        envhead = tk.Frame(shell, bg=BG)
        envhead.pack(fill="x", pady=(10, 5))
        self.env_button = ttk.Button(envhead, text="编译环境…", command=self.toggle_environment)
        self.env_button.pack(side="left")
        self.label(envhead, "使用 9288 SDK 和当前工程工具链，不上传文件。", 9, color=MUTED).pack(
            side="left", padx=12
        )
        self.env_window = tk.Toplevel(self.root)
        self.env_window.withdraw()
        self.env_window.title("编译环境 · GAMForge")
        self.env_window.geometry("920x330")
        self.env_window.minsize(740, 310)
        self.env_window.transient(self.root)
        self.env_window.protocol("WM_DELETE_WINDOW", self.env_window.withdraw)
        self.env = self.card(self.env_window)
        self.env.pack(fill="both", expand=True)
        self.env.columnconfigure(1, weight=1)
        for i, (label, var) in enumerate(
            (
                ("9288 SDK", self.sdk),
                ("S1C33 工具链", self.toolchain),
                ("A 系列 8.BIN", self.rom8),
                ("A 系列 E.BIN", self.rome),
            )
        ):
            self.label(self.env, label, 9).grid(row=i, column=0, sticky="w", padx=(0, 10))
            item = ttk.Entry(self.env, textvariable=var)
            item.grid(row=i, column=1, sticky="ew", pady=3)
            self.inputs.append(item)
            self.button(
                self.env, "浏览…", lambda v=var, f=i >= 2: self.choose_dependency(v, f)
            ).grid(row=i, column=2, padx=(8, 0))
        self.label(
            self.env, "SDK 和固件由用户自行提供；不会上传。工具链 ABI 自动校验。", 9, color=MUTED
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(self.env, text="完成", command=self.env_window.withdraw).grid(row=4, column=2)

        action = self.card(shell)
        action.pack(fill="x", pady=(7, 10))
        bar = tk.Frame(action, bg="white")
        bar.pack(fill="x")
        self.status = self.label(bar, "准备就绪", 12, bold=True)
        self.status.pack(side="left")
        self.elapsed = self.label(bar, "", 9, color=MUTED)
        self.elapsed.pack(side="right")
        self.detail = self.label(
            action,
            "选择一个 GAM，确认名称和图标后开始转换。",
            9,
            color=MUTED,
            anchor="w",
            justify="left",
            wraplength=990,
        )
        self.detail.pack(fill="x", pady=(5, 9))
        self.progress = ttk.Progressbar(action, mode="indeterminate")
        self.progress.pack(fill="x")
        row = tk.Frame(action, bg="white")
        row.pack(fill="x", pady=(12, 0))
        self.convert_button = ttk.Button(
            row,
            text="一键转换为 9288 EXE",
            style="Accent.TButton",
            command=self.convert,
            state="disabled",
        )
        self.convert_button.pack(side="left")
        self.cancel_button = ttk.Button(row, text="取消转换", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.folder_button = ttk.Button(
            row, text="打开输出目录", command=self.open_output, state="disabled"
        )
        self.folder_button.pack(side="right")
        self.log_button = ttk.Button(row, text="打开日志", command=self.open_log, state="disabled")
        self.log_button.pack(side="right", padx=8)

        self.label(shell, "转换日志", 10, bold=True).pack(anchor="w", pady=(0, 5))
        logframe = tk.Frame(shell, bg=BG)
        logframe.pack(fill="both", expand=True)
        self.log = tk.Text(
            logframe,
            height=7,
            bg="#142238",
            fg="#cbd9ee",
            insertbackground="white",
            relief="flat",
            font=("Consolas", 9),
            padx=12,
            pady=9,
            state="disabled",
            wrap="word",
        )
        self.log.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(logframe, command=self.log.yview)
        scroll.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scroll.set)
        self.label(
            shell,
            "输出 EXE 运行于 9288，不是 Windows 程序。编译成功不代表所有游戏功能都已验证。",
            9,
            color=MUTED,
        ).pack(anchor="w", pady=(9, 0))

    def choose_game(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择 A 系列 GAM",
            filetypes=[("GAM 游戏", "*.gam"), ("所有文件", "*.*")],
        )
        if path:
            self.load_game(Path(path))

    def load_game(self, path: Path):
        try:
            info = inspect_game(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法读取游戏", str(exc), parent=self.root)
            return
        self.auto_output = True
        self.game.set(str(path.resolve()))
        self.name.set(default_app_name(path.stem))
        self.game_info.configure(
            text=f"文件 {info['size'] / 1024:.1f} KiB  ·  头部代码段 {info['code_size'] / 1024:.1f} KiB  ·  入口 ${info['entry']:04X}\n游戏标题：{info['title'] or '未提供'}"
        )
        self.status.configure(text="待转换", fg=INK)
        self.detail.configure(text="可修改名称、替换图标或选择其他输出位置。")
        self.convert_button.configure(state="normal")
        self._name_changed()

    def choose_output(self):
        current = Path(self.output.get()) if self.output.get() else WORK / "converted/game.exe"
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="保存 9288 EXE",
            defaultextension=".exe",
            initialfile=current.name,
            initialdir=str(current.parent) if current.parent.exists() else str(Path.home()),
            filetypes=[("9288 EXE", "*.exe")],
        )
        if path:
            self.output.set(path)

    def choose_dependency(self, var, file=False):
        if file:
            path = filedialog.askopenfilename(
                parent=self.env_window, title="选择 A 系列固件", filetypes=[("固件", "*.bin *.BIN")]
            )
        else:
            path = filedialog.askdirectory(
                parent=self.env_window, title="选择编译依赖目录", initialdir=var.get()
            )
        if path:
            var.set(path)

    def choose_icon(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择程序图标",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.ico *.webp"), ("所有文件", "*.*")],
        )
        if not path:
            return
        previous = self.icon_path
        self.icon_path = Path(path)
        try:
            self._preview()
        except Exception as exc:
            self.icon_path = previous
            messagebox.showerror("无法读取图标", str(exc), parent=self.root)

    def reset_icon(self):
        self.icon_path = None
        self._preview()

    def _preview(self):
        big, small = icon_images(self.icon_path)
        self.big_photo = ImageTk.PhotoImage(big.resize((160, 160), Image.Resampling.NEAREST))
        self.small_photo = ImageTk.PhotoImage(small.resize((32, 32), Image.Resampling.NEAREST))
        self.large.configure(image=self.big_photo)
        self.small.configure(image=self.small_photo)
        self.icon_label.configure(text=self.icon_path.name if self.icon_path else "使用默认图标")

    def _name_changed(self):
        preview = self.name.get() or "程序名称"
        self.preview_name.configure(text=preview if len(preview) <= 15 else preview[:15] + "…")
        try:
            size = len(encode_app_name(self.name.get()))
            self.name_hint.configure(text=f"{size} / 15 GBK 字节 · 将写入 EXE 内部名称", fg=MUTED)
            if self.auto_output and self.game.get():
                stem = "".join(
                    "_" if c in '<>:"/\\|?*' else c for c in self.name.get().strip()
                ).rstrip(". ")
                if stem.upper().split(".")[0] in {
                    "CON",
                    "PRN",
                    "AUX",
                    "NUL",
                    *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10)),
                }:
                    stem = "_" + stem
                self.setting_output = True
                try:
                    self.output.set(str(WORK / "converted" / ((stem or "GAM") + ".exe")))
                finally:
                    self.setting_output = False
        except ValueError as exc:
            self.name_hint.configure(text=str(exc), fg="#b42318")

    def _output_changed(self):
        if not self.setting_output:
            self.auto_output = False

    def toggle_environment(self):
        if self.env_window.state() == "withdrawn":
            self.env_window.deiconify()
            self.env_window.lift()
        else:
            self.env_window.withdraw()

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        if int(self.log.index("end-1c").split(".")[0]) > 1500:
            self.log.delete("1.0", "300.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def convert(self):
        if self.running:
            return
        try:
            config = Conversion(
                Path(self.game.get()),
                self.name.get().strip(),
                self.icon_path,
                Path(self.output.get()).resolve(),
                Path(self.sdk.get()).resolve(),
                Path(self.toolchain.get()).resolve(),
                Path(self.rom8.get()).resolve(),
                Path(self.rome.get()).resolve(),
                external_resources=self.external_resources.get(),
            )
            config.validate()
        except Exception as exc:
            messagebox.showerror("暂时无法转换", str(exc), parent=self.root)
            return
        if config.output.exists() and not messagebox.askyesno(
            "替换已有文件？",
            f"{config.output}\n\n转换成功后才替换现有 EXE 和同名编译报告。",
            parent=self.root,
        ):
            return
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(
                json.dumps(
                    dict(
                        sdk=self.sdk.get(),
                        toolchain=self.toolchain.get(),
                        rom8=self.rom8.get(),
                        rome=self.rome.get(),
                        external_resources=self.external_resources.get(),
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            messagebox.showerror("无法保存编译设置", str(exc), parent=self.root)
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.running = True
        self.start_time = time.monotonic()
        self.last_output = None
        self.saved_states = [(w, str(w.cget("state"))) for w in self.inputs]
        for w, _ in self.saved_states:
            w.configure(state="disabled")
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.folder_button.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status.configure(text="正在转换", fg=BLUE)
        self.detail.configure(text="检查输入文件与编译环境…")
        self.worker = ConversionWorker(self.events)
        threading.Thread(target=self.worker.run, args=(config,), daemon=True).start()

    def cancel(self):
        if self.worker and self.running:
            self.cancel_button.configure(state="disabled")
            self.detail.configure(text="正在停止本次编译及其子进程…")
            threading.Thread(target=self.worker.cancel, daemon=True).start()

    def finish(self):
        self.running = False
        self.progress.stop()
        self.cancel_button.configure(state="disabled")
        for widget, state in self.saved_states:
            widget.configure(state=state)
        self.convert_button.configure(state="normal" if self.game.get() else "disabled")
        if self.close_after_stop:
            self.root.destroy()

    def drain(self):
        for _ in range(250):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self.append_log(data)
                if data.startswith("[GAM9288_STAGE] "):
                    self.detail.configure(text=data.split("|", 1)[-1].strip())
            elif kind == "logpath":
                self.log_path = Path(data)
                self.log_button.configure(state="normal")
            elif kind == "success":
                self.finish()
                if self.close_after_stop:
                    return
                self.last_output = Path(data["output_kf2"])
                self.status.configure(text="转换完成", fg="#15803d")
                self.detail.configure(
                    text=f"{self.last_output.name} · {data['output_kf2_bytes'] / 1024:.1f} KiB · 校验通过\n"
                    + (
                        f"请安装 {data['resource_file']} 到 A:\\系统\\数据"
                        if data.get("external_resources")
                        else str(self.last_output)
                    )
                )
                self.progress.configure(mode="determinate", value=100)
                self.folder_button.configure(state="normal")
            elif kind in ("error", "cancelled"):
                self.finish()
                if self.close_after_stop:
                    return
                self.status.configure(
                    text="转换失败" if kind == "error" else "已取消",
                    fg="#b42318" if kind == "error" else MUTED,
                )
                self.progress.configure(mode="determinate", value=0)
                self.detail.configure(
                    text=data or "已停止本次任务。之前的 EXE 不会被未完成的编译覆盖。"
                )
                if data:
                    self.append_log("\n" + data + "\n")
        if self.running:
            self.elapsed.configure(text=f"已用时 {time.monotonic() - self.start_time:.0f} 秒")
        if not self.close_after_stop or self.running:
            self.root.after(80, self.drain)

    def open_output(self):
        if self.last_output:
            os.startfile(str(self.last_output.parent))

    def open_log(self):
        if self.log_path and self.log_path.exists():
            os.startfile(str(self.log_path))

    def close(self):
        if self.running:
            if messagebox.askyesno(
                "停止转换并关闭？", "当前转换还没有完成。是否停止编译后关闭窗口？", parent=self.root
            ):
                self.close_after_stop = True
                self.cancel()
        else:
            self.root.destroy()


def main():
    if os.name == "nt":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    app = ConverterApp(root)
    if len(sys.argv) > 1:
        app.load_game(Path(sys.argv[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
