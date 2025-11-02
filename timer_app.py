import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

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


class TimeField(ttk.Entry):
    """Entry-like widget that emulates Google timer digit entry."""

    def __init__(
        self,
        master: tk.Widget,
        *,
        initial: str = "00:00:00",
        font: Optional[tkfont.Font] = None,
        width: int = 10,
    ) -> None:
        self._digits = self._normalize(initial)
        self.variable = tk.StringVar(value=self._format())
        super().__init__(
            master,
            textvariable=self.variable,
            justify="center",
            width=width,
            font=font,
        )
        self._callback: Optional[Callable[[], None]] = None
        self.bind("<KeyPress>", self._on_key)
        self.bind("<Control-v>", lambda event: "break")
        self.bind("<Control-V>", lambda event: "break")
        self.bind("<Button-1>", self._focus_all)
        self.bind("<FocusIn>", self._focus_all)

    def set_callback(self, callback: Callable[[], None]) -> None:
        self._callback = callback

    def _focus_all(self, _event: tk.Event) -> None:
        self.after_idle(lambda: self.select_range(0, tk.END))

    def _notify(self) -> None:
        if self._callback:
            self._callback()
        self.event_generate("<<TimeFieldChanged>>")

    def _normalize(self, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if not digits:
            digits = "0"
        digits = digits[-6:]
        digits = digits.rjust(6, "0")
        return digits

    def _format(self) -> str:
        hours = self._digits[0:2]
        minutes = self._digits[2:4]
        seconds = self._digits[4:6]
        return f"{hours}:{minutes}:{seconds}"

    def _set_digits(self, digits: str) -> None:
        self._digits = digits
        self.variable.set(self._format())
        self._notify()

    def _on_key(self, event: tk.Event) -> Optional[str]:
        if event.keysym in ("Tab", "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return None
        if event.keysym == "BackSpace":
            if self.selection_present():
                self._set_digits("000000")
                return "break"
            new_digits = "0" + self._digits[:-1]
            self._set_digits(new_digits)
            return "break"
        if event.keysym == "Delete":
            self._set_digits("000000")
            return "break"
        if event.char and event.char.isdigit():
            if self.selection_present():
                self._digits = "000000"
            new_digits = (self._digits + event.char)[-6:]
            self._set_digits(new_digits)
            return "break"
        if event.keysym in ("Left", "Right", "Home", "End"):
            return "break"
        return "break"

    def set_from_seconds(self, total_seconds: int) -> None:
        total_seconds = max(0, min(total_seconds, 359999))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        digits = f"{hours:02d}{minutes:02d}{seconds:02d}"[-6:]
        self._set_digits(digits)

    def set_from_string(self, value: str) -> None:
        self._set_digits(self._normalize(value))

    def get_seconds(self) -> int:
        hours = int(self._digits[0:2])
        minutes = int(self._digits[2:4])
        seconds = int(self._digits[4:6])
        return hours * 3600 + minutes * 60 + seconds

    def get_formatted(self) -> str:
        return self._format()


class CountdownGUI:
    """Tkinter-based GUI for the countdown timer."""

    WINDOW_BG = "#B7B7B7"
    PANEL_BG = "#D4D0C8"
    EDGE_DARK = "#808080"
    EDGE_LIGHT = "#FFFFFF"
    ACCENT_DARK = "#000080"
    PROGRESS_BAR = "#003399"
    FONT_FAMILY = "Tahoma"

    def __init__(self, master: tk.Tk, timer: CountdownTimer) -> None:
        self.master = master
        self.timer = timer
        self.master.title("Countdown Timer")
        self.master.configure(bg=self.WINDOW_BG)
        self.master.geometry("420x260")
        self.master.minsize(280, 160)
        self.master.attributes("-topmost", True)

        self.drag_data = {"x": 0, "y": 0}
        self.compact_mode = tk.BooleanVar(value=False)
        self.remaining_var = tk.StringVar(value="00:00:00")
        self.end_time_var = tk.StringVar(value="End Time: --:--:--")
        self.sound_var = tk.StringVar(value="System Asterisk")
        self._completed = False

        self.font_small = tkfont.Font(family=self.FONT_FAMILY, size=9)
        self.font_medium = tkfont.Font(family=self.FONT_FAMILY, size=10)
        self.font_large = tkfont.Font(family=self.FONT_FAMILY, size=18, weight="bold")

        self.duration_field: Optional[TimeField] = None
        self.add_field: Optional[TimeField] = None

        self._load_config()

        self._create_style()
        self._create_widgets()
        self._create_tray_icon()
        self._bind_events()
        self._schedule_update()

    def _load_config(self) -> None:
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                self._initial_duration = data.get("last_duration", "00:05:00")
                self._initial_add = data.get("add_duration", "00:01:00")
                self.sound_var.set(data.get("sound", "System Asterisk"))
            except json.JSONDecodeError:
                CONFIG_FILE.unlink(missing_ok=True)
                self._initial_duration = "00:05:00"
                self._initial_add = "00:01:00"
        else:
            self._initial_duration = "00:05:00"
            self._initial_add = "00:01:00"

    def _save_config(self) -> None:
        data = {
            "last_duration": self.duration_field.get_formatted() if self.duration_field else "00:05:00",
            "add_duration": self.add_field.get_formatted() if self.add_field else "00:01:00",
            "sound": self.sound_var.get(),
        }
        CONFIG_FILE.write_text(json.dumps(data, indent=2))

    def _create_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Timer.TFrame", background=self.PANEL_BG)
        style.configure(
            "Timer.TButton",
            padding=4,
            background=self.PANEL_BG,
            font=self.font_medium,
            relief="raised",
        )
        style.map(
            "Timer.TButton",
            background=[("active", self.WINDOW_BG)],
        )
        style.configure(
            "Timer.TCheckbutton",
            background=self.WINDOW_BG,
            font=self.font_small,
        )
        style.configure(
            "Classic.Horizontal.TProgressbar",
            thickness=16,
            troughcolor="#E4E0D7",
            background=self.PROGRESS_BAR,
            bordercolor=self.EDGE_DARK,
            lightcolor="#6D90C7",
            darkcolor=self.ACCENT_DARK,
        )

    def _create_widgets(self) -> None:
        self.outer = tk.Frame(self.master, bg=self.WINDOW_BG, bd=1, relief="flat")
        self.outer.pack(expand=True, fill="both", padx=6, pady=(6, 4))

        self.display_panel = tk.Frame(
            self.outer,
            bg=self.PANEL_BG,
            bd=2,
            relief="sunken",
            highlightthickness=1,
            highlightbackground=self.EDGE_LIGHT,
            highlightcolor=self.EDGE_LIGHT,
        )
        self.display_panel.pack(expand=True, fill="both", padx=4, pady=(4, 6))

        self.remaining_label = tk.Label(
            self.display_panel,
            textvariable=self.remaining_var,
            font=self.font_large,
            bg=self.PANEL_BG,
            fg=self.ACCENT_DARK,
            anchor="center",
        )
        self.remaining_label.pack(expand=True, fill="both", padx=8, pady=(12, 4))

        self.end_time_label = tk.Label(
            self.display_panel,
            textvariable=self.end_time_var,
            font=self.font_small,
            bg=self.PANEL_BG,
            fg="#202020",
            anchor="center",
        )
        self.end_time_label.pack(pady=(0, 8))

        self.compact_hint = tk.Label(
            self.display_panel,
            text="Compact Mode — double-click to restore",
            font=self.font_small,
            bg=self.PANEL_BG,
            fg="#202020",
        )
        self.compact_hint.pack_forget()
        self.compact_hint.bind("<Double-Button-1>", self._toggle_compact_from_double)

        self.progress = ttk.Progressbar(
            self.outer,
            style="Classic.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
        )
        self.progress.pack(fill="x", padx=6, pady=(0, 6))

        self.controls_panel = tk.Frame(self.outer, bg=self.WINDOW_BG)
        self.controls_panel.pack(fill="both", padx=4, pady=(0, 4))
        self.controls_panel.columnconfigure(0, weight=1)
        self.controls_panel.columnconfigure(1, weight=1)

        duration_box = tk.Frame(self.controls_panel, bg=self.WINDOW_BG)
        duration_box.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        duration_box.columnconfigure(1, weight=1)

        duration_label = tk.Label(
            duration_box,
            text="Duration:",
            font=self.font_small,
            bg=self.WINDOW_BG,
            fg="#000000",
        )
        duration_label.grid(row=0, column=0, sticky="w", padx=(0, 4))

        self.duration_field = TimeField(duration_box, initial=self._initial_duration, font=self.font_medium)
        self.duration_field.grid(row=0, column=1, sticky="ew")
        self.duration_field.set_callback(self._on_duration_changed)

        add_box = tk.Frame(self.controls_panel, bg=self.WINDOW_BG)
        add_box.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        add_box.columnconfigure(1, weight=1)

        add_label = tk.Label(
            add_box,
            text="Add Time:",
            font=self.font_small,
            bg=self.WINDOW_BG,
            fg="#000000",
        )
        add_label.grid(row=0, column=0, sticky="w", padx=(0, 4))

        self.add_field = TimeField(add_box, initial=self._initial_add, font=self.font_medium)
        self.add_field.grid(row=0, column=1, sticky="ew")
        self.add_field.set_callback(self._on_add_duration_changed)

        buttons_box = tk.Frame(self.controls_panel, bg=self.WINDOW_BG)
        buttons_box.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=2, pady=2)
        for col in range(2):
            buttons_box.columnconfigure(col, weight=1)

        self.start_button = ttk.Button(
            buttons_box,
            text="Start",
            style="Timer.TButton",
            command=self.start_timer,
        )
        self.start_button.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        self.pause_button = ttk.Button(
            buttons_box,
            text="Pause",
            style="Timer.TButton",
            command=self.toggle_pause,
        )
        self.pause_button.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)

        self.reset_button = ttk.Button(
            buttons_box,
            text="Reset",
            style="Timer.TButton",
            command=self.reset_timer,
        )
        self.reset_button.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)

        self.add_button = ttk.Button(
            buttons_box,
            text="Add",
            style="Timer.TButton",
            command=self.add_time,
        )
        self.add_button.grid(row=1, column=1, sticky="nsew", padx=2, pady=2)

        sound_box = tk.Frame(self.outer, bg=self.WINDOW_BG)
        sound_box.pack(fill="x", padx=4, pady=(0, 4))
        sound_box.columnconfigure(1, weight=1)

        sound_label = tk.Label(
            sound_box,
            text="Alarm Sound:",
            font=self.font_small,
            bg=self.WINDOW_BG,
            fg="#000000",
        )
        sound_label.grid(row=0, column=0, sticky="w", padx=(0, 4))

        sound_choices = [
            "System Asterisk",
            "System Exclamation",
            "System Hand",
            "System Question",
            "Classic Beeps",
        ]
        self.sound_menu = ttk.OptionMenu(
            sound_box,
            self.sound_var,
            self.sound_var.get(),
            *sound_choices,
            command=self._on_sound_change,
        )
        self.sound_menu.configure(width=16)
        self.sound_menu.grid(row=0, column=1, sticky="ew")

        self.compact_check = ttk.Checkbutton(
            sound_box,
            text="Compact View",
            variable=self.compact_mode,
            command=self.toggle_compact,
            style="Timer.TCheckbutton",
        )
        self.compact_check.grid(row=0, column=2, sticky="e", padx=(6, 0))

        self.sound_box = sound_box
        self._on_duration_changed()
        self.timer.set_duration(self.duration_field.get_seconds())
        self._on_resize()

    def _create_tray_icon(self) -> None:
        if not pystray or not Image:
            self.tray_icon = None
            self.tray_thread = None
            return

        # Create a simple Windows 2000-style icon (blue square with white border)
        size = 64
        image = Image.new("RGB", (size, size), self.ACCENT_DARK)
        draw = ImageDraw.Draw(image)
        draw.rectangle((6, 6, size - 7, size - 7), outline=self.EDGE_LIGHT, fill=self.PANEL_BG)
        draw.rectangle((7, 7, size - 8, size - 8), outline=self.EDGE_DARK)
        draw.text((20, 18), "T", fill=self.ACCENT_DARK)
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
        self.master.bind("<Configure>", self._on_resize)
        self.master.bind("<ButtonPress-1>", self._start_move)
        self.master.bind("<B1-Motion>", self._on_move)
        self.remaining_label.bind("<Double-Button-1>", self._toggle_compact_from_double)
        self.progress.bind("<Double-Button-1>", self._toggle_compact_from_double)
        self.display_panel.bind("<Double-Button-1>", self._toggle_compact_from_double)
        if self.tray_icon:
            self.master.protocol("WM_DELETE_WINDOW", self._hide_window)
        else:
            self.master.protocol("WM_DELETE_WINDOW", self._quit_app)

    def _start_move(self, event: tk.Event) -> None:
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def _on_move(self, event: tk.Event) -> None:
        x = self.master.winfo_pointerx() - self.drag_data["x"]
        y = self.master.winfo_pointery() - self.drag_data["y"]
        self.master.geometry(f"+{x}+{y}")

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

        self.remaining_var.set(self._format_timedelta(remaining))
        if self.timer.start_time:
            self.end_time_var.set(f"End Time: {end.strftime('%H:%M:%S')}")
        else:
            self.end_time_var.set("End Time: --:--:--")
        progress = state["progress"] * 100
        self.progress.configure(value=progress, maximum=100)

        if self.timer.has_finished():
            self._handle_completion()

        self._update_progress_padding()
        self._schedule_update()

    def _handle_completion(self) -> None:
        if getattr(self, "_completed", False):
            return
        self._completed = True
        self._play_alarm()
        self.master.after(150, lambda: messagebox.showinfo("Timer Complete", "Time is up!"))
        self.pause_button.configure(text="Pause")

    def _play_alarm(self) -> None:
        sound = self.sound_var.get()
        if winsound:
            alias_map = {
                "System Asterisk": "SystemAsterisk",
                "System Exclamation": "SystemExclamation",
                "System Hand": "SystemHand",
                "System Question": "SystemQuestion",
            }
            alias = alias_map.get(sound)
            if alias:
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
                return
            winsound.PlaySound(None, winsound.SND_PURGE)
            threading.Thread(target=self._play_fallback_beeps, daemon=True).start()
        else:
            threading.Thread(target=self._play_fallback_beeps, daemon=True).start()

    def _play_fallback_beeps(self) -> None:
        pattern = [440, 523, 659, 523]
        for freq in pattern:
            if winsound:
                winsound.Beep(freq, 200)
            else:
                self.master.after(0, self.master.bell)
                time.sleep(0.2)
            time.sleep(0.05)

    def _update_progress_padding(self) -> None:
        if self.compact_mode.get():
            self.progress.pack_configure(fill="x", padx=6, pady=6)
        else:
            self.progress.pack_configure(fill="x", padx=6, pady=(0, 6))

    def start_timer(self) -> None:
        if not self.duration_field:
            return
        duration = self.duration_field.get_seconds()
        if duration <= 0:
            messagebox.showwarning("Invalid Duration", "Please enter a positive duration.")
            return
        self.timer.set_duration(duration)
        self.timer.start()
        self._completed = False
        self._save_config()
        self.pause_button.configure(text="Pause")

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
        if self.duration_field:
            self.remaining_var.set(self.duration_field.get_formatted())
        self.end_time_var.set("End Time: --:--:--")
        self.progress.configure(value=0)
        self._completed = False
        if winsound:
            winsound.PlaySound(None, winsound.SND_PURGE)

    def add_time(self) -> None:
        if not self.add_field:
            return
        seconds = self.add_field.get_seconds()
        if seconds <= 0:
            messagebox.showwarning("Invalid Duration", "Please enter a duration to add.")
            return
        if self.timer.start_time:
            self.timer.add_time(seconds)
        else:
            if self.duration_field:
                new_total = self.duration_field.get_seconds() + seconds
                self.duration_field.set_from_seconds(new_total)
                self.remaining_var.set(self.duration_field.get_formatted())
                self.timer.set_duration(new_total)
        self._save_config()
        self._completed = False

    def toggle_compact(self) -> None:
        self._apply_compact_mode()

    def _toggle_compact_from_double(self, _event: Optional[tk.Event] = None) -> None:
        self.compact_mode.set(not self.compact_mode.get())
        self._apply_compact_mode()

    def _apply_compact_mode(self) -> None:
        compact = self.compact_mode.get()
        if compact:
            self.controls_panel.pack_forget()
            self.sound_box.pack_forget()
            self.end_time_label.pack_forget()
            self.compact_hint.pack(pady=(0, 8))
        else:
            self.compact_hint.pack_forget()
            if not self.end_time_label.winfo_manager():
                self.end_time_label.pack(pady=(0, 8))
            if not self.controls_panel.winfo_manager():
                self.controls_panel.pack(fill="both", padx=4, pady=(0, 4))
            if not self.sound_box.winfo_manager():
                self.sound_box.pack(fill="x", padx=4, pady=(0, 4))
        self._update_progress_padding()

    def _format_timedelta(self, delta: timedelta) -> str:
        total_seconds = int(max(delta.total_seconds(), 0))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _on_duration_changed(self) -> None:
        if not self.duration_field:
            return
        formatted = self.duration_field.get_formatted()
        if not self.timer.start_time:
            self.remaining_var.set(formatted)
        self._save_config()

    def _on_add_duration_changed(self) -> None:
        self._save_config()

    def _on_sound_change(self, *_args) -> None:
        self._save_config()

    def _on_resize(self, _event: Optional[tk.Event] = None) -> None:
        width = max(self.master.winfo_width(), 280)
        height = max(self.master.winfo_height(), 160)
        base = max(8, min(width // 26, height // 14))
        self.font_small.configure(size=base)
        self.font_medium.configure(size=base + 1)
        self.font_large.configure(size=max(14, (base + 2) * 2))
        self._update_progress_padding()

    def run(self) -> None:
        self.master.mainloop()


def main() -> None:
    root = tk.Tk()
    timer = CountdownTimer()
    gui = CountdownGUI(root, timer)
    gui.run()


if __name__ == "__main__":
    main()
