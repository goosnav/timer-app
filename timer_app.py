import json
import math
import struct
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter import font as tkfont

try:
    import winsound  # type: ignore
except ImportError:  # pragma: no cover - platform specific
    winsound = None

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    pystray = None
    Image = None
    ImageDraw = None

try:
    import simpleaudio as sa  # type: ignore
except ImportError:  # pragma: no cover
    sa = None

CONFIG_FILE = Path(__file__).with_name("timer_config.json")


class CountdownTimer:
    """Logic controller for the countdown timer."""

    def __init__(self, duration_s: int = 0) -> None:
        self.duration = timedelta(seconds=duration_s)
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.paused = True
        self.pause_time: Optional[datetime] = None
        self._finished = False

    def set_duration(self, seconds: int) -> None:
        self.duration = timedelta(seconds=max(0, seconds))
        self.reset()

    def start(self) -> None:
        now = datetime.now()
        self.start_time = now
        self.end_time = now + self.duration
        self.paused = False
        self.pause_time = None
        self._finished = False

    def pause(self) -> None:
        if self.start_time and not self.paused:
            self.paused = True
            self.pause_time = datetime.now()

    def resume(self) -> None:
        if self.start_time and self.paused:
            now = datetime.now()
            if self.pause_time and self.end_time and self.start_time:
                paused_delta = now - self.pause_time
                self.start_time += paused_delta
                self.end_time += paused_delta
            self.paused = False
            self.pause_time = None

    def reset(self) -> None:
        self.paused = True
        self.pause_time = None
        self.start_time = None
        self.end_time = None
        self._finished = False

    def add_time(self, seconds: int) -> None:
        if seconds <= 0:
            return
        self._finished = False
        if self.start_time and self.end_time:
            self.end_time += timedelta(seconds=seconds)
        else:
            self.duration += timedelta(seconds=seconds)

    def is_running(self) -> bool:
        return self.start_time is not None and not self.paused and not self._finished

    def has_finished(self) -> bool:
        return self._finished

    def _compute_state(self, reference: Optional[datetime] = None) -> dict:
        now = reference or datetime.now()
        if not self.start_time or not self.end_time:
            total_seconds = max(int(self.duration.total_seconds()), 0)
            return {
                "remaining": timedelta(seconds=total_seconds),
                "progress": 0.0,
                "total": timedelta(seconds=total_seconds),
                "now": now,
                "end": now + timedelta(seconds=total_seconds),
            }

        effective_now = self.pause_time if self.paused and self.pause_time else now
        remaining = self.end_time - effective_now
        total = self.end_time - self.start_time
        if remaining.total_seconds() <= 0:
            remaining = timedelta(seconds=0)
            self._finished = True
            self.paused = True
        elapsed = total - remaining
        total_seconds = max(total.total_seconds(), 1)
        progress = min(max(elapsed.total_seconds() / total_seconds, 0.0), 1.0)
        return {
            "remaining": remaining,
            "progress": progress,
            "total": total,
            "now": effective_now,
            "end": self.end_time,
        }

    def update(self) -> dict:
        return self._compute_state()


class TimeInput(tk.Entry):
    """Specialized entry widget that behaves like a digital time input."""

    MAX_SECONDS = 99 * 3600 + 59 * 60 + 59

    def __init__(
        self,
        master: tk.Widget,
        *,
        initial: str = "00:05:00",
        font: Optional[tkfont.Font] = None,
        command=None,
        **kwargs,
    ) -> None:
        self._var = tk.StringVar()
        super().__init__(
            master,
            textvariable=self._var,
            justify="center",
            relief="sunken",
            bd=2,
            highlightthickness=0,
            **kwargs,
        )
        self._digits = ["0"] * 6
        self._command = command
        if font is not None:
            self.configure(font=font)
        self.set_formatted(initial)
        self.bind("<KeyPress>", self._on_keypress)
        self.bind("<KeyRelease>", self._squelch_typing)
        self.bind("<FocusIn>", self._handle_focus)
        self.configure(insertontime=0, insertofftime=0)

    def _handle_focus(self, _event: tk.Event) -> None:
        self.icursor(tk.END)

    def _squelch_typing(self, _event: tk.Event) -> str:
        """Prevent default text editing behaviours."""
        return "break"

    def _notify(self) -> None:
        if self._command:
            self._command()

    def _on_keypress(self, event: tk.Event) -> Optional[str]:
        keysym = getattr(event, "keysym", "")
        char = getattr(event, "char", "")
        if keysym in {"Tab", "Shift_L", "Shift_R", "Control_L", "Control_R"}:
            return None
        if keysym == "BackSpace":
            self._digits = ["0"] + self._digits[:-1]
            self._update_display()
            self._notify()
            return "break"
        if keysym == "Delete":
            self.clear()
            self._notify()
            return "break"
        if keysym == "Return":
            self._notify()
            return "break"
        if keysym in {"Up", "Down"}:
            delta = 60 if keysym == "Up" else -60
            self.set_seconds(self.get_seconds() + delta)
            self._notify()
            return "break"
        if char.isdigit():
            self._digits = self._digits[1:] + [char]
            self._update_display()
            self._notify()
            return "break"
        return "break"

    def _update_display(self) -> None:
        text = f"{self._digits[0]}{self._digits[1]}:{self._digits[2]}{self._digits[3]}:{self._digits[4]}{self._digits[5]}"
        self._var.set(text)

    def set_seconds(self, seconds: int) -> None:
        total = max(0, min(int(seconds), self.MAX_SECONDS))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        self._digits = list(f"{hours:02d}{minutes:02d}{secs:02d}")
        self._update_display()

    def get_seconds(self) -> int:
        hours = int("".join(self._digits[0:2]))
        minutes = int("".join(self._digits[2:4]))
        seconds = int("".join(self._digits[4:6]))
        return hours * 3600 + minutes * 60 + seconds

    def set_formatted(self, value: str) -> None:
        digits = [c for c in value if c.isdigit()]
        if len(digits) < 6:
            digits = ["0"] * (6 - len(digits)) + digits
        else:
            digits = digits[-6:]
        self._digits = digits
        self._update_display()

    def get_formatted(self) -> str:
        return self._var.get()

    def clear(self) -> None:
        self._digits = ["0"] * 6
        self._update_display()

    def set_font(self, font: tkfont.Font) -> None:
        self.configure(font=font)

class RetroProgressBar(tk.Canvas):
    """Canvas-based progress bar with Windows 2000 styling."""

    def __init__(
        self,
        master: tk.Widget,
        *,
        trough: str,
        fill: str,
        highlight: str,
        shadow: str,
        stripe: str,
        text_dark: str,
        text_light: str,
        font: tkfont.Font,
        height: int = 24,
    ) -> None:
        super().__init__(
            master,
            height=height,
            bg=trough,
            bd=2,
            relief="sunken",
            highlightthickness=0,
        )
        self._fraction = 0.0
        self._label = "0% Complete"
        self._font = font
        self._fill = fill
        self._highlight = highlight
        self._shadow = shadow
        self._stripe = stripe
        self._text_dark = text_dark
        self._text_light = text_light
        self.bind("<Configure>", self._redraw)

    def set_progress(self, fraction: float, label: Optional[str] = None) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        if label is not None:
            self._label = label
        self._redraw()

    def set_font(self, font: tkfont.Font) -> None:
        self._font = font
        self._redraw()

    def _redraw(self, _event: Optional[tk.Event] = None) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        fill_width = int(width * self._fraction)

        if fill_width > 0:
            self.create_rectangle(0, 0, fill_width, height, fill=self._fill, outline=self._shadow)
            # Add stripes to mimic the Windows 2000 progress bar
            for x in range(-fill_width, fill_width, 12):
                stripe_x = x + (fill_width % 12)
                if stripe_x < fill_width:
                    self.create_rectangle(
                        stripe_x,
                        0,
                        min(stripe_x + 6, fill_width),
                        height,
                        fill=self._stripe,
                        outline="",
                    )

        self.create_line(0, 0, width, 0, fill=self._highlight)
        self.create_line(0, 0, 0, height, fill=self._highlight)
        self.create_line(0, height - 1, width, height - 1, fill=self._shadow)
        self.create_line(width - 1, 0, width - 1, height, fill=self._shadow)

        text_color = self._text_light if fill_width > width * 0.45 else self._text_dark
        self.create_text(
            width / 2,
            height / 2,
            text=self._label,
            fill=text_color,
            font=self._font,
        )


class CountdownGUI:
    """Tkinter-based GUI styled after a Windows 2000 utility."""

    WINDOW_BG = "#C0C0C0"
    PANEL_BG = "#D4D0C8"
    EDGE_LIGHT = "#FFFFFF"
    EDGE_DARK = "#404040"
    ACCENT = "#0A246A"
    ACCENT_LIGHT = "#3A6EA5"
    TEXT_DARK = "#000000"
    TEXT_SOFT = "#202020"
    FONT_FAMILY = "Tahoma"
    SAMPLE_RATE = 44100

    SOUND_PRESETS = {
        "Office Reminder": [((1046, 784), 220), ((), 90), ((1046, 784), 220), ((880,), 320)],
        "Meeting Alert": [((659, 988), 180), ((), 70), ((784, 1046), 220), ((659,), 260), ((988,), 320)],
        "Soft Pulse": [((523,), 180), ((), 60), ((659,), 180), ((), 60), ((784,), 280), ((), 80), ((523, 784), 220)],
        "Digital Sweep": [((440,), 140), ((554,), 140), ((659,), 140), ((880,), 220), ((1108,), 260)],
    }

    def __init__(self, master: tk.Tk, timer: CountdownTimer) -> None:
        self.master = master
        self.timer = timer
        self.master.title("Countdown Timer")
        self.master.configure(bg=self.EDGE_DARK)
        self.master.geometry("460x310")
        self.master.minsize(340, 220)
        self.master.attributes("-topmost", True)

        self.drag_offset = {"x": 0, "y": 0}
        self.compact_mode = tk.BooleanVar(value=False)
        self.remaining_var = tk.StringVar(value="00:00:00")
        self.compact_remaining_var = tk.StringVar(value="Time Left: 00:00:00")
        self.end_time_var = tk.StringVar(value="End Time: --:--:--")
        self.sound_var = tk.StringVar()
        self._completed = False
        self._audio_cache: dict[tuple, dict[str, bytes]] = {}

        self._config_data = {"last_duration": "00:05:00", "sound": "Office Reminder"}
        self._load_config()
        self.sound_var.set(self._config_data.get("sound", "Office Reminder"))

        self._setup_fonts()
        self._create_style()
        self._build_full_view()
        self._build_compact_view()
        self._create_tray_icon()
        self._bind_events()
        self._schedule_update()

    def _setup_fonts(self) -> None:
        self.fonts = {
            "small": tkfont.Font(family=self.FONT_FAMILY, size=9),
            "normal": tkfont.Font(family=self.FONT_FAMILY, size=10),
            "input": tkfont.Font(family=self.FONT_FAMILY, size=11),
            "timer": tkfont.Font(family=self.FONT_FAMILY, size=28, weight="bold"),
            "end": tkfont.Font(family=self.FONT_FAMILY, size=14, weight="bold"),
            "progress": tkfont.Font(family=self.FONT_FAMILY, size=11, weight="bold"),
            "compact": tkfont.Font(family=self.FONT_FAMILY, size=16, weight="bold"),
            "compact_info": tkfont.Font(family=self.FONT_FAMILY, size=11),
        }

    def _load_config(self) -> None:
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                self._config_data.update(
                    {
                        "last_duration": data.get("last_duration", self._config_data["last_duration"]),
                        "sound": data.get("sound", self._config_data["sound"]),
                    }
                )
            except json.JSONDecodeError:
                CONFIG_FILE.unlink(missing_ok=True)

    def _save_config(self) -> None:
        payload = {
            "last_duration": self.duration_input.get_formatted(),
            "sound": self.sound_var.get(),
        }
        CONFIG_FILE.write_text(json.dumps(payload, indent=2))

    def _create_style(self) -> None:
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("Win2000.TFrame", background=self.WINDOW_BG, borderwidth=0)
        self.style.configure(
            "Win2000.TLabel",
            background=self.WINDOW_BG,
            foreground=self.TEXT_DARK,
            font=self.fonts["normal"],
        )
        self.style.configure(
            "Win2000Accent.TLabel",
            background=self.PANEL_BG,
            foreground=self.TEXT_DARK,
            font=self.fonts["timer"],
        )
        self.style.configure(
            "Win2000.TButton",
            background=self.PANEL_BG,
            foreground=self.TEXT_DARK,
            font=self.fonts["normal"],
            relief="raised",
            padding=(10, 4),
        )
        self.style.map(
            "Win2000.TButton",
            background=[("active", self.EDGE_LIGHT)],
            relief=[("pressed", "sunken"), ("active", "raised")],
        )
        self.style.configure(
            "Win2000.TCheckbutton",
            background=self.WINDOW_BG,
            foreground=self.TEXT_DARK,
            font=self.fonts["normal"],
        )
        self.style.configure(
            "Win2000.TCombobox",
            fieldbackground="#FFFFFF",
            selectforeground=self.TEXT_DARK,
            selectbackground="#C6D0E1",
            foreground=self.TEXT_DARK,
            font=self.fonts["normal"],
        )

    def _build_full_view(self) -> None:
        self.full_frame = tk.Frame(self.master, bg=self.EDGE_DARK)
        self.full_frame.pack(expand=True, fill="both", padx=6, pady=6)

        raised = tk.Frame(self.full_frame, bg=self.EDGE_LIGHT, bd=2, relief="raised")
        raised.pack(expand=True, fill="both")

        inner = tk.Frame(raised, bg=self.WINDOW_BG, bd=2, relief="sunken")
        inner.pack(expand=True, fill="both", padx=2, pady=2)

        banner = tk.Frame(inner, bg=self.ACCENT, height=38, bd=0, relief="flat")
        banner.pack(fill="x", padx=6, pady=(6, 0))
        banner.columnconfigure(0, weight=1)
        tk.Label(
            banner,
            text="Countdown Timer",
            font=self.fonts["end"],
            foreground="#FFFFFF",
            background=self.ACCENT,
            anchor="w",
            padx=12,
        ).grid(row=0, column=0, sticky="ew")

        self.timer_panel = tk.Frame(inner, bg=self.PANEL_BG, bd=2, relief="sunken")
        self.timer_panel.pack(expand=True, fill="both", padx=10, pady=(8, 6))

        self.remaining_label = tk.Label(
            self.timer_panel,
            textvariable=self.remaining_var,
            font=self.fonts["timer"],
            background=self.PANEL_BG,
            foreground=self.TEXT_DARK,
        )
        self.remaining_label.pack(expand=True, fill="both", pady=(12, 8))

        self.end_time_label = tk.Label(
            self.timer_panel,
            textvariable=self.end_time_var,
            font=self.fonts["end"],
            background=self.PANEL_BG,
            foreground=self.ACCENT,
        )
        self.end_time_label.pack(pady=(0, 10))

        self.progress = RetroProgressBar(
            inner,
            trough="#E9E5DD",
            fill=self.ACCENT,
            highlight=self.EDGE_LIGHT,
            shadow=self.EDGE_DARK,
            stripe=self.ACCENT_LIGHT,
            text_dark=self.TEXT_DARK,
            text_light="#FFFFFF",
            font=self.fonts["progress"],
            height=28,
        )
        self.progress.pack(fill="x", padx=12, pady=(0, 12))
        self.progress.set_progress(0.0, "0% Complete")

        self.controls_panel = tk.Frame(inner, bg=self.WINDOW_BG)
        self.controls_panel.pack(fill="both", expand=False, padx=8, pady=(0, 10))

        self.controls_panel.columnconfigure(1, weight=1)

        duration_frame = tk.Frame(self.controls_panel, bg=self.WINDOW_BG)
        duration_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        duration_frame.columnconfigure(1, weight=1)

        ttk.Label(duration_frame, text="Duration (HH:MM:SS):", style="Win2000.TLabel").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.duration_input = TimeInput(
            duration_frame,
            initial=self._config_data.get("last_duration", "00:05:00"),
            font=self.fonts["input"],
            width=11,
            command=self._on_duration_change,
        )
        self.duration_input.grid(row=0, column=1, sticky="ew")
        self.duration_input.configure(bg="#FFFFFF", fg=self.TEXT_DARK, insertbackground=self.TEXT_DARK)

        buttons_frame = tk.Frame(self.controls_panel, bg=self.WINDOW_BG)
        buttons_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for col in range(3):
            buttons_frame.columnconfigure(col, weight=1)

        self.start_button = ttk.Button(
            buttons_frame,
            text="Start",
            style="Win2000.TButton",
            command=self.start_timer,
        )
        self.start_button.grid(row=0, column=0, padx=4, sticky="ew")

        self.pause_button = ttk.Button(
            buttons_frame,
            text="Pause",
            style="Win2000.TButton",
            command=self.toggle_pause,
        )
        self.pause_button.grid(row=0, column=1, padx=4, sticky="ew")

        self.reset_button = ttk.Button(
            buttons_frame,
            text="Reset",
            style="Win2000.TButton",
            command=self.reset_timer,
        )
        self.reset_button.grid(row=0, column=2, padx=4, sticky="ew")

        add_frame = tk.Frame(self.controls_panel, bg=self.WINDOW_BG)
        add_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        add_frame.columnconfigure(1, weight=1)

        ttk.Label(add_frame, text="Add (HH:MM:SS):", style="Win2000.TLabel").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.add_input = TimeInput(add_frame, initial="00:00:30", font=self.fonts["input"], width=11)
        self.add_input.grid(row=0, column=1, sticky="ew")
        self.add_input.configure(bg="#FFFFFF", fg=self.TEXT_DARK, insertbackground=self.TEXT_DARK)

        self.add_button = ttk.Button(
            add_frame,
            text="Add Time",
            style="Win2000.TButton",
            command=self.add_time,
        )
        self.add_button.grid(row=0, column=2, padx=(8, 0))

        sound_frame = tk.Frame(self.controls_panel, bg=self.WINDOW_BG)
        sound_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        sound_frame.columnconfigure(1, weight=1)

        ttk.Label(sound_frame, text="Alarm Sound:", style="Win2000.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.sound_combo = ttk.Combobox(
            sound_frame,
            textvariable=self.sound_var,
            values=list(self.SOUND_PRESETS.keys()),
            state="readonly",
            style="Win2000.TCombobox",
        )
        self.sound_combo.grid(row=0, column=1, sticky="ew", padx=6)
        self.sound_combo.bind("<<ComboboxSelected>>", self._on_sound_change)

        self.compact_check = ttk.Checkbutton(
            sound_frame,
            text="Compact View",
            variable=self.compact_mode,
            command=self.toggle_compact,
            style="Win2000.TCheckbutton",
        )
        self.compact_check.grid(row=0, column=2, sticky="e")

        # Ensure the initial remaining display matches duration
        self.remaining_var.set(self.duration_input.get_formatted())

    def _build_compact_view(self) -> None:
        self.compact_view = tk.Frame(self.master, bg=self.WINDOW_BG, bd=2, relief="ridge")
        self.compact_view.pack_forget()

        self.compact_progress = RetroProgressBar(
            self.compact_view,
            trough="#E9E5DD",
            fill=self.ACCENT,
            highlight=self.EDGE_LIGHT,
            shadow=self.EDGE_DARK,
            stripe=self.ACCENT_LIGHT,
            text_dark=self.TEXT_DARK,
            text_light="#FFFFFF",
            font=self.fonts["progress"],
            height=26,
        )
        self.compact_progress.pack(fill="x", padx=10, pady=(10, 6))
        self.compact_progress.set_progress(0.0, "0% Complete")

        self.compact_time = tk.Label(
            self.compact_view,
            textvariable=self.compact_remaining_var,
            font=self.fonts["compact"],
            background=self.WINDOW_BG,
            foreground=self.TEXT_DARK,
        )
        self.compact_time.pack(fill="x", padx=10)

        self.compact_end_var = tk.StringVar(value="Ends @ --:--:--")
        self.compact_end = tk.Label(
            self.compact_view,
            textvariable=self.compact_end_var,
            font=self.fonts["compact_info"],
            background=self.WINDOW_BG,
            foreground=self.TEXT_SOFT,
        )
        self.compact_end.pack(fill="x", padx=10, pady=(2, 4))

        self.expand_button = ttk.Button(
            self.compact_view,
            text="Expand",
            style="Win2000.TButton",
            command=self._exit_compact,
        )
        self.expand_button.pack(padx=12, pady=(6, 10), anchor="e")

    def _create_tray_icon(self) -> None:
        if not pystray or not Image:
            self.tray_icon = None
            self.tray_thread = None
            return

        size = 64
        image = Image.new("RGB", (size, size), self.ACCENT)
        draw = ImageDraw.Draw(image)
        draw.rectangle((6, 6, size - 7, size - 7), fill=self.PANEL_BG, outline=self.EDGE_LIGHT)
        draw.rectangle((10, 24, size - 11, 36), fill=self.ACCENT)
        draw.text((20, 18), "T", fill=self.TEXT_DARK)

        self.tray_icon = pystray.Icon(
            "countdown_timer",
            image,
            "Countdown Timer",
            menu=pystray.Menu(
                pystray.MenuItem("Show", self._show_window),
                pystray.MenuItem("Hide", self._hide_window),
                pystray.MenuItem("Exit", self._quit_app),
            ),
        )
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def _bind_events(self) -> None:
        self.master.bind("<space>", lambda event: self.toggle_pause())
        self.master.bind("<Escape>", lambda event: self.reset_timer())
        self.master.bind("<Configure>", self._on_configure)
        self.master.bind("<Double-Button-1>", lambda _e: self._toggle_compact_from_double())

        drag_targets = [self.master, self.full_frame, self.timer_panel, self.compact_view]
        for widget in drag_targets:
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._on_move)
            widget.bind("<ButtonRelease-1>", self._stop_move)

        if self.tray_icon:
            self.master.protocol("WM_DELETE_WINDOW", self._hide_window)
        else:
            self.master.protocol("WM_DELETE_WINDOW", self._quit_app)

    def _start_move(self, event: tk.Event) -> None:
        widget = event.widget
        if isinstance(widget, (TimeInput, ttk.Combobox, ttk.Button, ttk.Checkbutton)):
            return
        self.drag_offset["x"] = event.x_root - self.master.winfo_x()
        self.drag_offset["y"] = event.y_root - self.master.winfo_y()

    def _on_move(self, event: tk.Event) -> None:
        if self.drag_offset["x"] == 0 and self.drag_offset["y"] == 0:
            return
        new_x = event.x_root - self.drag_offset["x"]
        new_y = event.y_root - self.drag_offset["y"]
        self.master.geometry(f"+{new_x}+{new_y}")

    def _stop_move(self, _event: tk.Event) -> None:
        self.drag_offset["x"] = 0
        self.drag_offset["y"] = 0

    def _toggle_compact_from_double(self) -> None:
        self.compact_mode.set(not self.compact_mode.get())
        self.toggle_compact()

    def _show_window(self, icon=None, item=None) -> None:
        self.master.after(0, self.master.deiconify)
        self.master.after(0, self.master.lift)

    def _hide_window(self, icon=None, item=None) -> None:
        self.master.after(0, self.master.withdraw)

    def _quit_app(self, icon=None, item=None) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
        self.master.after(0, self.master.destroy)

    def _schedule_update(self) -> None:
        self.master.after(100, self._refresh)

    def _refresh(self) -> None:
        state = self.timer.update()
        remaining = state["remaining"]
        end = state["end"]

        formatted = self._format_timedelta(remaining)
        self.remaining_var.set(formatted)
        self.compact_remaining_var.set(f"Time Left: {formatted}")
        if self.timer.start_time:
            end_text = end.strftime("%H:%M:%S")
            self.end_time_var.set(f"End Time: {end_text}")
            if hasattr(self, "compact_end_var"):
                self.compact_end_var.set(f"Ends @ {end_text}")
        else:
            self.end_time_var.set("End Time: --:--:--")
            if hasattr(self, "compact_end_var"):
                self.compact_end_var.set("Ends @ --:--:--")

        progress_fraction = state["progress"]
        progress_label = f"{int(progress_fraction * 100):3d}% Complete"
        self.progress.set_progress(progress_fraction, progress_label)
        self.compact_progress.set_progress(progress_fraction, progress_label)

        if self.timer.has_finished():
            self._handle_completion()

        self._schedule_update()

    def _handle_completion(self) -> None:
        if self._completed:
            return
        self._completed = True
        self.pause_button.configure(text="Pause")
        self._play_alarm()
        # Delay popup slightly so the alarm is heard first
        self.master.after(800, self._show_completion_popup)

    def _show_completion_popup(self) -> None:
        if self.master.state() == "withdrawn":
            self._show_window()
        messagebox.showinfo("Timer Complete", "Time is up!")

    def _play_alarm(self) -> None:
        sound_name = self.sound_var.get()
        pattern = self.SOUND_PRESETS.get(sound_name) or next(iter(self.SOUND_PRESETS.values()))
        buffers = self._get_sound_buffers(pattern)

        used_audio_device = False
        if winsound and hasattr(winsound, "PlaySound"):
            threading.Thread(
                target=self._play_winsound_wave,
                args=(buffers["wave"],),
                daemon=True,
            ).start()
            used_audio_device = True
        elif sa:
            threading.Thread(
                target=sa.play_buffer,
                args=(buffers["pcm"], 1, 2, self.SAMPLE_RATE),
                daemon=True,
            ).start()
            used_audio_device = True
        else:
            self._play_fallback(pattern)

        if not used_audio_device:
            try:
                self.master.bell()
            except tk.TclError:
                pass

    def _play_winsound_wave(self, data: bytes) -> None:
        try:
            winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_ASYNC)
        except RuntimeError:
            pass

    def _play_fallback(self, pattern: list[tuple[tuple[int, ...], int]]) -> None:
        def step(index: int = 0) -> None:
            if index >= len(pattern):
                return
            freqs, dur = pattern[index]
            if freqs:
                try:
                    self.master.bell()
                except tk.TclError:
                    return
            self.master.after(max(int(dur * 1.05), 80), lambda: step(index + 1))

        self.master.after(120, step)

    def _get_sound_buffers(self, pattern: list[tuple[tuple[int, ...], int]]) -> dict[str, bytes]:
        key = tuple((tuple(freqs), dur) for freqs, dur in pattern)
        cached = self._audio_cache.get(key)
        if cached:
            return cached

        frames = bytearray()
        for freqs, dur in pattern:
            samples = max(int(self.SAMPLE_RATE * (dur / 1000.0)), 1)
            if not freqs:
                frames.extend((0).to_bytes(2, "little", signed=True) * samples)
                continue
            for n in range(samples):
                t = n / self.SAMPLE_RATE
                envelope = 0.5 - 0.5 * math.cos(min(n / samples, 1.0) * math.pi)
                sample = 0.0
                for freq in freqs:
                    sample += math.sin(2 * math.pi * freq * t)
                sample /= len(freqs)
                value = int(32767 * envelope * sample * 0.85)
                frames.extend(int(value).to_bytes(2, "little", signed=True))

        pcm = bytes(frames)
        wave_data = self._wrap_wave(pcm)
        cached = {"pcm": pcm, "wave": wave_data}
        self._audio_cache[key] = cached
        return cached

    def _wrap_wave(self, pcm: bytes) -> bytes:
        data_size = len(pcm)
        riff_size = data_size + 36
        header = b"RIFF" + struct.pack("<I", riff_size) + b"WAVE"
        fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, self.SAMPLE_RATE, self.SAMPLE_RATE * 2, 2, 16)
        data_chunk = b"data" + struct.pack("<I", data_size)
        return header + fmt_chunk + data_chunk + pcm

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self.master:
            self._update_font_sizes(event.width, event.height)

    def _update_font_sizes(self, width: int, height: int) -> None:
        scale = min(max(width / 460, 0.75), max(height / 310, 0.75))
        normal_size = max(9, int(10 * scale))
        input_size = max(10, int(12 * scale))
        timer_size = max(24, int(30 * scale))
        end_size = max(12, int(15 * scale))
        progress_size = max(10, int(12 * scale))
        compact_size = max(12, int(18 * scale))
        compact_info_size = max(10, int(12 * scale))

        self.fonts["small"].configure(size=max(8, normal_size - 1))
        self.fonts["normal"].configure(size=normal_size)
        self.fonts["input"].configure(size=input_size)
        self.fonts["timer"].configure(size=timer_size)
        self.fonts["end"].configure(size=end_size)
        self.fonts["progress"].configure(size=progress_size)
        self.fonts["compact"].configure(size=compact_size)
        self.fonts["compact_info"].configure(size=compact_info_size)

        self.duration_input.set_font(self.fonts["input"])
        self.add_input.set_font(self.fonts["input"])
        self.remaining_label.configure(font=self.fonts["timer"])
        self.compact_time.configure(font=self.fonts["compact"])
        self.end_time_label.configure(font=self.fonts["end"])
        if hasattr(self, "compact_end"):
            self.compact_end.configure(font=self.fonts["compact_info"])
        if hasattr(self, "progress"):
            self.progress.set_font(self.fonts["progress"])
        if hasattr(self, "compact_progress"):
            self.compact_progress.set_font(self.fonts["progress"])
        self.style.configure("Win2000.TLabel", font=self.fonts["normal"])
        self.style.configure("Win2000.TButton", font=self.fonts["normal"])
        self.style.configure("Win2000.TCheckbutton", font=self.fonts["normal"])
        self.style.configure("Win2000.TCombobox", font=self.fonts["normal"])

    def start_timer(self) -> None:
        seconds = self.duration_input.get_seconds()
        if seconds <= 0:
            messagebox.showwarning("Invalid Duration", "Please enter a positive duration.")
            return
        self.timer.set_duration(seconds)
        self.timer.start()
        self._completed = False
        self.pause_button.configure(text="Pause")
        self._save_config()

    def toggle_pause(self) -> None:
        if self.timer.has_finished():
            self.start_timer()
            return
        if not self.timer.start_time:
            self.start_timer()
            return
        if self.timer.paused:
            self.timer.resume()
            self.pause_button.configure(text="Pause")
        else:
            self.timer.pause()
            self.pause_button.configure(text="Resume")

    def reset_timer(self) -> None:
        self.timer.reset()
        self.pause_button.configure(text="Pause")
        self.remaining_var.set(self.duration_input.get_formatted())
        self.compact_remaining_var.set(f"Time Left: {self.duration_input.get_formatted()}")
        self.end_time_var.set("End Time: --:--:--")
        if hasattr(self, "compact_end_var"):
            self.compact_end_var.set("Ends @ --:--:--")
        self.progress.set_progress(0.0, "0% Complete")
        self.compact_progress.set_progress(0.0, "0% Complete")
        if winsound:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except RuntimeError:
                pass
        self._completed = False

    def add_time(self) -> None:
        seconds = self.add_input.get_seconds()
        if seconds <= 0:
            messagebox.showwarning("Invalid Duration", "Enter a time amount to add.")
            return
        self.timer.add_time(seconds)
        self._completed = False

    def toggle_compact(self) -> None:
        if self.compact_mode.get():
            self._enter_compact()
        else:
            self._exit_compact()

    def _enter_compact(self) -> None:
        self.full_frame.pack_forget()
        self.compact_view.pack(expand=True, fill="both", padx=6, pady=6)
        self.compact_mode.set(True)
        self.compact_check.state(["selected"])
        self.master.minsize(220, 120)
        self.master.geometry(f"{max(240, self.master.winfo_width())}x140")

    def _exit_compact(self) -> None:
        self.compact_view.pack_forget()
        self.full_frame.pack(expand=True, fill="both", padx=6, pady=6)
        self.compact_mode.set(False)
        self.compact_check.state(["!selected"])
        self.master.minsize(340, 220)

    def _on_duration_change(self) -> None:
        if not self.timer.start_time:
            formatted = self.duration_input.get_formatted()
            self.remaining_var.set(formatted)
            self.compact_remaining_var.set(f"Time Left: {formatted}")
        self._save_config()

    def _on_sound_change(self, *_event) -> None:
        self._save_config()

    def _format_timedelta(self, delta: timedelta) -> str:
        total_seconds = int(max(delta.total_seconds(), 0))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def run(self) -> None:
        self.master.mainloop()


def main() -> None:
    root = tk.Tk()
    timer = CountdownTimer()
    gui = CountdownGUI(root, timer)
    gui.run()


if __name__ == "__main__":
    main()
