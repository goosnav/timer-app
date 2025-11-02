import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import messagebox, ttk

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


class CountdownGUI:
    """Tkinter-based GUI for the countdown timer."""

    STYLE_BG = "#C3CED6"
    STYLE_DARK = "#7A8AA1"
    STYLE_LIGHT = "#E5E9F0"
    FONT_FAMILY = "Tahoma"

    def __init__(self, master: tk.Tk, timer: CountdownTimer) -> None:
        self.master = master
        self.timer = timer
        self.master.title("Countdown Timer")
        self.master.configure(bg=self.STYLE_BG)
        self.master.geometry("380x220")
        self.master.minsize(260, 120)
        self.master.attributes("-topmost", True)

        self.drag_data = {"x": 0, "y": 0}
        self.compact_mode = tk.BooleanVar(value=False)
        self.duration_var = tk.StringVar(value="00:05:00")
        self.remaining_var = tk.StringVar(value="00:00:00")
        self.end_time_var = tk.StringVar(value="End Time: --:--:--")
        self.sound_var = tk.StringVar(value="Classic Beep")
        self._completed = False

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
                self.duration_var.set(data.get("last_duration", "00:05:00"))
                self.sound_var.set(data.get("sound", "Classic Beep"))
            except json.JSONDecodeError:
                CONFIG_FILE.unlink(missing_ok=True)

    def _save_config(self) -> None:
        data = {
            "last_duration": self.duration_var.get(),
            "sound": self.sound_var.get(),
        }
        CONFIG_FILE.write_text(json.dumps(data, indent=2))

    def _create_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Classic.TFrame",
            background=self.STYLE_BG,
            borderwidth=2,
            relief="groove",
        )
        style.configure(
            "Classic.TLabel",
            background=self.STYLE_BG,
            foreground="#1B2A4E",
            font=(self.FONT_FAMILY, 9),
        )
        style.configure(
            "Classic.TButton",
            background=self.STYLE_LIGHT,
            foreground="#1B2A4E",
            font=(self.FONT_FAMILY, 9),
            padding=4,
        )
        style.map(
            "Classic.TButton",
            background=[("active", self.STYLE_DARK)],
            foreground=[("active", "white")],
        )
        style.configure(
            "Classic.TCheckbutton",
            background=self.STYLE_BG,
            foreground="#1B2A4E",
            font=(self.FONT_FAMILY, 9),
        )
        style.configure(
            "Classic.Horizontal.TProgressbar",
            thickness=18,
            troughcolor="#F2F2F2",
            background="#4A6FA5",
            bordercolor="#4A6FA5",
            lightcolor="#6F8FBF",
            darkcolor="#2F4A6F",
        )

    def _create_widgets(self) -> None:
        self.container = ttk.Frame(self.master, style="Classic.TFrame")
        self.container.pack(expand=True, fill="both", padx=6, pady=6)

        self.container.columnconfigure(0, weight=1)
        for row in range(4):
            self.container.rowconfigure(row, weight=1)

        input_frame = ttk.Frame(self.container, style="Classic.TFrame")
        input_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        input_frame.columnconfigure(1, weight=1)

        ttk.Label(
            input_frame,
            text="Duration (HH:MM:SS):",
            style="Classic.TLabel",
        ).grid(row=0, column=0, padx=4, pady=4, sticky="w")

        self.duration_entry = ttk.Entry(
            input_frame,
            textvariable=self.duration_var,
            font=(self.FONT_FAMILY, 9),
            width=12,
        )
        self.duration_entry.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        controls_frame = ttk.Frame(self.container, style="Classic.TFrame")
        controls_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
        for col in range(4):
            controls_frame.columnconfigure(col, weight=1)

        self.start_button = ttk.Button(
            controls_frame,
            text="Start",
            style="Classic.TButton",
            command=self.start_timer,
        )
        self.start_button.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")

        self.pause_button = ttk.Button(
            controls_frame,
            text="Pause",
            style="Classic.TButton",
            command=self.toggle_pause,
        )
        self.pause_button.grid(row=0, column=1, padx=4, pady=4, sticky="nsew")

        self.reset_button = ttk.Button(
            controls_frame,
            text="Reset",
            style="Classic.TButton",
            command=self.reset_timer,
        )
        self.reset_button.grid(row=0, column=2, padx=4, pady=4, sticky="nsew")

        self.add_button = ttk.Button(
            controls_frame,
            text="Add +00:00:00",
            style="Classic.TButton",
            command=self.add_time,
        )
        self.add_button.grid(row=0, column=3, padx=4, pady=4, sticky="nsew")

        info_frame = ttk.Frame(self.container, style="Classic.TFrame")
        info_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 4))
        info_frame.columnconfigure(0, weight=1)

        self.remaining_label = ttk.Label(
            info_frame,
            textvariable=self.remaining_var,
            style="Classic.TLabel",
            font=(self.FONT_FAMILY, 11, "bold"),
        )
        self.remaining_label.grid(row=0, column=0, padx=4, pady=2, sticky="w")

        self.end_time_label = ttk.Label(
            info_frame,
            textvariable=self.end_time_var,
            style="Classic.TLabel",
        )
        self.end_time_label.grid(row=1, column=0, padx=4, pady=2, sticky="w")

        sound_frame = ttk.Frame(self.container, style="Classic.TFrame")
        sound_frame.grid(row=3, column=0, sticky="nsew")
        sound_frame.columnconfigure(1, weight=1)

        ttk.Label(
            sound_frame,
            text="Alarm Sound:",
            style="Classic.TLabel",
        ).grid(row=0, column=0, padx=4, pady=4, sticky="w")

        sound_choices = [
            "Classic Beep",
            "Double Beep",
            "Triple Beep",
            "Soft Bell",
        ]
        self.sound_menu = ttk.OptionMenu(
            sound_frame,
            self.sound_var,
            self.sound_var.get(),
            *sound_choices,
            command=self._on_sound_change,
        )
        self.sound_menu.configure(width=12)
        self.sound_menu.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        self.compact_check = ttk.Checkbutton(
            sound_frame,
            text="Compact View",
            variable=self.compact_mode,
            command=self.toggle_compact,
            style="Classic.TCheckbutton",
        )
        self.compact_check.grid(row=0, column=2, padx=4, pady=4, sticky="e")

        self.progress = ttk.Progressbar(
            self.master,
            style="Classic.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
        )
        self.progress.pack(fill="x", padx=10, pady=(0, 8))

        self.compact_remaining_label = ttk.Label(
            self.master,
            textvariable=self.remaining_var,
            style="Classic.TLabel",
            anchor="center",
        )

        self.duration_var.trace_add("write", lambda *_: self._update_add_label())
        self._update_add_label()

    def _create_tray_icon(self) -> None:
        if not pystray or not Image:
            self.tray_icon = None
            self.tray_thread = None
            return

        # Create a simple Windows 2000-style icon (blue square with white border)
        size = 64
        image = Image.new("RGB", (size, size), self.STYLE_DARK)
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, size - 9, size - 9), outline="white", fill=self.STYLE_BG)
        draw.text((16, 20), "T", fill=self.STYLE_DARK)
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
        self.master.bind("<Configure>", lambda event: self._update_progress_geometry())
        self.master.bind("<ButtonPress-1>", self._start_move)
        self.master.bind("<B1-Motion>", self._on_move)
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

        self._update_progress_geometry()
        self._schedule_update()

    def _handle_completion(self) -> None:
        if getattr(self, "_completed", False):
            return
        self._completed = True
        threading.Thread(target=self._play_alarm, daemon=True).start()
        messagebox.showinfo("Timer Complete", "Time is up!")
        self.pause_button.configure(text="Pause")

    def _play_alarm(self) -> None:
        sound = self.sound_var.get()
        pattern = {
            "Classic Beep": [(440, 300)],
            "Double Beep": [(523, 200), (659, 200)],
            "Triple Beep": [(659, 150), (784, 150), (880, 200)],
            "Soft Bell": [(392, 400), (330, 400)],
        }.get(sound, [(440, 300)])

        if winsound:
            for freq, dur in pattern:
                winsound.Beep(freq, dur)
                time.sleep(0.05)
        else:
            for _freq, _dur in pattern:
                self.master.bell()
                time.sleep(0.2)

    def _update_progress_geometry(self) -> None:
        if self.compact_mode.get():
            self.progress.pack_configure(fill="x", padx=6, pady=6)
        else:
            self.progress.pack_configure(fill="x", padx=10, pady=(0, 8))

    def start_timer(self) -> None:
        duration = self._parse_duration(self.duration_var.get())
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
        self.remaining_var.set(self.duration_var.get())
        self.end_time_var.set("End Time: --:--:--")
        self.progress.configure(value=0)
        self._completed = False

    def add_time(self) -> None:
        seconds = self._parse_duration(self.duration_var.get())
        if seconds <= 0:
            messagebox.showwarning("Invalid Duration", "Please enter a duration to add.")
            return
        self.timer.add_time(seconds)
        self._save_config()
        self._completed = False

    def toggle_compact(self) -> None:
        compact = self.compact_mode.get()
        self.container.pack_forget()
        self.compact_remaining_label.pack_forget()
        if compact:
            self.progress.pack_configure(fill="x", padx=6, pady=6)
            self.compact_remaining_label.pack(fill="x", padx=6)
        else:
            self.container.pack(expand=True, fill="both", padx=6, pady=6)
            self.progress.pack_configure(fill="x", padx=10, pady=(0, 8))
        self._update_compact_visibility()

    def _update_compact_visibility(self) -> None:
        visible = not self.compact_mode.get()
        for child in self.container.winfo_children():
            child.grid_remove() if not visible else child.grid()
        if visible:
            self.container.grid_propagate(True)
        else:
            self.container.update()

    def _parse_duration(self, value: str) -> int:
        try:
            parts = value.strip().split(":")
            if len(parts) != 3:
                raise ValueError
            hours, minutes, seconds = map(int, parts)
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return max(0, total_seconds)
        except ValueError:
            return 0

    def _format_timedelta(self, delta: timedelta) -> str:
        total_seconds = int(max(delta.total_seconds(), 0))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _update_add_label(self) -> None:
        self.add_button.configure(text=f"Add +{self.duration_var.get()}")
        if not self.timer.start_time:
            self.remaining_var.set(self.duration_var.get())

    def _on_sound_change(self, *_args) -> None:
        self._save_config()

    def run(self) -> None:
        self.master.mainloop()


def main() -> None:
    root = tk.Tk()
    timer = CountdownTimer()
    gui = CountdownGUI(root, timer)
    gui.run()


if __name__ == "__main__":
    main()
