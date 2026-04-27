from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from sc2_replay_version_modifier import (
    batch_patch_replays,
    read_replay_metadata,
    version_info_from_metadata,
)


class ReplayVersionModifierApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SC2录像版本号修改器")
        self.geometry("820x560")
        self.minsize(720, 500)

        self.target_replay = tk.StringVar()
        self.old_replay_folder = tk.StringVar()
        self.target_info = tk.StringVar(value="请选择一份新版本录像作为目标版本")
        self.status = tk.StringVar(value="Ready")
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_ui()
        self.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=(18, 16, 18, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text="SC2录像版本号修改器", font=("Microsoft YaHei UI", 18, "bold"))
        title.grid(row=0, column=0, sticky="w")
        subtitle = ttk.Label(
            header,
            text="选择一份新录像，批量把旧录像伪装到同一 build。不会覆盖原文件。",
            foreground="#4b5563",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        form = ttk.Frame(self, padding=(18, 8, 18, 12))
        form.grid(row=1, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="新版本录像").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.target_replay).grid(row=0, column=1, sticky="ew", padx=(10, 8))
        ttk.Button(form, text="选择录像", command=self._choose_target_replay).grid(row=0, column=2, sticky="e")

        ttk.Label(form, text="旧录像文件夹").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.old_replay_folder).grid(row=1, column=1, sticky="ew", padx=(10, 8))
        ttk.Button(form, text="选择文件夹", command=self._choose_old_folder).grid(row=1, column=2, sticky="e")

        info = ttk.Label(form, textvariable=self.target_info, foreground="#2563eb")
        info.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 2))

        actions = ttk.Frame(form)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        self.run_button = ttk.Button(actions, text="开始批量处理", command=self._start_patch)
        self.run_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Button(actions, text="打开输出文件夹", command=self._open_output_folder).grid(row=0, column=2, padx=(8, 0))

        log_frame = ttk.Frame(self, padding=(18, 0, 18, 8))
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log = tk.Text(log_frame, wrap="word", height=14, state="disabled", bg="#f8fafc", relief="solid", bd=1)
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(self, padding=(18, 0, 18, 14))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status, foreground="#4b5563").grid(row=0, column=0, sticky="w")

    def _choose_target_replay(self) -> None:
        path = filedialog.askopenfilename(
            title="选择新版本录像",
            filetypes=[("SC2 Replay", "*.SC2Replay"), ("All files", "*.*")],
        )
        if not path:
            return
        self.target_replay.set(path)
        try:
            _, _, metadata = read_replay_metadata(Path(path))
            target = version_info_from_metadata(metadata)
            self.target_info.set(
                f"目标版本: {target.game_version} | Build {target.data_build} | DataVersion {target.data_version}"
            )
            self._write_log(f"已读取新录像: {path}")
            self._write_log(f"目标 build: {target.data_build}")
        except Exception as exc:
            self.target_info.set("无法读取这份录像的版本信息")
            messagebox.showerror("读取失败", str(exc))

    def _choose_old_folder(self) -> None:
        path = filedialog.askdirectory(title="选择旧录像文件夹")
        if path:
            self.old_replay_folder.set(path)
            self._write_log(f"旧录像文件夹: {path}")

    def _start_patch(self) -> None:
        target_path = Path(self.target_replay.get().strip())
        old_folder = Path(self.old_replay_folder.get().strip())

        if not target_path.is_file():
            messagebox.showwarning("缺少新录像", "请先选择一份新版本录像。")
            return
        if not old_folder.is_dir():
            messagebox.showwarning("缺少旧录像文件夹", "请先选择旧录像文件夹。")
            return
        if self.worker and self.worker.is_alive():
            return

        self.run_button.configure(state="disabled")
        self.status.set("Processing...")
        self._clear_log()
        self.worker = threading.Thread(target=self._patch_worker, args=(target_path, old_folder), daemon=True)
        self.worker.start()

    def _patch_worker(self, target_path: Path, old_folder: Path) -> None:
        try:
            _, _, metadata = read_replay_metadata(target_path)
            target = version_info_from_metadata(metadata)
            self.log_queue.put(f"目标录像: {target_path}")
            self.log_queue.put(f"目标版本: {target.game_version} / build {target.data_build}")
            self.log_queue.put(f"开始扫描: {old_folder}")

            results = batch_patch_replays([old_folder], target=target, target_replay=target_path)
            success = 0
            failed = 0
            if not results:
                self.log_queue.put("没有找到需要处理的旧录像。")
            for source, output, error in results:
                if error is None and output is not None:
                    success += 1
                    self.log_queue.put(f"成功: {source.name} -> {output.name}")
                else:
                    failed += 1
                    self.log_queue.put(f"跳过: {source.name} ({error})")
            self.log_queue.put(f"完成: 成功 {success} 个，跳过/失败 {failed} 个。")
            self.log_queue.put("__DONE__")
        except Exception as exc:
            self.log_queue.put(f"错误: {exc}")
            self.log_queue.put("__DONE__")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                if message == "__DONE__":
                    self.status.set("Done")
                    self.run_button.configure(state="normal")
                else:
                    self._write_log(message)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _write_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _open_output_folder(self) -> None:
        folder = self.old_replay_folder.get().strip()
        if not folder:
            return
        if Path(folder).is_dir():
            os.startfile(folder)


def main() -> None:
    app = ReplayVersionModifierApp()
    app.mainloop()


if __name__ == "__main__":
    main()
