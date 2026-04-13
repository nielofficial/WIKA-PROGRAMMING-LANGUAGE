"""
WIKA IDE — Integrated Development Environment
Para sa WIKA programming language (bilang + titik lamang).

Features:
  - Syntax highlighting
  - Line numbers
  - Font size adjuster
  - Dark / Light mode toggle
  - Open / Save / New file
  - Three output panels:
      1. Actual Output    (values printed by ipakita)
      2. MIPS Assembly    (instructions + labels)
      3. Hex & Binary     (machine code encoding per instruction)
  - Error panel with red highlights
  - Line & column indicator
  - Keyboard shortcuts (Ctrl+R, Ctrl+S, Ctrl+N, Ctrl+O)
  - Copy output buttons
  - Recent files (last 5)
  - Current line highlight
  - Token counter
  - Run status badge

Requirements:
  pip install customtkinter
  wika.exe (or wika on Linux/Mac) in the same folder as this script.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import os
import json
import tempfile
import re
from datetime import datetime

# ── App settings ────────────────────────────────────────────
APP_TITLE     = "WIKA IDE"
APP_VERSION   = "2.0"
SETTINGS_FILE = "wika_ide_settings.json"
RECENT_MAX    = 5

DEFAULT_SETTINGS = {
    "theme":          "dark",
    "font_family":    "Consolas",
    "font_size":      14,
    "recent_files":   [],
    "wika_exe_path":  "",
}

# ── Color palettes ───────────────────────────────────────────
DARK_COLORS = {
    "bg_editor":    "#1E1E2E",
    "bg_panel":     "#181825",
    "bg_sidebar":   "#11111B",
    "bg_button":    "#313244",
    "fg_text":      "#CDD6F4",
    "fg_dim":       "#6C7086",
    "fg_linenum":   "#45475A",
    "accent":       "#89B4FA",
    "accent2":      "#A6E3A1",
    "accent3":      "#F38BA8",
    "kw_color":     "#CBA6F7",
    "type_color":   "#89DCEB",
    "bi_color":     "#A6E3A1",
    "num_color":    "#FAB387",
    "comment_color":"#6C7086",
    "op_color":     "#89B4FA",
    "curline_color":"#2A2A3E",
    "out_bg":       "#1E1E2E",
    "out_fg":       "#CDD6F4",
    "mips_bg":      "#0D1B2A",
    "mips_fg":      "#A6E3A1",
    "hex_bg":       "#1A0D2E",
    "hex_fg":       "#FAB387",
    "error_fg":     "#F38BA8",
    "success_fg":   "#A6E3A1",
}

LIGHT_COLORS = {
    "bg_editor":    "#FFFFFF",
    "bg_panel":     "#F5F5F5",
    "bg_sidebar":   "#EBEBEB",
    "bg_button":    "#DEDEDE",
    "fg_text":      "#1A1A2E",
    "fg_dim":       "#555555",
    "fg_linenum":   "#999999",
    "accent":       "#1565C0",
    "accent2":      "#1B5E20",
    "accent3":      "#B71C1C",
    "kw_color":     "#6A0DAD",
    "type_color":   "#0057A8",
    "bi_color":     "#1B7030",
    "num_color":    "#B94000",
    "comment_color":"#707070",
    "op_color":     "#00529B",
    "curline_color":"#EEF2FF",
    "out_bg":       "#FFFFFF",
    "out_fg":       "#1A1A2E",
    "mips_bg":      "#F0F8FF",
    "mips_fg":      "#1B4332",
    "hex_bg":       "#FFF8F0",
    "hex_fg":       "#7B3800",
    "error_fg":     "#B71C1C",
    "success_fg":   "#1B5E20",
}

KEYWORDS  = ["simula", "tapos"]
TYPES     = ["bilang", "titik"]
BUILTINS  = ["ipakita"]


# ── Settings ─────────────────────────────────────────────────
class Settings:
    def __init__(self):
        self.data = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r") as f:
                    self.data.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def __getitem__(self, k):
        return self.data.get(k, DEFAULT_SETTINGS.get(k))

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()


# ── Line number canvas ────────────────────────────────────────
class LineNumberCanvas(tk.Canvas):
    def __init__(self, parent, editor, colors, font_family, font_size, **kwargs):
        super().__init__(parent, **kwargs)
        self.editor      = editor
        self.colors      = colors
        self.font_family = font_family
        self.font_size   = font_size
        self.configure(bg=colors["bg_sidebar"], highlightthickness=0, width=48)
        for event in ("<KeyRelease>", "<ButtonRelease>", "<MouseWheel>", "<<Scroll>>"):
            self.editor.bind(event, self._update, add=True)

    def _update(self, event=None):
        self.delete("all")
        i = self.editor.index("@0,0")
        while True:
            dline = self.editor.dlineinfo(i)
            if dline is None:
                break
            y    = dline[1]
            line = str(i).split(".")[0]
            self.create_text(
                40, y + 2, anchor="ne", text=line,
                fill=self.colors["fg_linenum"],
                font=(self.font_family, self.font_size - 2)
            )
            i = self.editor.index(f"{i}+1line")
            if i == self.editor.index(f"{i}-1line"):
                break

    def update_colors(self, colors):
        self.colors = colors
        self.configure(bg=colors["bg_sidebar"])
        self._update()

    def update_font(self, family, size):
        self.font_family = family
        self.font_size   = size
        self._update()


# ── Main IDE Window ───────────────────────────────────────────
class WikaIDE(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings     = Settings()
        self.current_file = None
        self.colors       = DARK_COLORS if self.settings["theme"] == "dark" else LIGHT_COLORS
        self._setup_window()
        self._build_ui()
        self._apply_theme()
        self._load_starter_code()
        self._update_line_col()
        self.editor.bind("<KeyRelease>", self._on_key_syntax, add=True)
        self._do_highlight()

    # ── Window ───────────────────────────────────────────────
    def _setup_window(self):
        ctk.set_appearance_mode(self.settings["theme"])
        ctk.set_default_color_theme("blue")
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("1600x900")
        self.minsize(1000, 640)
        self._bind_shortcuts()

    def _bind_shortcuts(self):
        for key in ("<Control-r>", "<Control-R>"):
            self.bind(key, lambda e: self._run())
        for key in ("<Control-s>", "<Control-S>"):
            self.bind(key, lambda e: self._save())
        for key in ("<Control-n>", "<Control-N>"):
            self.bind(key, lambda e: self._new())
        for key in ("<Control-o>", "<Control-O>"):
            self.bind(key, lambda e: self._open())
        self.bind("<Control-equal>",    lambda e: self._font_size_change(1))
        self.bind("<Control-minus>",    lambda e: self._font_size_change(-1))
        self.bind("<Control-MouseWheel>", self._zoom_scroll)

    # ── UI Build ─────────────────────────────────────────────
    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_topbar()
        self._build_main_area()
        self._build_statusbar()

    def _build_topbar(self):
        bar = ctk.CTkFrame(self, height=52, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(
            bar, text="  WIKA IDE",
            font=ctk.CTkFont(family="Arial", size=18, weight="bold"),
            text_color=self.colors["accent"]
        ).grid(row=0, column=0, padx=(16, 8), pady=8)

        btn_cfg = dict(width=80, height=34, corner_radius=8)
        for col, (text, cmd) in enumerate([
            ("New",  self._new),
            ("Open", self._open),
            ("Save", self._save),
        ], start=1):
            ctk.CTkButton(bar, text=text, command=cmd, **btn_cfg).grid(
                row=0, column=col, padx=4, pady=8)

        self.recent_var  = ctk.StringVar(value="Recent")
        self.recent_menu = ctk.CTkOptionMenu(
            bar, values=self._get_recent_labels(),
            variable=self.recent_var,
            command=self._open_recent,
            width=140, height=34,
        )
        self.recent_menu.grid(row=0, column=4, padx=4, pady=8)

        ctk.CTkLabel(bar, text="").grid(row=0, column=5, sticky="ew")

        ctk.CTkLabel(bar, text="Font:").grid(row=0, column=6, padx=(8, 2))
        self.font_family_var = ctk.StringVar(value=self.settings["font_family"])
        ctk.CTkOptionMenu(
            bar,
            values=["Consolas", "Courier New", "Lucida Console", "Cascadia Code"],
            variable=self.font_family_var,
            command=self._change_font_family,
            width=150, height=34,
        ).grid(row=0, column=7, padx=4)

        ctk.CTkButton(bar, text="A-", width=36, height=34, corner_radius=8,
                      command=lambda: self._font_size_change(-1)
                      ).grid(row=0, column=8, padx=2)
        self.font_size_label = ctk.CTkLabel(bar, text=str(self.settings["font_size"]), width=28)
        self.font_size_label.grid(row=0, column=9, padx=2)
        ctk.CTkButton(bar, text="A+", width=36, height=34, corner_radius=8,
                      command=lambda: self._font_size_change(1)
                      ).grid(row=0, column=10, padx=2)

        self.theme_btn = ctk.CTkButton(
            bar,
            text="☀ Light" if self.settings["theme"] == "dark" else "🌙 Dark",
            width=90, height=34, corner_radius=8,
            command=self._toggle_theme,
        )
        self.theme_btn.grid(row=0, column=11, padx=8)

        ctk.CTkButton(
            bar, text="📖  Docs",
            width=90, height=34, corner_radius=8,
            command=self._show_docs,
        ).grid(row=0, column=12, padx=(0, 8))

        self.run_btn = ctk.CTkButton(
            bar, text="▶  Run",
            width=100, height=36, corner_radius=10,
            fg_color="#A6E3A1", hover_color="#89DCEB",
            text_color="#1E1E2E",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._run,
        )
        self.run_btn.grid(row=0, column=13, padx=(0, 16))

    def _build_main_area(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        # editor=3 parts, output panels=2 parts each (3 panels on right)
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=4)
        self._build_editor_panel(main)
        self._build_output_area(main)

    def _build_editor_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        panel.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            panel, text="  📝  Wika Code Editor",
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))

        self.editor = tk.Text(
            panel,
            font=(self.settings["font_family"], self.settings["font_size"]),
            bg=self.colors["bg_editor"],
            fg=self.colors["fg_text"],
            insertbackground=self.colors["accent"],
            selectbackground="#3D5A8A",
            relief="flat",
            padx=12, pady=8,
            undo=True,
            wrap="none",
            tabs=("1c",),
            spacing1=2,
        )
        self.editor.grid(row=1, column=1, sticky="nsew")

        yscroll = ctk.CTkScrollbar(panel, command=self._editor_yview)
        yscroll.grid(row=1, column=2, sticky="ns")
        xscroll = ctk.CTkScrollbar(panel, orientation="horizontal",
                                   command=self.editor.xview)
        xscroll.grid(row=2, column=1, sticky="ew")

        self.editor.configure(
            yscrollcommand=self._make_scroll_handler(yscroll),
            xscrollcommand=xscroll.set,
        )

        self.ln_updater = LineNumberCanvas(
            panel, self.editor, self.colors,
            self.settings["font_family"], self.settings["font_size"],
        )
        self.ln_updater.grid(row=1, column=0, sticky="ns")

        self.editor.bind("<KeyRelease>",    self._on_key,       add=True)
        self.editor.bind("<ButtonRelease>", self._update_line_col)
        self.editor.bind("<Return>",        self._auto_indent)
        self.editor.bind("<Tab>",           self._insert_tab)

    def _make_scroll_handler(self, scrollbar):
        def handler(*args):
            scrollbar.set(*args)
            self.ln_updater._update()
        return handler

    def _editor_yview(self, *args):
        self.editor.yview(*args)
        self.ln_updater._update()

    # ── Output area: three stacked panels on the right ───────
    def _build_output_area(self, parent):
        right = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.grid_columnconfigure(0, weight=1)
        # Three rows, equal weight
        right.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=2)
        right.grid_rowconfigure(2, weight=2)

        self._build_actual_output(right, row=0)
        self._build_mips_panel(right, row=1)
        self._build_hex_panel(right, row=2)

    def _make_output_box(self, parent, bg, fg):
        box = tk.Text(
            parent, font=("Consolas", self.settings["font_size"] - 1),
            bg=bg, fg=fg,
            insertbackground=fg,
            relief="flat", padx=10, pady=6,
            state="disabled", wrap="none",
        )
        return box

    def _build_actual_output(self, parent, row):
        frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="nsew", pady=(0, 4))
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(header, text="  ✅  Output (Actual)",
                     font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
                     ).pack(side="left")
        self.status_badge = ctk.CTkLabel(
            header, text="", width=70, height=22, corner_radius=6,
            font=ctk.CTkFont(size=11))
        self.status_badge.pack(side="left", padx=6)
        ctk.CTkButton(header, text="Copy", width=55, height=24, corner_radius=6,
                      command=lambda: self._copy_text(self.output_box)
                      ).pack(side="right", padx=2)
        ctk.CTkButton(header, text="Clear", width=55, height=24, corner_radius=6,
                      command=self._clear_outputs
                      ).pack(side="right", padx=2)

        self.output_box = self._make_output_box(
            frame, self.colors["out_bg"], self.colors["out_fg"])
        self.output_box.grid(row=1, column=0, sticky="nsew")
        self.output_box.tag_config("error",   foreground=self.colors["error_fg"])
        self.output_box.tag_config("success", foreground=self.colors["success_fg"])

        sb = ctk.CTkScrollbar(frame, command=self.output_box.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.output_box.configure(yscrollcommand=sb.set)

    def _build_mips_panel(self, parent, row):
        frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="nsew", pady=(4, 2))
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(header, text="  ⚙️  MIPS Assembly (.data + .code)",
                     font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
                     ).pack(side="left")
        ctk.CTkButton(header, text="Copy", width=55, height=24, corner_radius=6,
                      command=lambda: self._copy_text(self.mips_box)
                      ).pack(side="right", padx=2)

        self.mips_box = self._make_output_box(
            frame, self.colors["mips_bg"], self.colors["mips_fg"])
        self.mips_box.grid(row=1, column=0, sticky="nsew")
        self._setup_mips_tags()

        sb = ctk.CTkScrollbar(frame, command=self.mips_box.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.mips_box.configure(yscrollcommand=sb.set)

    def _build_hex_panel(self, parent, row):
        frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="nsew", pady=(2, 0))
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(header, text="  🔢  Hex & Binary Encoding",
                     font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
                     ).pack(side="left")
        ctk.CTkButton(header, text="Copy", width=55, height=24, corner_radius=6,
                      command=lambda: self._copy_text(self.hex_box)
                      ).pack(side="right", padx=2)

        self.hex_box = self._make_output_box(
            frame, self.colors["hex_bg"], self.colors["hex_fg"])
        self.hex_box.grid(row=1, column=0, sticky="nsew")
        self._setup_hex_tags()

        sb = ctk.CTkScrollbar(frame, command=self.hex_box.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.hex_box.configure(yscrollcommand=sb.set)

    def _setup_mips_tags(self):
        c = self.colors
        self.mips_box.tag_config("instr",   foreground=c["mips_fg"])
        self.mips_box.tag_config("label",   foreground=c["accent"])
        self.mips_box.tag_config("syscall", foreground=c["type_color"])
        self.mips_box.tag_config("comment", foreground=c["comment_color"])
        self.mips_box.tag_config("data",    foreground=c["num_color"])
        self.mips_box.tag_config("output",  foreground=c["success_fg"])

    def _setup_hex_tags(self):
        c = self.colors
        self.hex_box.tag_config("instr",    foreground=c["accent"])
        self.hex_box.tag_config("hex_val",  foreground=c["hex_fg"])
        self.hex_box.tag_config("bin_val",  foreground=c["accent2"])
        self.hex_box.tag_config("label",    foreground=c["kw_color"])

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, height=28, corner_radius=0)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(3, weight=1)

        self.lc_label    = ctk.CTkLabel(bar, text="Ln 1, Col 1", font=ctk.CTkFont(size=11))
        self.token_label = ctk.CTkLabel(bar, text="Tokens: 0",   font=ctk.CTkFont(size=11))
        self.file_label  = ctk.CTkLabel(bar, text="Untitled",    font=ctk.CTkFont(size=11))
        self.time_label  = ctk.CTkLabel(bar, text="",            font=ctk.CTkFont(size=11))

        self.lc_label.grid(   row=0, column=0, padx=12, pady=2)
        self.token_label.grid(row=0, column=1, padx=12, pady=2)
        ctk.CTkLabel(bar, text="|", font=ctk.CTkFont(size=11)).grid(row=0, column=2)
        self.file_label.grid( row=0, column=4, padx=12, pady=2, sticky="e")
        self.time_label.grid( row=0, column=5, padx=12, pady=2, sticky="e")

    # ── Syntax Highlighting ───────────────────────────────────
    def _on_key_syntax(self, event=None):
        if hasattr(self, "_hl_job"):
            self.after_cancel(self._hl_job)
        self._hl_job = self.after(120, self._do_highlight)

    def _do_highlight(self):
        code = self.editor.get("1.0", "end-1c")
        for tag in ["kw", "type", "bi", "num", "comment", "op", "curline"]:
            self.editor.tag_remove(tag, "1.0", "end")

        cur_line = self.editor.index("insert").split(".")[0]
        self.editor.tag_add("curline", f"{cur_line}.0", f"{cur_line}.end+1c")

        def apply(pattern, tag, flags=0):
            for m in re.finditer(pattern, code, flags):
                s = f"1.0+{m.start()}c"
                e = f"1.0+{m.end()}c"
                self.editor.tag_add(tag, s, e)

        apply(r'#[^\n]*',                              "comment")
        apply(r"'[^']'",                               "num")
        apply(r'\b(' + '|'.join(KEYWORDS) + r')\b',   "kw")
        apply(r'\b(' + '|'.join(TYPES)    + r')\b',   "type")
        apply(r'\b(' + '|'.join(BUILTINS) + r')\b',   "bi")
        apply(r'\b\d+\b',                              "num")
        apply(r'(\+\+|--|[+\-*/=])',                   "op")

        # Token count
        tokens = re.findall(
            r'\b(?:' + '|'.join(KEYWORDS + TYPES + BUILTINS) + r')\b'
            r"|'[^']'"
            r'|\b\d+\b|[+\-*/=,(){}]'
            r'|[a-zA-Z_][a-zA-Z0-9_]*',
            code
        )
        self.token_label.configure(text=f"Tokens: {len(tokens)}")

    def _apply_syntax_tag_colors(self):
        c  = self.colors
        f  = self.settings["font_family"]
        sz = self.settings["font_size"]
        self.editor.tag_config("kw",      foreground=c["kw_color"],  font=(f, sz, "bold"))
        self.editor.tag_config("type",    foreground=c["type_color"],font=(f, sz, "bold"))
        self.editor.tag_config("bi",      foreground=c["bi_color"],  font=(f, sz, "bold"))
        self.editor.tag_config("num",     foreground=c["num_color"])
        self.editor.tag_config("comment", foreground=c["comment_color"], font=(f, sz, "italic"))
        self.editor.tag_config("op",      foreground=c["op_color"])
        self.editor.tag_config("curline", background=c["curline_color"])

    # ── Run ──────────────────────────────────────────────────
    def _run(self, event=None):
        code = self.editor.get("1.0", "end-1c").strip()
        if not code:
            self._show_output("(walang code na isine-run)", error=True)
            return

        wika_exe = self._find_wika()
        if not wika_exe:
            self._show_output(
                "ERROR: Hindi mahanap ang 'wika' executable!\n\n"
                "Siguraduhing nandito ang wika (o wika.exe) sa parehong folder.",
                error=True)
            return

        # Disable run button, show "Running..."
        self.run_btn.configure(text="⏳ Running...", state="disabled",
                               fg_color="#555555")
        self.update_idletasks()

        try:
            self._do_run(wika_exe, code)
        finally:
            self.run_btn.configure(text="▶  Run", state="normal",
                                   fg_color="#A6E3A1")
            self.time_label.configure(
                text=f"Last run: {datetime.now().strftime('%H:%M:%S')}")

    def _do_run(self, wika_exe, code):
        # Write code to temp file
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".wika", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmpfile = f.name

        try:
            result = subprocess.run(
                [wika_exe],
                stdin=open(tmpfile, "r", encoding="utf-8"),
                capture_output=True, text=True, timeout=8,
            )
            self._parse_and_display(result.stdout, result.stderr, result.returncode)
        except subprocess.TimeoutExpired:
            self._show_output("ERROR: Timeout — ang program ay tumatagal ng masyadong matagal.",
                              error=True)
        except Exception as ex:
            self._show_output(f"ERROR: {ex}", error=True)
        finally:
            try:
                os.unlink(tmpfile)
            except Exception:
                pass

    # ── Output Parsing ────────────────────────────────────────
    def _parse_and_display(self, stdout, stderr, returncode):
        self._clear_outputs()

        if returncode != 0 or (stderr and stderr.strip()):
            self._set_status("Error", ok=False)
            self._show_output(stderr.strip() or "Hindi kilalang error.", error=True)
            return

        self._set_status("OK", ok=True)

        # Split stdout into three buckets:
        #   actual_lines — lines tagged "; OUTPUT: ..."
        #   hex_lines    — lines starting with "; HEX:" or "; BINARY:"
        #   mips_lines   — everything else (instructions, .data, .code, etc.)

        actual_lines = []
        mips_lines   = []
        hex_lines    = []

        lines = stdout.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("; OUTPUT:"):
                val = stripped[len("; OUTPUT:"):].strip()
                actual_lines.append(val)
            elif stripped.startswith("; HEX:") or stripped.startswith("; BINARY:"):
                hex_lines.append(line)
            else:
                mips_lines.append(line)
            i += 1

        # ── Actual Output panel ──
        if actual_lines:
            self._write_box(self.output_box, "\n".join(actual_lines))
        else:
            self._write_box(self.output_box, "(walang output)")

        # ── MIPS Assembly panel ──
        self._write_mips("\n".join(mips_lines))

        # ── Hex & Binary panel ──
        self._write_hex("\n".join(hex_lines))

    def _write_box(self, box, text, error=False):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("end", text, "error" if error else "")
        box.configure(state="disabled")

    def _write_mips(self, text):
        self.mips_box.configure(state="normal")
        self.mips_box.delete("1.0", "end")
        for line in text.splitlines():
            s = line.strip()
            if s.startswith(";"):
                self.mips_box.insert("end", line + "\n", "comment")
            elif s.startswith(".data") or s.startswith(".code"):
                self.mips_box.insert("end", line + "\n", "label")
            elif s.startswith("SYSCALL"):
                self.mips_box.insert("end", line + "\n", "syscall")
            elif re.match(r'\s*(daddi|daddu|dsubu|dmultu|ddiv|mflo|ld |sd |la )', line):
                self.mips_box.insert("end", line + "\n", "instr")
            elif re.match(r'\s*\w+\s*:', line):
                self.mips_box.insert("end", line + "\n", "data")
            else:
                self.mips_box.insert("end", line + "\n")
        self.mips_box.configure(state="disabled")

    def _write_hex(self, text):
        self.hex_box.configure(state="normal")
        self.hex_box.delete("1.0", "end")

        for line in text.splitlines():
            s = line.strip()

            if s.startswith("; HEX:"):
                value = s.replace("; HEX:", "").strip()
                self.hex_box.insert("end", value + "\n", "hex_val")

            elif s.startswith("; BINARY:"):
                value = s.replace("; BINARY:", "").strip()
                self.hex_box.insert("end", value + "\n", "bin_val")

            else:
                self.hex_box.insert("end", line + "\n")

        self.hex_box.configure(state="disabled")

    def _show_output(self, text, error=False):
        self._write_box(self.output_box, text, error=error)

    def _set_status(self, text, ok=True):
        color = self.colors["success_fg"] if ok else self.colors["error_fg"]
        self.status_badge.configure(text=f"  {text}  ",
                                    fg_color="transparent",
                                    text_color=color)

    def _clear_outputs(self):
        for box in [self.output_box, self.mips_box, self.hex_box]:
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.configure(state="disabled")
        self.status_badge.configure(text="", fg_color="transparent")

    def _copy_text(self, box):
        text = box.get("1.0", "end-1c")
        # If copying the MIPS assembly panel, strip the ; HEX: and ; BINARY: annotation
        # lines so the result is clean EduMIPS64 assembly ready to paste and run.
        if box is self.mips_box:
            clean_lines = []
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("; HEX:") or stripped.startswith("; BINARY:"):
                    continue
                clean_lines.append(line)
            # Remove runs of more than one blank line that result from stripping
            text = "\n".join(clean_lines)
        self.clipboard_clear()
        self.clipboard_append(text)

    # ── File operations ───────────────────────────────────────
    def _new(self, event=None):
        if self.editor.get("1.0", "end-1c").strip():
            if not messagebox.askyesno("New File", "Discard current code?"):
                return
        self.editor.delete("1.0", "end")
        self._load_starter_code()
        self.current_file = None
        self.file_label.configure(text="Untitled")

    def _open(self, event=None):
        path = filedialog.askopenfilename(
            filetypes=[("Wika files", "*.wika"), ("All files", "*.*")])
        if path:
            self._load_file(path)

    def _open_recent(self, label):
        for path in self.settings["recent_files"]:
            if os.path.basename(path) == label:
                self._load_file(path)
                return

    def _load_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", code)
            self.current_file = path
            self.file_label.configure(text=os.path.basename(path))
            self._add_recent(path)
            self._do_highlight()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _save(self, event=None):
        if self.current_file:
            self._write_file(self.current_file)
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".wika",
                filetypes=[("Wika files", "*.wika"), ("All files", "*.*")])
            if path:
                self._write_file(path)
                self.current_file = path
                self.file_label.configure(text=os.path.basename(path))
                self._add_recent(path)

    def _write_file(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.get("1.0", "end-1c"))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _add_recent(self, path):
        recent = self.settings["recent_files"]
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self.settings["recent_files"] = recent[:RECENT_MAX]
        self.recent_menu.configure(values=self._get_recent_labels())

    def _get_recent_labels(self):
        recent = self.settings["recent_files"]
        return [os.path.basename(p) for p in recent] if recent else ["(none)"]

    # ── Find wika executable ─────────────────────────────────
    def _find_wika(self):
        saved = self.settings["wika_exe_path"]
        if saved and os.path.isfile(saved):
            return saved

        candidates = []
        for folder in [os.getcwd(),
                       os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "",
                       os.path.dirname(self.current_file) if self.current_file else ""]:
            if folder:
                candidates += [
                    os.path.join(folder, "wika.exe"),
                    os.path.join(folder, "wika"),
                ]
        candidates += ["wika.exe", "wika"]

        for c in candidates:
            if c and os.path.isfile(c):
                self.settings["wika_exe_path"] = c
                return c

        # Ask user
        if messagebox.askyesno("wika Hindi Mahanap",
                               "Hindi mahanap ang wika executable!\n\n"
                               "Gusto mo bang hanapin ito manually?"):
            path = filedialog.askopenfilename(
                title="Hanapin ang wika executable",
                filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
            if path and os.path.isfile(path):
                self.settings["wika_exe_path"] = path
                return path
        return None

    # ── Docs Window ──────────────────────────────────────────
    def _show_docs(self):
        win = ctk.CTkToplevel(self)
        win.title("WIKA Language Reference")
        win.geometry("820x640")
        win.minsize(700, 500)
        win.grab_set()

        c   = self.colors
        bg  = c["bg_panel"]
        fg  = c["fg_text"]
        acc = c["accent"]
        dim = c["fg_dim"]
        kw  = c["kw_color"]
        ty  = c["type_color"]
        num = c["num_color"]

        mono_font = (self.settings["font_family"], self.settings["font_size"] - 1)

        TABS = [
            "📋  Overview",
            "🔤  Uri ng Datos",
            "⚙️  Mga Operator",
            "🖨️  ipakita",
            "💡  Halimbawa",
            "⌨️  Shortcuts",
        ]

        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)

        tab_bar = ctk.CTkFrame(win, corner_radius=0, height=44)
        tab_bar.grid(row=0, column=0, sticky="ew")

        content = ctk.CTkFrame(win, corner_radius=0, fg_color=bg)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        tab_frames = {}
        active_tab = tk.StringVar(value=TABS[0])

        def make_text():
            frame = ctk.CTkFrame(content, corner_radius=0, fg_color=bg)
            frame.grid_rowconfigure(0, weight=1)
            frame.grid_columnconfigure(0, weight=1)
            txt = tk.Text(frame, font=mono_font, bg=bg, fg=fg,
                          relief="flat", padx=24, pady=16, wrap="word",
                          state="disabled", spacing1=4, spacing2=2, spacing3=4,
                          highlightthickness=0)
            txt.grid(row=0, column=0, sticky="nsew")
            sb = ctk.CTkScrollbar(frame, command=txt.yview)
            sb.grid(row=0, column=1, sticky="ns")
            txt.configure(yscrollcommand=sb.set)

            txt.tag_config("h1",   font=(self.settings["font_family"], self.settings["font_size"]+4, "bold"), foreground=acc)
            txt.tag_config("h2",   font=(self.settings["font_family"], self.settings["font_size"]+1, "bold"), foreground=ty)
            txt.tag_config("kw",   foreground=kw,  font=(self.settings["font_family"], self.settings["font_size"]-1, "bold"))
            txt.tag_config("type", foreground=ty,  font=(self.settings["font_family"], self.settings["font_size"]-1, "bold"))
            txt.tag_config("num",  foreground=num)
            txt.tag_config("code", background=c["bg_editor"], font=mono_font,
                           relief="flat", lmargin1=32, lmargin2=32)
            txt.tag_config("dim",  foreground=dim)
            txt.tag_config("bold", font=(self.settings["font_family"], self.settings["font_size"]-1, "bold"))
            txt.tag_config("acc",  foreground=acc, font=(self.settings["font_family"], self.settings["font_size"]-1, "bold"))
            return frame, txt

        def w(txt, text, *tags):
            txt.configure(state="normal")
            txt.insert("end", text, tags)
            txt.configure(state="disabled")

        # Overview
        def build_overview(txt):
            w(txt, "WIKA Programming Language\n", "h1")
            w(txt, "bilang + titik lamang (integers and characters)\n\n", "dim")
            w(txt, "Istruktura ng Programa\n", "h2")
            w(txt, "    simula\n    # komento\n    bilang x = 10\n    titik c = 'A'\n    ipakita(x)\n    tapos\n\n", "code")
            w(txt, "Mga Suportadong Feature\n", "h2")
            feats = [
                ("bilang",      "Integer variable (64-bit)"),
                ("titik",       "Single character variable (ASCII integer internally)"),
                ("ipakita",     "Console output"),
                ("+=  -=",      "Compound assignment"),
                ("++  --",      "Increment / decrement"),
                ("#",           "Single-line comment"),
                ("a,b,c",       "Comma-separated multi-declaration"),
            ]
            for tok, desc in feats:
                w(txt, f"    {tok:<20}", "code")
                w(txt, f"  —  {desc}\n", "dim")

        # Data types
        def build_types(txt):
            w(txt, "Uri ng Datos (Data Types)\n\n", "h1")
            w(txt, "bilang\n", "h2")
            w(txt, "  64-bit integer. Lahat ng arithmetic operations ay available.\n\n")
            w(txt, "    bilang x = 10\n    bilang a = 5, b = 3\n    bilang c          # default value = 0\n\n", "code")
            w(txt, "titik\n", "h2")
            w(txt, "  Single character. Iniimbak bilang ASCII integer sa loob.\n"
                   "  Maaaring gamitin sa arithmetic (ASCII arithmetic).\n"
                   "  ipakita() ay naglalabas ng aktwal na karakter (hindi ASCII number).\n\n")
            w(txt, "    titik letra = 'A'    # nagiging 65 sa loob\n"
                   "    titik c = 'Z'\n"
                   "    c++                  # 'Z' -> 91 -> '['\n\n", "code")
            w(txt, "Output Format\n", "h2")
            w(txt, "    bilang x = 13    →  ipakita(x)  →  13\n"
                   "    titik c = 'A'   →  ipakita(c)  →  A\n\n", "code")

        # Operators
        def build_operators(txt):
            w(txt, "Mga Operator\n\n", "h1")
            w(txt, "Arithmetic\n", "h2")
            for op, d in [("+","Addition"),("-","Subtraction"),("*","Multiplication"),("/","Integer Division"),("-x","Unary minus")]:
                w(txt, f"    {op:<6}", "code"); w(txt, f"  {d}\n", "dim")
            w(txt, "\nAssignment\n", "h2")
            for op, d in [("=","Simple assignment"),("+=","Add and assign"),("-=","Subtract and assign"),("++","Increment"),("--","Decrement")]:
                w(txt, f"    {op:<6}", "code"); w(txt, f"  {d}\n", "dim")
            w(txt, "\nPrecedence (mataas → mababa)\n", "h2")
            for n, r in [("1","( )  — Parentheses"),("2","-x  — Unary minus"),("3","*  /  — Multiply, Divide"),("4","+  -  — Add, Subtract")]:
                w(txt, f"    {n}. {r}\n", "code")

        # ipakita
        def build_ipakita(txt):
            w(txt, "ipakita — Output Statement\n\n", "h1")
            w(txt, "Sintaks: ")
            w(txt, "ipakita", "kw"); w(txt, "(argumento)\n\n")
            w(txt, "Variable (bilang)\n", "h2")
            w(txt, "    ipakita(x)        → prints integer value\n", "code")
            w(txt, "Variable (titik)\n", "h2")
            w(txt, "    ipakita(letra)    → prints the actual character\n", "code")
            w(txt, "Expression\n", "h2")
            w(txt, "    ipakita(10 + 5)   → prints 15\n    ipakita(x * 2)    → prints x*2\n", "code")
            w(txt, "Character literal\n", "h2")
            w(txt, "    ipakita('W')      → prints W\n\n", "code")
            w(txt, "EduMIPS64 SYSCALL\n", "h2")
            w(txt, "    SYSCALL 1   — print integer (value in r14)\n"
                   "    SYSCALL 11  — print character (ASCII in r14)\n"
                   "    SYSCALL 0   — exit / halt (end of program)\n\n", "code")

        # Examples
        def build_examples(txt):
            w(txt, "Mga Halimbawa\n\n", "h1")
            examples = [
                ("Basic bilang", "simula\nbilang a = 10, b = 3\nbilang c\nc = a + b\nipakita(c)\ntapos", "13"),
                ("Titik ASCII arithmetic", "simula\ntitik c = 'A'\nc++\nipakita(c)\ntapos", "B"),
                ("Compound assignment", "simula\nbilang score = 0\nscore += 10\nscore += 5\nscore--\nipakita(score)\ntapos", "14"),
                ("Expressions", "simula\nipakita(100 + 200)\nipakita(10 * 10)\nipakita((5 + 3) * 2)\ntapos", "300\n100\n16"),
            ]
            for title, code, output in examples:
                w(txt, f"{title}\n", "h2")
                for line in code.split("\n"):
                    w(txt, f"    {line}\n", "code")
                w(txt, "\n  Output:\n", "dim")
                for line in output.split("\n"):
                    w(txt, f"    {line}\n", "num")
                w(txt, "\n")

        # Shortcuts
        def build_shortcuts(txt):
            w(txt, "Keyboard Shortcuts\n\n", "h1")
            groups = [
                ("File", [("Ctrl+N","New"),("Ctrl+O","Open"),("Ctrl+S","Save")]),
                ("Run",  [("Ctrl+R","Run the WIKA program")]),
                ("Font", [("Ctrl+=","Bigger font"),("Ctrl+-","Smaller font"),("Ctrl+Scroll","Zoom")]),
            ]
            for grp, items in groups:
                w(txt, f"{grp}\n", "h2")
                for k, d in items:
                    w(txt, f"    {k:<20}", "acc"); w(txt, f"  {d}\n")
                w(txt, "\n")
            w(txt, "Panels\n", "h2")
            w(txt, "    ✅ Output       — Actual values printed by ipakita\n"
                   "    ⚙️  MIPS        — Full EduMIPS64 assembly (.data + .code)\n"
                   "    🔢 Hex & Binary — Machine code encoding per instruction\n\n", "dim")
            w(txt, "Nathaniel B. Ministros  |  CSC 112 BNO1  |  WIKA IDE v2.0\n", "bold")

        builders = {
            TABS[0]: build_overview,
            TABS[1]: build_types,
            TABS[2]: build_operators,
            TABS[3]: build_ipakita,
            TABS[4]: build_examples,
            TABS[5]: build_shortcuts,
        }

        tab_btns = {}
        for tab in TABS:
            frame, txt = make_text()
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_remove()
            builders[tab](txt)
            tab_frames[tab] = frame

        def switch_tab(tab):
            for f in tab_frames.values():
                f.grid_remove()
            tab_frames[tab].grid()
            active_tab.set(tab)
            for t, btn in tab_btns.items():
                btn.configure(
                    fg_color=c["accent"] if t == tab else c["bg_button"],
                    text_color="#1E1E2E" if t == tab else fg,
                )

        for i, tab in enumerate(TABS):
            btn = ctk.CTkButton(
                tab_bar, text=tab, width=118, height=36, corner_radius=6,
                fg_color=c["bg_button"], text_color=fg,
                command=lambda t=tab: switch_tab(t),
            )
            btn.grid(row=0, column=i, padx=(8 if i == 0 else 2, 2), pady=4)
            tab_btns[tab] = btn

        ctk.CTkButton(
            tab_bar, text="✕ Isara", width=80, height=36, corner_radius=6,
            fg_color="transparent", text_color=c["error_fg"],
            hover_color=c["bg_button"], command=win.destroy,
        ).grid(row=0, column=len(TABS), padx=(8, 8), pady=4, sticky="e")
        tab_bar.grid_columnconfigure(len(TABS), weight=1)

        switch_tab(TABS[0])

    # ── Theme ─────────────────────────────────────────────────
    def _toggle_theme(self):
        new_theme = "light" if self.settings["theme"] == "dark" else "dark"
        self.settings["theme"] = new_theme
        self.colors = DARK_COLORS if new_theme == "dark" else LIGHT_COLORS
        ctk.set_appearance_mode(new_theme)
        self.theme_btn.configure(
            text="☀ Light" if new_theme == "dark" else "🌙 Dark")
        self._apply_theme()

    def _apply_theme(self):
        c = self.colors
        self.editor.configure(bg=c["bg_editor"], fg=c["fg_text"],
                              insertbackground=c["accent"])
        self.output_box.configure(bg=c["out_bg"], fg=c["out_fg"])
        self.output_box.tag_config("error",   foreground=c["error_fg"])
        self.output_box.tag_config("success", foreground=c["success_fg"])
        self.mips_box.configure(bg=c["mips_bg"], fg=c["mips_fg"])
        self.hex_box.configure(bg=c["hex_bg"], fg=c["hex_fg"])
        self._setup_mips_tags()
        self._setup_hex_tags()
        self.ln_updater.update_colors(c)
        self._apply_syntax_tag_colors()

    # ── Font ─────────────────────────────────────────────────
    def _font_size_change(self, delta):
        size = max(8, min(32, self.settings["font_size"] + delta))
        self.settings["font_size"] = size
        self.font_size_label.configure(text=str(size))
        self._apply_font()

    def _change_font_family(self, family):
        self.settings["font_family"] = family
        self._apply_font()

    def _apply_font(self):
        f  = self.settings["font_family"]
        sz = self.settings["font_size"]
        self.editor.configure(font=(f, sz))
        self.output_box.configure(font=(f, sz - 1))
        self.mips_box.configure(font=(f, sz - 1))
        self.hex_box.configure(font=(f, sz - 1))
        self.ln_updater.update_font(f, sz)
        self._apply_syntax_tag_colors()

    def _zoom_scroll(self, event):
        self._font_size_change(1 if event.delta > 0 else -1)

    # ── Editor helpers ────────────────────────────────────────
    def _on_key(self, event=None):
        self._update_line_col()

    def _update_line_col(self, event=None):
        pos  = self.editor.index("insert")
        line, col = pos.split(".")
        self.lc_label.configure(text=f"Ln {line}, Col {int(col)+1}")

    def _auto_indent(self, event=None):
        cur = self.editor.get("insert linestart", "insert")
        indent = len(cur) - len(cur.lstrip())
        self.editor.insert("insert", "\n" + " " * indent)
        return "break"

    def _insert_tab(self, event=None):
        self.editor.insert("insert", "    ")
        return "break"

    def _load_starter_code(self):
        starter = """\
simula
# Halimbawa ng WIKA program

bilang x = 5, y = 10
titik letra = 'A'

x = x + y
ipakita(x)
ipakita(letra)
tapos"""
        self.editor.insert("1.0", starter)


# ── Entry point ──────────────────────────────────────────────
if __name__ == "__main__":
    app = WikaIDE()
    app.mainloop()