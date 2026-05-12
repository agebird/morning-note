#!/opt/homebrew/bin/python3.12
"""Morning Note — tkinter desktop app.

Sell-side equity research morning meeting note generator.
Manages a coverage universe of companies and generates reports via Claude CLI.
"""

import sys
import pickle  # save sash positions

# System Python 3.9 (from Xcode CLT) has a broken tkinter on macOS 26+.
# Require Homebrew Python 3.12+ (the shebang at line 1 handles this).
MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    print(
        f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required (found {sys.version}).\n"
        "Run with Homebrew Python instead:\n"
        "  /opt/homebrew/bin/python3.12 /Users/patrickge/晨会/app.py"
    )
    sys.exit(1)

import json
import os
import re
import shutil
import subprocess
import threading
from datetime import date
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime

# ── paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
COMPANIES_FILE = BASE_DIR / "companies.json"
NOTES_DIR = BASE_DIR / "notes"
NOTES_INDEX = NOTES_DIR / "index.json"
SASH_FILE = BASE_DIR / ".sashpos"
PLUGIN_DIR = Path(
    os.environ.get(
        "MORNING_NOTE_PLUGIN_DIR",
        "/Users/patrickge/financial-services/plugins/vertical-plugins/equity-research",
    )
)
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", shutil.which("claude") or "claude")

# ── data helpers ─────────────────────────────────────────────────────

def load_companies():
    if not COMPANIES_FILE.exists():
        return []
    try:
        data = json.loads(COMPANIES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_companies(companies):
    tmp = COMPANIES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(COMPANIES_FILE)


def load_notes_index():
    if not NOTES_INDEX.exists():
        return []
    try:
        data = json.loads(NOTES_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_notes_index(index):
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = NOTES_INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(NOTES_INDEX)


def add_note(markdown: str, tickers: list[str]) -> str:
    """Save a generated note to disk and update index. Returns filename."""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    filename = now.strftime("%Y-%m-%d_%H%M") + ".md"
    filepath = NOTES_DIR / filename
    filepath.write_text(markdown, encoding="utf-8")

    index = load_notes_index()
    index.insert(0, {
        "file": filename,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "tickers": sorted(tickers),
        "label": f"{now.strftime('%m-%d %H:%M')}  {' '.join(sorted(tickers))}",
    })
    save_notes_index(index)
    return filename


def delete_note_file(filename: str):
    path = NOTES_DIR / filename
    if path.exists():
        path.unlink()
    index = [e for e in load_notes_index() if e["file"] != filename]
    save_notes_index(index)


# ── tkinter app ──────────────────────────────────────────────────────

class MorningNoteApp:
    FIELD_LABELS = {
        "name": "公司名称",
        "sector": "所属行业",
        "rating": "评级",
        "target_price": "目标价",
    }

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Morning Note — Coverage Universe")
        self.root.geometry("1200x720")
        self.root.minsize(900, 500)

        # Apple-dark title bar on macOS
        try:
            self.root.tk.call("::tk::unsupported::MacWindowStyle", "style",
                              self.root._w, "titleBar", "normal")
        except Exception:
            pass

        self.companies = load_companies()
        self.is_generating = False
        self.current_note_file = None

        NOTES_DIR.mkdir(parents=True, exist_ok=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._refresh_list()
        self._refresh_tags()
        self._refresh_notes_list()

    # ── build UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        # sash widths (sensible defaults)
        self._sash0 = 320  # left panel width
        self._sash1 = 580  # left + center width
        self._load_sash_positions()

        # Main paned window — 3 panes: left(middle) | center(notes) | right(report)
        self.pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.pane.pack(fill=tk.BOTH, expand=True)

        # ══ left panel: watchlist ══════════════════════════════════
        self.left = ttk.Frame(self.pane, width=320)
        self.pane.add(self.left, weight=0)

        hdr = ttk.Frame(self.left)
        hdr.pack(fill=tk.X, padx=14, pady=(14, 0))
        ttk.Label(hdr, text="自选股", font=("", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(hdr, text="Watchlist",
                  font=("", 10), foreground="gray").pack(anchor=tk.W)

        add_frame = ttk.Frame(self.left)
        add_frame.pack(fill=tk.X, padx=10, pady=(12, 0))
        self.add_entry = ttk.Entry(add_frame, font=("", 12))
        self.add_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.add_entry.insert(0, "输入代码后回车添加")
        self.add_entry.bind("<FocusIn>", lambda e: self.add_entry.delete(0, tk.END) if self.add_entry.get() == "输入代码后回车添加" else None)
        self.add_entry.bind("<Return>", lambda e: self._quick_add())
        add_btn = ttk.Button(add_frame, text="＋ 添加", width=8, command=self._quick_add)
        add_btn.pack(side=tk.RIGHT, padx=(6, 0))

        list_frame = ttk.LabelFrame(self.left, text="自选股列表", padding=4)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 10))
        tree_frame = ttk.Frame(list_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(
            tree_frame, columns=("ticker", "name"),
            show="tree", selectmode="browse", height=16,
        )
        self.tree.column("#0", width=0, stretch=False)
        self.tree.heading("ticker", text="代码")
        self.tree.column("ticker", width=60, minwidth=50)
        self.tree.heading("name", text="名称")
        self.tree.column("name", width=180, minwidth=100)
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", lambda e: self._edit_dialog())
        self.tree.bind("<Delete>", lambda e: self._delete_selected())
        act_row = ttk.Frame(list_frame)
        act_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(act_row, text="编辑", command=self._edit_dialog).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(act_row, text="删除", command=self._delete_selected).pack(side=tk.LEFT)

        # ══ center panel: notes list ═══════════════════════════════
        self.center = ttk.Frame(self.pane, width=260)
        self.pane.add(self.center, weight=0)

        center_hdr = ttk.Frame(self.center)
        center_hdr.pack(fill=tk.X, padx=10, pady=(14, 8))
        ttk.Label(center_hdr, text="晨会纪要", font=("", 14, "bold")).pack(anchor=tk.W)
        self.notes_count = ttk.Label(center_hdr, text="", font=("", 10), foreground="gray")
        self.notes_count.pack(anchor=tk.W)

        notes_list_frame = ttk.Frame(self.center)
        notes_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.notes_listbox = tk.Listbox(
            notes_list_frame, font=("", 11),
            selectbackground="#e8f0fe", selectforeground="#000",
            activestyle="none", borderwidth=0, highlightthickness=0,
        )
        nsb = ttk.Scrollbar(notes_list_frame, orient=tk.VERTICAL, command=self.notes_listbox.yview)
        self.notes_listbox.configure(yscrollcommand=nsb.set)
        self.notes_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        nsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.notes_listbox.bind("<<ListboxSelect>>", self._on_note_selected)
        self.notes_listbox.bind("<Delete>", lambda e: self._delete_selected_note())

        # note action buttons
        nact_row = ttk.Frame(self.center)
        nact_row.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(nact_row, text="删除", command=self._delete_selected_note).pack(side=tk.LEFT)
        ttk.Button(nact_row, text="刷新", command=self._refresh_notes_list).pack(side=tk.LEFT, padx=(4, 0))

        # ══ right panel: report ════════════════════════════════════
        self.right = ttk.Frame(self.pane)
        self.pane.add(self.right, weight=1)

        top = ttk.Frame(self.right)
        top.pack(fill=tk.X, padx=14, pady=(14, 8))

        top_left = ttk.Frame(top)
        top_left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(top_left, text="Daily Morning Note",
                  font=("", 14, "bold")).pack(anchor=tk.W)
        self.tags_frame = ttk.Frame(top_left)
        self.tags_frame.pack(anchor=tk.W, pady=(4, 0))

        self.gen_btn = ttk.Button(top, text="Generate Morning Note",
                                  command=self._generate)
        self.gen_btn.pack(side=tk.RIGHT)

        # report area
        self.report_frame = ttk.Frame(self.right)
        self.report_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        # placeholder
        self.placeholder = ttk.Frame(self.report_frame)
        self.placeholder.pack(fill=tk.BOTH, expand=True)
        self.placeholder.grid_columnconfigure(0, weight=1)
        self.placeholder.grid_rowconfigure(0, weight=1)
        ph = ttk.Frame(self.placeholder)
        ph.grid(row=0, column=0)
        ttk.Label(ph, text="📄", font=("", 40)).pack()
        ttk.Label(ph, text="No report yet", font=("", 13, "bold")).pack(pady=(4, 0))
        ttk.Label(ph, text='Add companies and click "Generate Morning Note"\nto create a sell-side research report.',
                  foreground="gray", justify=tk.CENTER).pack(pady=(4, 0))

        # report card
        self.report_card = ttk.Frame(self.report_frame)
        self.report_toolbar = ttk.Frame(self.report_card)
        self.report_toolbar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(self.report_toolbar, text="Copy", command=self._copy_report).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(self.report_toolbar, text="Download .md", command=self._download_report).pack(side=tk.RIGHT, padx=(4, 0))
        self.regen_btn = ttk.Button(self.report_toolbar, text="Regenerate",
                                    command=self._generate)
        self.regen_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self.report_text = scrolledtext.ScrolledText(
            self.report_card, wrap=tk.WORD, font=("SF Mono", 12),
            bg="#ffffff", relief=tk.FLAT, borderwidth=1,
            padx=16, pady=16,
        )
        self.report_text.pack(fill=tk.BOTH, expand=True)

        # custom tags for markdown rendering
        self.report_text.tag_configure("h1", font=("", 18, "bold"), spacing3=8)
        self.report_text.tag_configure("h2", font=("", 15, "bold"), spacing3=6)
        self.report_text.tag_configure("h3", font=("", 13, "bold"), spacing3=4)
        self.report_text.tag_configure("bold", font=("", 12, "bold"))
        self.report_text.tag_configure("italic", font=("", 12, "italic"))
        self.report_text.tag_configure("code", font=("SF Mono", 11),
                                       background="#f0f0f0", lmargin2=8)
        self.report_text.tag_configure("hr", foreground="#ccc", font=("", 8))
        self.report_text.tag_configure("bullet", lmargin1=12, lmargin2=20)
        self.report_text.tag_configure("table", font=("SF Mono", 11))

        # status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               relief=tk.SUNKEN, anchor=tk.W, padding=(8, 2))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # save sash when user drags; apply positions after window mapped
        self.pane.bind("<ButtonRelease-1>", lambda e: self._save_sash_positions())
        self.root.after(50, self._apply_sash_positions)

    # ── sash position persistence ────────────────────────────────────

    def _load_sash_positions(self):
        try:
            if SASH_FILE.exists():
                data = pickle.loads(SASH_FILE.read_bytes())
                self._sash0, self._sash1 = data
        except Exception:
            pass

    def _save_sash_positions(self):
        try:
            # read current positions from the widget
            s0 = self.pane.sashpos(0)
            s1 = self.pane.sashpos(1)
            SASH_FILE.write_bytes(pickle.dumps((s0, s1)))
        except Exception:
            pass

    def _apply_sash_positions(self):
        try:
            self.pane.sashpos(0, self._sash0)
            self.pane.sashpos(1, self._sash1)
        except Exception:
            pass

    # ── quick-add ────────────────────────────────────────────────────

    @staticmethod
    def _validate_number(value):
        if not value:
            return True
        try:
            float(value)
            return True
        except ValueError:
            return False

    def _quick_add(self):
        raw = self.add_entry.get().strip().upper()
        if not raw or raw == "输入代码后回车添加":
            return
        ticker = raw
        if any(c["ticker"] == ticker for c in self.companies):
            self.status_var.set(f"{ticker} 已在自选股中")
            self.add_entry.delete(0, tk.END)
            return
        self.companies.append({"ticker": ticker, "name": ticker,
                                "sector": "", "rating": "", "target_price": None})
        save_companies(self.companies)
        self.add_entry.delete(0, tk.END)
        self._refresh_list()
        self._refresh_tags()
        self.status_var.set(f"已添加 {ticker}")

    # ── edit dialog ──────────────────────────────────────────────────

    def _edit_dialog(self):
        ticker = self._get_selected_ticker()
        if not ticker:
            return
        c = next((x for x in self.companies if x["ticker"] == ticker), None)
        if not c:
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(f"编辑 {ticker}")
        dlg.geometry("360x280")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        fields = {}
        row = 0
        for key in ("name", "sector", "rating", "target_price"):
            lbl = self.FIELD_LABELS.get(key, key)
            ttk.Label(dlg, text=lbl).grid(row=row, column=0, sticky=tk.W, padx=12, pady=(8, 2))
            val = c.get(key, "")
            if key == "target_price":
                val = str(val) if val is not None else ""
                vcmd = (self.root.register(self._validate_number), "%P")
                entry = ttk.Entry(dlg, validate="key", validatecommand=vcmd)
            else:
                entry = ttk.Entry(dlg)
            entry.insert(0, val)
            entry.grid(row=row, column=1, sticky=tk.EW, padx=(0, 12), pady=(8, 2))
            fields[key] = entry
            row += 1

        dlg.columnconfigure(1, weight=1)

        def save():
            for key, entry in fields.items():
                val = entry.get().strip()
                if key == "target_price":
                    c[key] = float(val) if val else None
                else:
                    c[key] = val
            save_companies(self.companies)
            self._refresh_list()
            self._refresh_tags()
            self.status_var.set(f"已更新 {ticker}")
            dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.grid(row=row, column=0, columnspan=2, pady=12)
        ttk.Button(btn_row, text="保存", command=save).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="取消", command=dlg.destroy).pack(side=tk.LEFT)

    # ── treeview helpers ─────────────────────────────────────────────

    def _refresh_list(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for c in self.companies:
            self.tree.insert("", tk.END, values=(c["ticker"], c["name"]))

    def _refresh_tags(self):
        for w in self.tags_frame.winfo_children():
            w.destroy()
        for c in self.companies:
            lbl = ttk.Label(self.tags_frame, text=c["ticker"],
                            background="#e8f0fe", foreground="#1a73e8",
                            font=("", 10, "bold"), padding=(8, 2))
            lbl.pack(side=tk.LEFT, padx=(0, 4))

    def _get_selected_ticker(self):
        sel = self.tree.selection()
        if not sel:
            return None
        values = self.tree.item(sel[0], "values")
        return values[0] if values else None

    def _delete_selected(self):
        ticker = self._get_selected_ticker()
        if not ticker:
            return
        if not messagebox.askyesno("确认", f"从自选股中移除 {ticker}？"):
            return
        self.companies = [c for c in self.companies if c["ticker"] != ticker]
        save_companies(self.companies)
        self._refresh_list()
        self._refresh_tags()
        self.status_var.set(f"已移除 {ticker}")

    # ── report display ───────────────────────────────────────────────

    def _show_placeholder(self):
        self.placeholder.pack(fill=tk.BOTH, expand=True)
        self.report_card.pack_forget()

    def _show_report(self, markdown):
        self.placeholder.pack_forget()
        self.report_card.pack(fill=tk.BOTH, expand=True)
        self.report_text.configure(state=tk.NORMAL)
        self.report_text.delete("1.0", tk.END)
        self._render_markdown(markdown)
        self.report_text.configure(state=tk.DISABLED)
        self.report_text.markdown = markdown

    # ── simple markdown renderer ─────────────────────────────────────

    def _render_markdown(self, md):
        text = self.report_text
        for line in md.split("\n"):
            stripped = line.strip()

            # horizontal rule
            if re.match(r"^-{3,}$", stripped) or re.match(r"^\*{3,}$", stripped):
                text.insert(tk.END, "─" * 60 + "\n", "hr")
                continue

            # headers
            hm = re.match(r"^(#{1,3})\s+(.+)$", stripped)
            if hm:
                level = len(hm.group(1))
                content = hm.group(2)
                tag = f"h{level}"
                text.insert(tk.END, content + "\n", tag)
                continue

            # bullet points
            bm = re.match(r"^[\*\-\+]\s+(.+)$", stripped)
            if bm:
                self._render_inline(text, "  •  " + bm.group(1) + "\n", "bullet")
                continue

            # numbered list
            nm = re.match(r"^\d+[\.\)]\s+(.+)$", stripped)
            if nm:
                self._render_inline(text, line + "\n", "bullet")
                continue

            # table rows (pipe-delimited)
            if "|" in stripped and re.search(r"\|.*\|", stripped):
                text.insert(tk.END, stripped + "\n", "table")
                continue

            # empty line
            if not stripped:
                text.insert(tk.END, "\n")
                continue

            # normal paragraph with inline formatting
            self._render_inline(text, line + "\n")

    def _render_inline(self, text, line, default_tag=None):
        """Insert line with **bold**, *italic*, and `code` formatting."""
        pattern = r"\*\*(.+?)\*\*|`(.+?)`|\*(.+?)\*"
        pos = 0
        for m in re.finditer(pattern, line):
            if m.start() > pos:
                text.insert(tk.END, line[pos:m.start()], default_tag)
            if m.group(1) is not None:      # **bold**
                text.insert(tk.END, m.group(1), "bold")
            elif m.group(2) is not None:    # `code`
                text.insert(tk.END, m.group(2), "code")
            elif m.group(3) is not None:    # *italic*
                text.insert(tk.END, m.group(3), "italic")
            pos = m.end()
        if pos < len(line):
            text.insert(tk.END, line[pos:], default_tag)

    # ── notes list ───────────────────────────────────────────────────

    def _refresh_notes_list(self):
        self.notes_listbox.delete(0, tk.END)
        index = load_notes_index()
        self._notes_index = index  # cache for lookups
        if not index:
            self.notes_listbox.insert(tk.END, "(暂无晨会纪要)")
            self.notes_count.configure(text="0 篇")
            return
        for entry in index:
            self.notes_listbox.insert(tk.END, entry["label"])
        self.notes_count.configure(text=f"{len(index)} 篇")

    def _on_note_selected(self, event):
        sel = self.notes_listbox.curselection()
        if not sel or not hasattr(self, "_notes_index"):
            return
        idx = sel[0]
        if idx >= len(self._notes_index):
            return
        entry = self._notes_index[idx]
        filepath = NOTES_DIR / entry["file"]
        if not filepath.exists():
            messagebox.showerror("错误", f"文件不存在: {entry['file']}")
            self._refresh_notes_list()
            return
        md = filepath.read_text(encoding="utf-8")
        self.current_note_file = entry["file"]
        self._show_report(md)

    def _delete_selected_note(self):
        sel = self.notes_listbox.curselection()
        if not sel or not hasattr(self, "_notes_index"):
            return
        idx = sel[0]
        if idx >= len(self._notes_index):
            return
        entry = self._notes_index[idx]
        if not messagebox.askyesno("确认", f"删除 {entry['label']}？"):
            return
        delete_note_file(entry["file"])
        if self.current_note_file == entry["file"]:
            self.current_note_file = None
            self._show_placeholder()
        self._refresh_notes_list()
        self.status_var.set(f"已删除 {entry['label']}")

    # ── generate ─────────────────────────────────────────────────────

    def _build_prompt(self):
        today = date.today().isoformat()
        tickers = ", ".join(c["ticker"] for c in self.companies)
        lines = [
            f"Write a morning meeting note for today ({today}) covering: {tickers}.",
            "",
            "Coverage Universe:",
        ]
        for c in self.companies:
            parts = [f"{c['ticker']} ({c['name']})"]
            if c.get("sector"):
                parts.append(c["sector"])
            if c.get("rating"):
                parts.append(f"rating: {c['rating']}")
            tp = c.get("target_price")
            if tp is not None:
                parts.append(f"target: ${tp:.2f}")
            lines.append("- " + ", ".join(parts))
        lines.extend([
            "",
            "Use the morning meeting note format:",
            "1. **Top Call** — the one thing PMs need to hear today",
            "2. **Overnight / Pre-Market Developments** — key news per company with our take",
            "3. **Key Events Today** — earnings, economic data, conferences",
            "4. **Trade Ideas** — actionable long/short recommendations with catalysts and risks",
            "",
            "Requirements:",
            "- Be opinionated and concise (readable in 2 minutes)",
            "- Lead with the most important point",
            "- If nothing material happened, say so explicitly",
            "- Use web search to find latest news on each company",
            "- Output the COMPLETE morning note in Markdown now, no preamble or summary.",
        ])
        return "\n".join(lines)

    def _generate(self):
        if self.is_generating:
            return
        if not self.companies:
            messagebox.showinfo("No Companies", "Add at least one company first.")
            return

        self.is_generating = True
        self.gen_btn.configure(state=tk.DISABLED, text="Generating...")
        self.status_var.set("Generating morning note via Claude CLI...")
        self._show_placeholder()

        prompt = self._build_prompt()
        threading.Thread(target=self._run_claude, args=(prompt,), daemon=True).start()

    def _run_claude(self, prompt):
        # Unset CLAUDECODE to prevent "nested session" error
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        try:
            result = subprocess.run(
                [CLAUDE_BIN, "-p", prompt, "--print",
                 "--dangerously-skip-permissions"],
                capture_output=True, text=True, timeout=600, env=env,
            )
        except FileNotFoundError:
            self.root.after(0, self._generation_error,
                            f"Claude CLI not found at '{CLAUDE_BIN}'")
            return
        except subprocess.TimeoutExpired:
            self.root.after(0, self._generation_error,
                            "Request timed out after 600s. Try fewer companies.")
            return

        if result.returncode != 0:
            err = (result.stderr or "").strip()
            self.root.after(0, self._generation_error,
                            f"Claude CLI exited with code {result.returncode}",
                            err or None)
            return

        output = (result.stdout or "").strip()
        if not output:
            self.root.after(0, self._generation_error, "Claude returned empty output.")
            return

        self.root.after(0, self._generation_done, output)

    def _generation_done(self, markdown):
        self.is_generating = False
        self.gen_btn.configure(state=tk.NORMAL, text="Generate Morning Note")
        tickers = [c["ticker"] for c in self.companies]
        filename = add_note(markdown, tickers)
        self.current_note_file = filename
        self._show_report(markdown)
        self._refresh_notes_list()
        # select the newly added note in the list
        for i, entry in enumerate(self._notes_index):
            if entry["file"] == filename:
                self.notes_listbox.selection_set(i)
                self.notes_listbox.see(i)
                break
        self.status_var.set(f"报告已生成 — {filename.replace('.md','')}")

    def _generation_error(self, msg, detail=None):
        self.is_generating = False
        self.gen_btn.configure(state=tk.NORMAL, text="Generate Morning Note")
        full = msg
        if detail:
            full += f"\n\n{detail}"
        messagebox.showerror("Generation Failed", full)
        self.status_var.set("Generation failed")
        self._show_placeholder()

    # ── copy / download ──────────────────────────────────────────────

    def _copy_report(self):
        md = getattr(self.report_text, "markdown", None)
        if not md:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(md)
        self.status_var.set("Copied to clipboard")

    def _download_report(self):
        md = getattr(self.report_text, "markdown", None)
        if not md:
            return
        filename = f"morning-note-{date.today().isoformat()}.md"
        path = BASE_DIR / filename
        try:
            path.write_text(md, encoding="utf-8")
            self.status_var.set(f"Saved to {filename}")
        except OSError as e:
            messagebox.showerror("Save Failed", str(e))

    # ── run / close ──────────────────────────────────────────────────

    def _on_close(self):
        self._save_sash_positions()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ── entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    app = MorningNoteApp()
    app.run()
