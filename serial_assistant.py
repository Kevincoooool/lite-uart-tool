"""
ESP32 轻量级串口助手 v1.0
专为 ESP-IDF 开发者设计，支持彩色日志、终端交互、多种发送模式
"""

import sys
import os
import re
import time
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, font as tkfont
from datetime import datetime
from collections import deque

import serial
import serial.tools.list_ports
import customtkinter as ctk

# ─── ANSI / ESP-IDF 日志颜色映射 ─────────────────────────────────────────────

ANSI_COLOR_MAP = {
    "30": "#4B5563",  # black / gray
    "31": "#EF4444",  # red     - ERROR
    "32": "#22C55E",  # green   - INFO
    "33": "#EAB308",  # yellow  - WARN
    "34": "#3B82F6",  # blue
    "35": "#A855F7",  # magenta - VERBOSE
    "36": "#06B6D4",  # cyan
    "37": "#F3F4F6",  # white
    "90": "#6B7280",  # bright black
    "91": "#F87171",  # bright red
    "92": "#4ADE80",  # bright green
    "93": "#FACC15",  # bright yellow
    "94": "#60A5FA",  # bright blue
    "95": "#C084FC",  # bright magenta
    "96": "#22D3EE",  # bright cyan
    "97": "#FFFFFF",  # bright white
}

ESP_LOG_COLORS = {
    "E": "#EF4444",   # ERROR  - 红色
    "W": "#F59E0B",   # WARN   - 橙黄
    "I": "#22C55E",   # INFO   - 绿色
    "D": "#3B82F6",   # DEBUG  - 蓝色
    "V": "#A855F7",   # VERBOSE- 紫色
}

ANSI_ESCAPE_RE = re.compile(r"\x1b\[([0-9;]*)m")
ESP_LOG_RE = re.compile(r"^([EWIDV])\s\((\d+)\)\s(.+?):\s(.*)$")

# ─── 配置持久化 ────────────────────────────────────────────────────────────────

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "port": "",
    "baudrate": 115200,
    "databits": 8,
    "stopbits": 1,
    "parity": "None",
    "font_family": "Consolas",
    "font_size": 11,
    "theme": "dark",
    "hex_display": False,
    "hex_send": False,
    "auto_scroll": True,
    "timestamp": False,
    "send_newline": True,
    "newline_type": "\\r\\n",
    "dtr": False,
    "rts": False,
    "cmd_history": [],
    "quick_cmds": [
        {"name": "重启", "cmd": "reboot"},
        {"name": "帮助", "cmd": "help"},
        {"name": "版本", "cmd": "version"},
        {"name": "WiFi扫描", "cmd": "wifi scan"},
    ],
}


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─── 主窗口 ──────────────────────────────────────────────────────────────────

class SerialAssistant(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()

        ctk.set_appearance_mode(self.cfg["theme"])
        ctk.set_default_color_theme("blue")

        self.title("ESP32 串口助手 v1.0 by Kevincoooool")
        self.geometry("1100x720")
        self.minsize(900, 600)

        self.serial_port = None
        self.is_connected = False
        self.rx_count = 0
        self.tx_count = 0
        self.read_thread = None
        self.running = False
        self.auto_send_running = False
        self.auto_send_thread = None
        self.cmd_history = deque(self.cfg.get("cmd_history", []), maxlen=50)
        self.cmd_history_idx = -1
        self.log_buffer = deque(maxlen=50000)
        self._pending_inserts = []
        self._flush_scheduled = False
        self._port_refresh_after_id = None
        self._last_port_values = None
        self._port_auto_refresh_interval_ms = int(self.cfg.get("port_auto_refresh_interval_ms", 1000))

        self._build_ui()
        self._apply_font_settings()
        self._refresh_ports()
        self._start_port_auto_refresh()
        self._restore_settings()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_clock()

    # ─── UI 构建 ──────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_main_area()
        self._build_send_area()
        self._build_statusbar()

    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self, height=46, corner_radius=0)
        toolbar.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        toolbar.grid_columnconfigure(20, weight=1)

        pad = {"padx": 4, "pady": 6}

        ctk.CTkLabel(toolbar, text="串口:", font=("Microsoft YaHei UI", 13)).grid(row=0, column=0, **pad)
        self.port_combo = ctk.CTkComboBox(toolbar, width=200, values=[], state="readonly")
        self.port_combo.grid(row=0, column=1, **pad)

        self.refresh_btn = ctk.CTkButton(toolbar, text="⟳", width=32, command=self._refresh_ports,
                                         font=("Segoe UI Symbol", 16))
        self.refresh_btn.grid(row=0, column=2, **pad)

        ctk.CTkLabel(toolbar, text="波特率:", font=("Microsoft YaHei UI", 13)).grid(row=0, column=3, **pad)
        self.baud_combo = ctk.CTkComboBox(
            toolbar, width=110,
            values=["9600", "19200", "38400", "57600", "74880", "115200", "230400", "460800", "921600", "1500000", "2000000"],
            state="readonly"
        )
        self.baud_combo.grid(row=0, column=4, **pad)
        self.baud_combo.set(str(self.cfg["baudrate"]))

        ctk.CTkLabel(toolbar, text="数据位:", font=("Microsoft YaHei UI", 13)).grid(row=0, column=5, **pad)
        self.databits_combo = ctk.CTkComboBox(toolbar, width=60, values=["5", "6", "7", "8"], state="readonly")
        self.databits_combo.grid(row=0, column=6, **pad)
        self.databits_combo.set(str(self.cfg["databits"]))

        ctk.CTkLabel(toolbar, text="停止位:", font=("Microsoft YaHei UI", 13)).grid(row=0, column=7, **pad)
        self.stopbits_combo = ctk.CTkComboBox(toolbar, width=60, values=["1", "1.5", "2"], state="readonly")
        self.stopbits_combo.grid(row=0, column=8, **pad)
        self.stopbits_combo.set(str(self.cfg["stopbits"]))

        ctk.CTkLabel(toolbar, text="校验:", font=("Microsoft YaHei UI", 13)).grid(row=0, column=9, **pad)
        self.parity_combo = ctk.CTkComboBox(toolbar, width=80, values=["None", "Even", "Odd", "Mark", "Space"],
                                            state="readonly")
        self.parity_combo.grid(row=0, column=10, **pad)
        self.parity_combo.set(self.cfg["parity"])

        spacer = ctk.CTkLabel(toolbar, text="")
        spacer.grid(row=0, column=20, sticky="ew")

        self.connect_btn = ctk.CTkButton(
            toolbar, text="打开串口", width=100, height=32,
            fg_color="#22C55E", hover_color="#16A34A",
            font=("Microsoft YaHei UI", 13, "bold"),
            command=self._toggle_connection
        )
        self.connect_btn.grid(row=0, column=21, padx=8, pady=6)

    def _build_main_area(self):
        main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=(4, 0))
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)

        recv_frame = ctk.CTkFrame(main_frame, corner_radius=8)
        recv_frame.grid(row=0, column=0, sticky="nsew")
        recv_frame.grid_columnconfigure(0, weight=1)
        recv_frame.grid_rowconfigure(1, weight=1)

        recv_toolbar = ctk.CTkFrame(recv_frame, height=36, corner_radius=0, fg_color="transparent")
        recv_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))

        ctk.CTkLabel(recv_toolbar, text="接收区", font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")

        self.auto_scroll_var = ctk.BooleanVar(value=self.cfg["auto_scroll"])
        ctk.CTkCheckBox(recv_toolbar, text="自动滚动", variable=self.auto_scroll_var,
                        font=("Microsoft YaHei UI", 12), width=90, checkbox_width=18, checkbox_height=18
                        ).pack(side="left", padx=(16, 4))

        self.timestamp_var = ctk.BooleanVar(value=self.cfg["timestamp"])
        ctk.CTkCheckBox(recv_toolbar, text="时间戳", variable=self.timestamp_var,
                        font=("Microsoft YaHei UI", 12), width=80, checkbox_width=18, checkbox_height=18
                        ).pack(side="left", padx=4)

        self.hex_display_var = ctk.BooleanVar(value=self.cfg["hex_display"])
        ctk.CTkCheckBox(recv_toolbar, text="HEX显示", variable=self.hex_display_var,
                        font=("Microsoft YaHei UI", 12), width=90, checkbox_width=18, checkbox_height=18
                        ).pack(side="left", padx=4)

        self.dtr_var = ctk.BooleanVar(value=self.cfg["dtr"])
        ctk.CTkCheckBox(recv_toolbar, text="DTR", variable=self.dtr_var,
                        font=("Microsoft YaHei UI", 12), width=55, checkbox_width=18, checkbox_height=18,
                        command=self._on_dtr_rts_change
                        ).pack(side="left", padx=4)

        self.rts_var = ctk.BooleanVar(value=self.cfg["rts"])
        ctk.CTkCheckBox(recv_toolbar, text="RTS", variable=self.rts_var,
                        font=("Microsoft YaHei UI", 12), width=55, checkbox_width=18, checkbox_height=18,
                        command=self._on_dtr_rts_change
                        ).pack(side="left", padx=4)

        ctk.CTkLabel(recv_toolbar, text="字体:", font=("Microsoft YaHei UI", 12)).pack(side="left", padx=(16, 2))
        self.font_family_combo = ctk.CTkComboBox(
            recv_toolbar, width=130,
            values=["Consolas", "Courier New", "Cascadia Code", "JetBrains Mono", "Fira Code",
                    "Source Code Pro", "Monaco", "Lucida Console", "Microsoft YaHei UI"],
            state="readonly", command=self._on_font_change
        )
        self.font_family_combo.pack(side="left", padx=2)
        self.font_family_combo.set(self.cfg["font_family"])

        self.font_size_var = ctk.IntVar(value=self.cfg["font_size"])
        ctk.CTkLabel(recv_toolbar, text="大小:", font=("Microsoft YaHei UI", 12)).pack(side="left", padx=(8, 2))
        font_size_spin = ctk.CTkComboBox(
            recv_toolbar, width=60,
            values=["8", "9", "10", "11", "12", "13", "14", "16", "18", "20", "22", "24"],
            state="readonly", command=self._on_font_size_change
        )
        font_size_spin.pack(side="left", padx=2)
        font_size_spin.set(str(self.cfg["font_size"]))
        self.font_size_combo = font_size_spin

        ctk.CTkButton(recv_toolbar, text="清屏", width=56, height=28,
                      fg_color="#6B7280", hover_color="#4B5563",
                      command=self._clear_recv).pack(side="right", padx=4)
        ctk.CTkButton(recv_toolbar, text="保存", width=56, height=28,
                      fg_color="#6B7280", hover_color="#4B5563",
                      command=self._save_log).pack(side="right", padx=4)

        text_frame = ctk.CTkFrame(recv_frame, corner_radius=6, fg_color="#1E1E2E")
        text_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        text_frame.grid_columnconfigure(0, weight=1)
        text_frame.grid_rowconfigure(0, weight=1)

        self.recv_text = tk.Text(
            text_frame, wrap="none",
            bg="#1E1E2E", fg="#CDD6F4", insertbackground="#CDD6F4",
            selectbackground="#45475A", selectforeground="#CDD6F4",
            relief="flat", borderwidth=0, padx=8, pady=6,
            undo=False, maxundo=0
        )
        self.recv_text.grid(row=0, column=0, sticky="nsew")

        scrollbar_y = ctk.CTkScrollbar(text_frame, command=self.recv_text.yview)
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        self.recv_text.configure(yscrollcommand=scrollbar_y.set)

        scrollbar_x = ctk.CTkScrollbar(text_frame, orientation="horizontal", command=self.recv_text.xview)
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        self.recv_text.configure(xscrollcommand=scrollbar_x.set)

        self.recv_text.configure(state="disabled")

        self._setup_text_tags()

    def _build_send_area(self):
        send_frame = ctk.CTkFrame(self, corner_radius=8, height=140)
        send_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=4)
        send_frame.grid_columnconfigure(0, weight=1)

        send_toolbar = ctk.CTkFrame(send_frame, height=32, corner_radius=0, fg_color="transparent")
        send_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 0))

        ctk.CTkLabel(send_toolbar, text="发送区", font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")

        self.hex_send_var = ctk.BooleanVar(value=self.cfg["hex_send"])
        ctk.CTkCheckBox(send_toolbar, text="HEX发送", variable=self.hex_send_var,
                        font=("Microsoft YaHei UI", 12), width=90, checkbox_width=18, checkbox_height=18
                        ).pack(side="left", padx=(16, 4))

        self.newline_var = ctk.BooleanVar(value=self.cfg["send_newline"])
        ctk.CTkCheckBox(send_toolbar, text="发送新行", variable=self.newline_var,
                        font=("Microsoft YaHei UI", 12), width=90, checkbox_width=18, checkbox_height=18
                        ).pack(side="left", padx=4)

        ctk.CTkLabel(send_toolbar, text="换行符:", font=("Microsoft YaHei UI", 12)).pack(side="left", padx=(8, 2))
        self.newline_type_combo = ctk.CTkComboBox(
            send_toolbar, width=80, values=["\\r\\n", "\\n", "\\r"], state="readonly"
        )
        self.newline_type_combo.pack(side="left", padx=2)
        self.newline_type_combo.set(self.cfg["newline_type"])

        auto_frame = ctk.CTkFrame(send_toolbar, fg_color="transparent")
        auto_frame.pack(side="right")

        self.auto_send_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(auto_frame, text="定时发送", variable=self.auto_send_var,
                        font=("Microsoft YaHei UI", 12), width=90, checkbox_width=18, checkbox_height=18,
                        command=self._toggle_auto_send
                        ).pack(side="left", padx=4)

        ctk.CTkLabel(auto_frame, text="周期:", font=("Microsoft YaHei UI", 12)).pack(side="left", padx=(4, 2))
        self.auto_interval_entry = ctk.CTkEntry(auto_frame, width=60, placeholder_text="1000")
        self.auto_interval_entry.pack(side="left", padx=2)
        self.auto_interval_entry.insert(0, "1000")
        ctk.CTkLabel(auto_frame, text="ms", font=("Microsoft YaHei UI", 12)).pack(side="left", padx=(0, 4))

        input_row = ctk.CTkFrame(send_frame, fg_color="transparent")
        input_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 4))
        input_row.grid_columnconfigure(0, weight=1)

        self.send_entry = ctk.CTkEntry(
            input_row, height=36,
            placeholder_text="输入命令... (Enter发送, ↑↓ 历史记录)",
            font=("Consolas", 13)
        )
        self.send_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.send_entry.bind("<Return>", self._on_send_enter)
        self.send_entry.bind("<Up>", self._on_history_up)
        self.send_entry.bind("<Down>", self._on_history_down)
        self.send_entry.bind("<Tab>", self._on_tab_complete)

        ctk.CTkButton(input_row, text="发送", width=70, height=36,
                      fg_color="#3B82F6", hover_color="#2563EB",
                      font=("Microsoft YaHei UI", 13, "bold"),
                      command=self._send_data).grid(row=0, column=1, padx=(0, 4))

        ctk.CTkButton(input_row, text="发送文件", width=80, height=36,
                      fg_color="#6366F1", hover_color="#4F46E5",
                      font=("Microsoft YaHei UI", 12),
                      command=self._send_file).grid(row=0, column=2, padx=(0, 4))

        ctk.CTkButton(input_row, text="清除", width=56, height=36,
                      fg_color="#6B7280", hover_color="#4B5563",
                      command=lambda: self.send_entry.delete(0, "end")).grid(row=0, column=3)

        quick_frame = ctk.CTkFrame(send_frame, height=36, fg_color="transparent")
        quick_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 6))

        ctk.CTkLabel(quick_frame, text="快捷命令:", font=("Microsoft YaHei UI", 12)).pack(side="left", padx=(0, 6))

        for item in self.cfg.get("quick_cmds", []):
            btn = ctk.CTkButton(
                quick_frame, text=item["name"], width=60, height=28,
                fg_color="#374151", hover_color="#4B5563",
                font=("Microsoft YaHei UI", 11),
                command=lambda c=item["cmd"]: self._quick_send(c)
            )
            btn.pack(side="left", padx=2)

        ctk.CTkButton(quick_frame, text="+", width=28, height=28,
                      fg_color="#374151", hover_color="#4B5563",
                      font=("Microsoft YaHei UI", 14),
                      command=self._add_quick_cmd).pack(side="left", padx=4)

    def _build_statusbar(self):
        status = ctk.CTkFrame(self, height=28, corner_radius=0)
        status.grid(row=3, column=0, sticky="ew")

        self.status_label = ctk.CTkLabel(status, text="● 未连接", font=("Microsoft YaHei UI", 12),
                                         text_color="#EF4444")
        self.status_label.pack(side="left", padx=12)

        self.clock_label = ctk.CTkLabel(status, text="", font=("Microsoft YaHei UI", 11),
                                        text_color="#9CA3AF")
        self.clock_label.pack(side="right", padx=12)

        self.rx_label = ctk.CTkLabel(status, text="RX: 0", font=("Consolas", 11), text_color="#22C55E")
        self.rx_label.pack(side="right", padx=8)

        self.tx_label = ctk.CTkLabel(status, text="TX: 0", font=("Consolas", 11), text_color="#3B82F6")
        self.tx_label.pack(side="right", padx=8)

        theme_btn = ctk.CTkButton(status, text="🌓", width=28, height=22,
                                  fg_color="transparent", hover_color="#374151",
                                  command=self._toggle_theme, font=("Segoe UI Emoji", 13))
        theme_btn.pack(side="right", padx=4)

    # ─── 文本标签 ─────────────────────────────────────────────────────────

    def _setup_text_tags(self):
        for code, color in ANSI_COLOR_MAP.items():
            self.recv_text.tag_configure(f"ansi_{code}", foreground=color)

        for level, color in ESP_LOG_COLORS.items():
            self.recv_text.tag_configure(f"esp_{level}", foreground=color)

        self.recv_text.tag_configure("bold", font=(self.cfg["font_family"], self.cfg["font_size"], "bold"))
        self.recv_text.tag_configure("timestamp", foreground="#6B7280")
        self.recv_text.tag_configure("tx_echo", foreground="#60A5FA")
        self.recv_text.tag_configure("system", foreground="#F59E0B")
        self.recv_text.tag_configure("default", foreground="#CDD6F4")

    # ─── 字体设置 ─────────────────────────────────────────────────────────

    def _apply_font_settings(self):
        family = self.cfg["font_family"]
        size = self.cfg["font_size"]
        self.recv_text.configure(font=(family, size))
        for code in ANSI_COLOR_MAP:
            self.recv_text.tag_configure(f"ansi_{code}", font=(family, size))
        for level in ESP_LOG_COLORS:
            self.recv_text.tag_configure(f"esp_{level}", font=(family, size))
        self.recv_text.tag_configure("bold", font=(family, size, "bold"))
        self.recv_text.tag_configure("timestamp", font=(family, size))
        self.recv_text.tag_configure("tx_echo", font=(family, size))
        self.recv_text.tag_configure("system", font=(family, size))
        self.recv_text.tag_configure("default", font=(family, size))

    def _on_font_change(self, value):
        self.cfg["font_family"] = value
        self._apply_font_settings()

    def _on_font_size_change(self, value):
        self.cfg["font_size"] = int(value)
        self.font_size_var.set(int(value))
        self._apply_font_settings()

    # ─── 串口操作 ─────────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [f"{p.device}: {p.description}" for p in sorted(ports, key=lambda x: x.device)]

        current = self.port_combo.get()
        current_port = current.split(":")[0].strip() if ":" in current else current.strip()

        new_values = port_list if port_list else ["无可用串口"]
        self.port_combo.configure(values=new_values)

        if port_list:
            matched = [p for p in port_list if p.startswith(current_port) and current_port not in ("", "无可用串口")]
            if matched:
                self.port_combo.set(matched[0])
            else:
                saved = self.cfg.get("port", "")
                matched_saved = [p for p in port_list if p.startswith(saved)]
                self.port_combo.set(matched_saved[0] if matched_saved else port_list[0])
        else:
            self.port_combo.set("无可用串口")

        self._last_port_values = list(new_values)

    def _refresh_ports_if_changed(self):
        ports = serial.tools.list_ports.comports()
        port_list = [f"{p.device}: {p.description}" for p in sorted(ports, key=lambda x: x.device)]
        new_values = port_list if port_list else ["无可用串口"]
        if self._last_port_values != list(new_values):
            self._refresh_ports()

    def _start_port_auto_refresh(self):
        if self._port_refresh_after_id is not None:
            try:
                self.after_cancel(self._port_refresh_after_id)
            except Exception:
                pass
            self._port_refresh_after_id = None

        def _tick():
            self._port_refresh_after_id = None
            try:
                if self.winfo_exists():
                    if not self.is_connected:
                        self._refresh_ports_if_changed()
            finally:
                if self.winfo_exists():
                    self._port_refresh_after_id = self.after(self._port_auto_refresh_interval_ms, _tick)

        if self.winfo_exists():
            self._port_refresh_after_id = self.after(self._port_auto_refresh_interval_ms, _tick)

    def _get_serial_config(self):
        parity_map = {"None": serial.PARITY_NONE, "Even": serial.PARITY_EVEN,
                      "Odd": serial.PARITY_ODD, "Mark": serial.PARITY_MARK, "Space": serial.PARITY_SPACE}
        stopbits_map = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE,
                        "2": serial.STOPBITS_TWO}

        port_str = self.port_combo.get()
        port = port_str.split(":")[0].strip() if ":" in port_str else port_str

        return {
            "port": port,
            "baudrate": int(self.baud_combo.get()),
            "bytesize": int(self.databits_combo.get()),
            "stopbits": stopbits_map.get(self.stopbits_combo.get(), serial.STOPBITS_ONE),
            "parity": parity_map.get(self.parity_combo.get(), serial.PARITY_NONE),
            "timeout": 0.05,
            "write_timeout": 1,
        }

    def _toggle_connection(self):
        if self.is_connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        try:
            config = self._get_serial_config()
            if config["port"] in ("无可用串口", ""):
                self._append_system("没有可用的串口设备\n")
                return

            self.serial_port = serial.Serial(**config)
            self.serial_port.dtr = self.dtr_var.get()
            self.serial_port.rts = self.rts_var.get()

            self.is_connected = True
            self.running = True

            self.connect_btn.configure(text="关闭串口", fg_color="#EF4444", hover_color="#DC2626")
            self.status_label.configure(text=f"● 已连接 {config['port']} @ {config['baudrate']}",
                                        text_color="#22C55E")

            self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.read_thread.start()

            self._append_system(f"已连接 {config['port']} @ {config['baudrate']}\n")

            self.cfg["port"] = config["port"]
            self.cfg["baudrate"] = config["baudrate"]

        except serial.SerialException as e:
            self._append_system(f"连接失败: {e}\n")
            self.is_connected = False

    def _disconnect(self):
        self.running = False
        self.is_connected = False

        if self.auto_send_running:
            self.auto_send_running = False
            self.auto_send_var.set(False)

        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception:
                pass

        self.connect_btn.configure(text="打开串口", fg_color="#22C55E", hover_color="#16A34A")
        self.status_label.configure(text="● 未连接", text_color="#EF4444")
        self._append_system("串口已关闭\n")

    def _on_dtr_rts_change(self):
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.dtr = self.dtr_var.get()
                self.serial_port.rts = self.rts_var.get()
            except Exception:
                pass

    # ─── 数据读取线程 ─────────────────────────────────────────────────────

    def _read_loop(self):
        buf = b""
        while self.running:
            try:
                if not self.serial_port or not self.serial_port.is_open:
                    break
                data = self.serial_port.read(self.serial_port.in_waiting or 1)
                if data:
                    self.rx_count += len(data)
                    if self.hex_display_var.get():
                        hex_str = " ".join(f"{b:02X}" for b in data)
                        self._schedule_insert(hex_str + " ", ["default"])
                    else:
                        buf += data
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            text = line.decode("utf-8", errors="replace").rstrip("\r")
                            self._process_line(text + "\n")
                        if len(buf) > 4096:
                            text = buf.decode("utf-8", errors="replace")
                            buf = b""
                            self._process_line(text)
            except serial.SerialException:
                self.after(0, self._disconnect)
                break
            except Exception:
                continue

    def _process_line(self, line):
        segments = self._parse_ansi_line(line)

        if self.timestamp_var.get():
            ts = datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] "
            self._schedule_insert(ts, ["timestamp"])

        if segments:
            for text, tags in segments:
                self._schedule_insert(text, tags)
        else:
            self._schedule_insert(line, ["default"])

    def _parse_ansi_line(self, line):
        """解析 ANSI 转义序列和 ESP-IDF 日志格式"""
        stripped = ANSI_ESCAPE_RE.sub("", line)
        esp_match = ESP_LOG_RE.match(stripped.strip())
        if esp_match:
            level = esp_match.group(1)
            tag_name = f"esp_{level}"
            return [(stripped, [tag_name])]

        segments = []
        last_end = 0
        current_tags = ["default"]

        for match in ANSI_ESCAPE_RE.finditer(line):
            start, end = match.span()
            if start > last_end:
                text = line[last_end:start]
                if text:
                    segments.append((text, list(current_tags)))

            codes = match.group(1).split(";")
            new_tags = []
            for code in codes:
                code = code.strip()
                if code == "0" or code == "":
                    new_tags = ["default"]
                elif code == "1":
                    new_tags.append("bold")
                elif code in ANSI_COLOR_MAP:
                    new_tags.append(f"ansi_{code}")
            current_tags = new_tags if new_tags else ["default"]
            last_end = end

        if last_end < len(line):
            text = line[last_end:]
            if text:
                segments.append((text, list(current_tags)))

        return segments

    # ─── 高性能文本插入（批量刷新） ──────────────────────────────────────

    def _schedule_insert(self, text, tags):
        self._pending_inserts.append((text, tags))
        if not self._flush_scheduled:
            self._flush_scheduled = True
            self.after(16, self._flush_inserts)

    def _flush_inserts(self):
        self._flush_scheduled = False
        if not self._pending_inserts:
            return

        batch = self._pending_inserts[:]
        self._pending_inserts.clear()

        self.recv_text.configure(state="normal")
        for text, tags in batch:
            self.recv_text.insert("end", text, tuple(tags))
            self.log_buffer.append((text, tags))

        line_count = int(self.recv_text.index("end-1c").split(".")[0])
        if line_count > 50000:
            self.recv_text.delete("1.0", f"{line_count - 40000}.0")

        self.recv_text.configure(state="disabled")

        if self.auto_scroll_var.get():
            self.recv_text.see("end")

        self.rx_label.configure(text=f"RX: {self._format_bytes(self.rx_count)}")

    # ─── 发送操作 ─────────────────────────────────────────────────────────

    def _send_data(self):
        if not self.is_connected:
            self._append_system("串口未连接\n")
            return

        text = self.send_entry.get()
        if not text:
            return

        try:
            if self.hex_send_var.get():
                data = bytes.fromhex(text.replace(" ", ""))
            else:
                data = text.encode("utf-8")
                if self.newline_var.get():
                    nl = self.newline_type_combo.get()
                    nl_bytes = nl.encode("utf-8").decode("unicode_escape").encode("utf-8")
                    data += nl_bytes

            self.serial_port.write(data)
            self.tx_count += len(data)
            self.tx_label.configure(text=f"TX: {self._format_bytes(self.tx_count)}")

            self._schedule_insert(f">>> {text}\n", ["tx_echo"])

            if text not in self.cmd_history:
                self.cmd_history.appendleft(text)
            self.cmd_history_idx = -1

            self.send_entry.delete(0, "end")

        except Exception as e:
            self._append_system(f"发送失败: {e}\n")

    def _on_send_enter(self, event):
        self._send_data()
        return "break"

    def _on_history_up(self, event):
        if not self.cmd_history:
            return "break"
        self.cmd_history_idx = min(self.cmd_history_idx + 1, len(self.cmd_history) - 1)
        self.send_entry.delete(0, "end")
        self.send_entry.insert(0, self.cmd_history[self.cmd_history_idx])
        return "break"

    def _on_history_down(self, event):
        if self.cmd_history_idx <= 0:
            self.cmd_history_idx = -1
            self.send_entry.delete(0, "end")
            return "break"
        self.cmd_history_idx -= 1
        self.send_entry.delete(0, "end")
        self.send_entry.insert(0, self.cmd_history[self.cmd_history_idx])
        return "break"

    def _on_tab_complete(self, event):
        return "break"

    def _quick_send(self, cmd):
        if not self.is_connected:
            self._append_system("串口未连接\n")
            return
        self.send_entry.delete(0, "end")
        self.send_entry.insert(0, cmd)
        self._send_data()

    def _send_file(self):
        if not self.is_connected:
            self._append_system("串口未连接\n")
            return

        filepath = filedialog.askopenfilename(
            title="选择要发送的文件",
            filetypes=[("所有文件", "*.*"), ("文本文件", "*.txt"), ("二进制文件", "*.bin")]
        )
        if not filepath:
            return

        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.serial_port.write(data)
            self.tx_count += len(data)
            self.tx_label.configure(text=f"TX: {self._format_bytes(self.tx_count)}")
            self._append_system(f"文件已发送: {os.path.basename(filepath)} ({len(data)} bytes)\n")
        except Exception as e:
            self._append_system(f"文件发送失败: {e}\n")

    def _toggle_auto_send(self):
        if self.auto_send_var.get():
            if not self.is_connected:
                self._append_system("串口未连接\n")
                self.auto_send_var.set(False)
                return
            try:
                interval = int(self.auto_interval_entry.get())
            except ValueError:
                interval = 1000
            self.auto_send_running = True
            self.auto_send_thread = threading.Thread(
                target=self._auto_send_loop, args=(interval,), daemon=True
            )
            self.auto_send_thread.start()
        else:
            self.auto_send_running = False

    def _auto_send_loop(self, interval_ms):
        while self.auto_send_running and self.is_connected:
            self.after(0, self._send_data)
            time.sleep(interval_ms / 1000.0)

    # ─── 添加快捷命令 ────────────────────────────────────────────────────

    def _add_quick_cmd(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("添加快捷命令")
        dialog.geometry("320x180")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        ctk.CTkLabel(dialog, text="按钮名称:", font=("Microsoft YaHei UI", 13)).grid(
            row=0, column=0, padx=16, pady=(16, 4), sticky="w")
        name_entry = ctk.CTkEntry(dialog, width=200, placeholder_text="如: 重启")
        name_entry.grid(row=0, column=1, padx=(0, 16), pady=(16, 4))

        ctk.CTkLabel(dialog, text="发送命令:", font=("Microsoft YaHei UI", 13)).grid(
            row=1, column=0, padx=16, pady=4, sticky="w")
        cmd_entry = ctk.CTkEntry(dialog, width=200, placeholder_text="如: reboot")
        cmd_entry.grid(row=1, column=1, padx=(0, 16), pady=4)

        def on_add():
            name = name_entry.get().strip()
            cmd = cmd_entry.get().strip()
            if name and cmd:
                self.cfg.setdefault("quick_cmds", []).append({"name": name, "cmd": cmd})
                save_config(self.cfg)
                dialog.destroy()
                self._append_system(f"已添加快捷命令: {name} -> {cmd} (重启后生效)\n")

        ctk.CTkButton(dialog, text="添加", width=100, command=on_add).grid(
            row=2, column=0, columnspan=2, pady=16)

    # ─── 辅助方法 ─────────────────────────────────────────────────────────

    def _append_system(self, text):
        self._schedule_insert(text, ["system"])

    def _clear_recv(self):
        self.recv_text.configure(state="normal")
        self.recv_text.delete("1.0", "end")
        self.recv_text.configure(state="disabled")
        self.rx_count = 0
        self.tx_count = 0
        self.rx_label.configure(text="RX: 0")
        self.tx_label.configure(text="TX: 0")
        self.log_buffer.clear()

    def _save_log(self):
        filepath = filedialog.asksaveasfilename(
            title="保存日志",
            defaultextension=".log",
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=f"serial_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        if not filepath:
            return
        try:
            content = self.recv_text.get("1.0", "end")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self._append_system(f"日志已保存: {filepath}\n")
        except Exception as e:
            self._append_system(f"保存失败: {e}\n")

    def _toggle_theme(self):
        current = ctk.get_appearance_mode()
        new_mode = "light" if current == "Dark" else "dark"
        ctk.set_appearance_mode(new_mode)
        self.cfg["theme"] = new_mode

        if new_mode == "dark":
            self.recv_text.configure(bg="#1E1E2E", fg="#CDD6F4", insertbackground="#CDD6F4",
                                     selectbackground="#45475A", selectforeground="#CDD6F4")
            self.recv_text.master.configure(fg_color="#1E1E2E")
        else:
            self.recv_text.configure(bg="#FFFFFF", fg="#1E293B", insertbackground="#1E293B",
                                     selectbackground="#BFDBFE", selectforeground="#1E293B")
            self.recv_text.master.configure(fg_color="#FFFFFF")

    def _update_clock(self):
        self.clock_label.configure(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.after(1000, self._update_clock)

    @staticmethod
    def _format_bytes(n):
        if n < 1024:
            return str(n)
        elif n < 1024 * 1024:
            return f"{n / 1024:.1f}K"
        else:
            return f"{n / (1024 * 1024):.1f}M"

    def _restore_settings(self):
        self.dtr_var.set(self.cfg.get("dtr", False))
        self.rts_var.set(self.cfg.get("rts", False))

    def _on_close(self):
        self.cfg["hex_display"] = self.hex_display_var.get()
        self.cfg["hex_send"] = self.hex_send_var.get()
        self.cfg["auto_scroll"] = self.auto_scroll_var.get()
        self.cfg["timestamp"] = self.timestamp_var.get()
        self.cfg["send_newline"] = self.newline_var.get()
        self.cfg["newline_type"] = self.newline_type_combo.get()
        self.cfg["dtr"] = self.dtr_var.get()
        self.cfg["rts"] = self.rts_var.get()
        self.cfg["font_family"] = self.font_family_combo.get()
        self.cfg["font_size"] = self.font_size_var.get()
        self.cfg["cmd_history"] = list(self.cmd_history)[:20]
        save_config(self.cfg)

        if self._port_refresh_after_id is not None:
            try:
                self.after_cancel(self._port_refresh_after_id)
            except Exception:
                pass
            self._port_refresh_after_id = None

        self.running = False
        self.auto_send_running = False
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception:
                pass
        self.destroy()


# ─── 入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = SerialAssistant()
    app.mainloop()
