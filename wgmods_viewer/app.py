from __future__ import annotations

import calendar
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib
import pandas as pd
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg,
    NavigationToolbar2Tk,
)
from matplotlib.figure import Figure

from .data import DatabaseError, list_mods, load_snapshots
from .plotting import METRIC_LABELS, PlotOptions, make_summary, render_plot

matplotlib.use("TkAgg")


class DateSelector(ttk.Frame):
    """Explicit year/month/day selector with keyboard and arrow controls."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.year_var = tk.IntVar(value=date.today().year)
        self.month_var = tk.IntVar(value=date.today().month)
        self.day_var = tk.IntVar(value=date.today().day)

        self.year_spin = ttk.Spinbox(
            self, from_=1970, to=9999, textvariable=self.year_var, width=6,
            command=self._clamp_day,
        )
        self.month_spin = ttk.Spinbox(
            self, from_=1, to=12, textvariable=self.month_var, width=4,
            command=self._clamp_day,
        )
        self.day_spin = ttk.Spinbox(
            self, from_=1, to=31, textvariable=self.day_var, width=4,
        )

        self.year_spin.grid(row=0, column=0)
        ttk.Label(self, text='-').grid(row=0, column=1, padx=2)
        self.month_spin.grid(row=0, column=2)
        ttk.Label(self, text='-').grid(row=0, column=3, padx=2)
        self.day_spin.grid(row=0, column=4)

        for variable in (self.year_var, self.month_var):
            variable.trace_add('write', lambda *_: self._clamp_day())

    def _clamp_day(self) -> None:
        try:
            year = min(9999, max(1970, int(self.year_var.get())))
            month = min(12, max(1, int(self.month_var.get())))
            max_day = calendar.monthrange(year, month)[1]
            day = min(max_day, max(1, int(self.day_var.get())))
            self.day_spin.configure(to=max_day)
            if self.day_var.get() != day:
                self.day_var.set(day)
        except (tk.TclError, ValueError):
            return

    def set_date(self, value: date) -> None:
        self.year_var.set(value.year)
        self.month_var.set(value.month)
        self.day_var.set(value.day)
        self._clamp_day()

    def get_date(self) -> date:
        try:
            year = int(self.year_var.get())
            month = int(self.month_var.get())
            day = int(self.day_var.get())
            return date(year, month, day)
        except (tk.TclError, ValueError) as exc:
            raise ValueError('Invalid date selection.') from exc


class WGModsViewer(tk.Tk):
    def __init__(self, initial_database: str | None = None) -> None:
        super().__init__()
        self.title("WGMods Statistics Viewer")
        self.geometry("1500x900")
        self.minsize(1100, 700)

        self.database_path: Path | None = None
        self.snapshots = pd.DataFrame()
        self.mods = pd.DataFrame()
        self.visible_mod_ids: list[int] = []

        self.timezone_var = tk.StringVar(value="Europe/Zurich")
        self.search_var = tk.StringVar()
        self.start_time_var = tk.StringVar(value="00:00")
        self.end_time_var = tk.StringVar(value="00:00")
        self.aggregation_var = tk.StringVar(value="Daily")
        self.mode_var = tk.StringVar(value="Cumulative growth")
        self.chart_type_var = tk.StringVar(value="Line")
        self.smoothing_var = tk.IntVar(value=1)
        self.log_scale_var = tk.BooleanVar(value=False)
        self.markers_var = tk.BooleanVar(value=True)
        self.legend_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Open a WGMods SQLite database.")

        self.metric_vars = {
            metric: tk.BooleanVar(value=(metric == "downloads"))
            for metric in METRIC_LABELS
        }

        self._build_ui()
        self.search_var.trace_add("write", lambda *_: self._refresh_mod_list())

        if initial_database:
            self.after(100, lambda: self.open_database(initial_database))

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        controls = ttk.Frame(self, padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(5, weight=1)

        viewer = ttk.Frame(self, padding=(0, 10, 10, 10))
        viewer.grid(row=0, column=1, sticky="nsew")
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(0, weight=1)

        file_frame = ttk.LabelFrame(controls, text="Database", padding=8)
        file_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        file_frame.columnconfigure(0, weight=1)
        self.db_label = ttk.Label(file_frame, text="No database selected", wraplength=290)
        self.db_label.grid(row=0, column=0, sticky="w")
        ttk.Button(file_frame, text="Open SQLite…", command=self.choose_database).grid(
            row=1, column=0, sticky="ew", pady=(6, 0)
        )
        ttk.Button(file_frame, text="Reload", command=self.reload_database).grid(
            row=2, column=0, sticky="ew", pady=(4, 0)
        )

        timezone_frame = ttk.Frame(file_frame)
        timezone_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        timezone_frame.columnconfigure(1, weight=1)
        ttk.Label(timezone_frame, text="Timezone").grid(row=0, column=0, padx=(0, 4))
        ttk.Entry(timezone_frame, textvariable=self.timezone_var).grid(
            row=0, column=1, sticky="ew"
        )

        date_frame = ttk.LabelFrame(controls, text="Date range", padding=8)
        date_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        date_frame.columnconfigure(1, weight=1)
        date_frame.columnconfigure(2, weight=0)

        time_values = [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in range(0, 60, 15)]

        ttk.Label(date_frame, text="Start").grid(row=0, column=0, sticky="w")
        self.start_date_picker = DateSelector(date_frame)
        self.start_date_picker.grid(row=0, column=1, sticky="w", padx=(5, 4))
        self.start_time_picker = ttk.Combobox(
            date_frame,
            textvariable=self.start_time_var,
            values=time_values,
            state="readonly",
            width=7,
        )
        self.start_time_picker.grid(row=0, column=2, sticky="e")

        ttk.Label(date_frame, text="End").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.end_date_picker = DateSelector(date_frame)
        self.end_date_picker.grid(row=1, column=1, sticky="w", padx=(5, 4), pady=(4, 0))
        self.end_time_picker = ttk.Combobox(
            date_frame,
            textvariable=self.end_time_var,
            values=time_values,
            state="readonly",
            width=7,
        )
        self.end_time_picker.grid(row=1, column=2, sticky="e", pady=(4, 0))

        ttk.Label(
            date_frame,
            text="The end boundary is exclusive. Default: tomorrow at 00:00.",
            wraplength=285,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))

        metric_frame = ttk.LabelFrame(controls, text="Metrics", padding=8)
        metric_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for row, (metric, label) in enumerate(METRIC_LABELS.items()):
            ttk.Checkbutton(
                metric_frame,
                text=label,
                variable=self.metric_vars[metric],
            ).grid(row=row, column=0, sticky="w")

        view_frame = ttk.LabelFrame(controls, text="Plot settings", padding=8)
        view_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        view_frame.columnconfigure(1, weight=1)

        fields = [
            ("Aggregation", self.aggregation_var, ["Raw snapshots", "Hourly", "Daily", "Weekly"]),
            (
                "View",
                self.mode_var,
                [
                    "Absolute value",
                    "Cumulative growth",
                    "Period change",
                    "Percentage growth",
                    "Indexed growth (100)",
                ],
            ),
            ("Chart", self.chart_type_var, ["Line", "Step", "Area", "Bar"]),
        ]
        for row, (label, variable, values) in enumerate(fields):
            ttk.Label(view_frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Combobox(
                view_frame,
                textvariable=variable,
                values=values,
                state="readonly",
                width=22,
            ).grid(row=row, column=1, sticky="ew", padx=(5, 0), pady=2)

        ttk.Label(view_frame, text="Smoothing").grid(row=3, column=0, sticky="w")
        ttk.Spinbox(
            view_frame,
            from_=1,
            to=30,
            textvariable=self.smoothing_var,
            width=8,
        ).grid(row=3, column=1, sticky="w", padx=(5, 0), pady=2)
        ttk.Checkbutton(
            view_frame, text="Compressed/log scale", variable=self.log_scale_var
        ).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            view_frame, text="Show markers", variable=self.markers_var
        ).grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            view_frame, text="Show legend", variable=self.legend_var
        ).grid(row=6, column=0, columnspan=2, sticky="w")

        mod_header = ttk.Frame(controls)
        mod_header.grid(row=4, column=0, sticky="ew")
        mod_header.columnconfigure(0, weight=1)
        ttk.Label(mod_header, text="Mods").grid(row=0, column=0, sticky="w")
        ttk.Entry(mod_header, textvariable=self.search_var).grid(
            row=1, column=0, sticky="ew", pady=(3, 3)
        )

        mod_frame = ttk.Frame(controls)
        mod_frame.grid(row=5, column=0, sticky="nsew")
        mod_frame.columnconfigure(0, weight=1)
        mod_frame.rowconfigure(0, weight=1)

        self.mod_list = tk.Listbox(
            mod_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
            width=43,
        )
        self.mod_list.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            mod_frame, orient="vertical", command=self.mod_list.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.mod_list.configure(yscrollcommand=scrollbar.set)

        selection_buttons = ttk.Frame(controls)
        selection_buttons.grid(row=6, column=0, sticky="ew", pady=(6, 8))
        for column in range(4):
            selection_buttons.columnconfigure(column, weight=1)
        ttk.Button(
            selection_buttons, text="All", command=self.select_all_mods
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            selection_buttons, text="None", command=self.clear_mod_selection
        ).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(
            selection_buttons, text="Top 5", command=lambda: self.select_top_mods(5)
        ).grid(row=0, column=2, sticky="ew")
        ttk.Button(
            selection_buttons, text="Top 10", command=lambda: self.select_top_mods(10)
        ).grid(row=0, column=3, sticky="ew", padx=(3, 0))

        action_frame = ttk.Frame(controls)
        action_frame.grid(row=7, column=0, sticky="ew")
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        ttk.Button(
            action_frame, text="Update plot", command=self.update_plot
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            action_frame, text="Export summary…", command=self.export_summary
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        notebook = ttk.Notebook(viewer)
        notebook.grid(row=0, column=0, sticky="nsew")

        plot_tab = ttk.Frame(notebook)
        plot_tab.columnconfigure(0, weight=1)
        plot_tab.rowconfigure(0, weight=1)
        notebook.add(plot_tab, text="Interactive plot")

        self.figure = Figure(figsize=(10, 7), dpi=100, constrained_layout=True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_tab)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        toolbar_frame = ttk.Frame(plot_tab)
        toolbar_frame.grid(row=1, column=0, sticky="ew")
        self.toolbar = NavigationToolbar2Tk(
            self.canvas, toolbar_frame, pack_toolbar=False
        )
        self.toolbar.update()
        self.toolbar.pack(side=tk.LEFT, fill=tk.X)

        summary_tab = ttk.Frame(notebook)
        summary_tab.columnconfigure(0, weight=1)
        summary_tab.rowconfigure(0, weight=1)
        notebook.add(summary_tab, text="Summary table")

        columns = ("Mod", "ID", "Metric", "Start", "End", "Change", "Change %")
        self.summary_tree = ttk.Treeview(
            summary_tab, columns=columns, show="headings"
        )
        for column in columns:
            self.summary_tree.heading(column, text=column)
            self.summary_tree.column(
                column,
                width=230 if column == "Mod" else 100,
                anchor="w" if column == "Mod" else "e",
            )
        self.summary_tree.grid(row=0, column=0, sticky="nsew")
        summary_scroll = ttk.Scrollbar(
            summary_tab, orient="vertical", command=self.summary_tree.yview
        )
        summary_scroll.grid(row=0, column=1, sticky="ns")
        self.summary_tree.configure(yscrollcommand=summary_scroll.set)

        status = ttk.Label(
            self,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor="w",
            padding=(6, 3),
        )
        status.grid(row=1, column=0, columnspan=2, sticky="ew")

    def choose_database(self) -> None:
        path = filedialog.askopenfilename(
            title="Open WGMods statistics database",
            filetypes=[
                ("SQLite databases", "*.sqlite *.sqlite3 *.db"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.open_database(path)

    def reload_database(self) -> None:
        if self.database_path is None:
            self.choose_database()
            return
        self.open_database(str(self.database_path))

    def open_database(self, path: str) -> None:
        try:
            snapshots = load_snapshots(path, self.timezone_var.get().strip())
            mods = list_mods(snapshots)
        except DatabaseError as exc:
            messagebox.showerror("Could not open database", str(exc))
            return

        self.database_path = Path(path).resolve()
        self.snapshots = snapshots
        self.mods = mods
        self.db_label.configure(text=str(self.database_path))
        earliest = snapshots["timestamp"].min()
        tomorrow = pd.Timestamp.now(tz=self.timezone_var.get().strip()).normalize() + pd.Timedelta(days=1)

        self.start_date_picker.set_date(earliest.date())
        self.start_time_var.set(earliest.strftime("%H:%M"))
        self.end_date_picker.set_date(tomorrow.date())
        self.end_time_var.set("00:00")
        self._refresh_mod_list()
        self.select_top_mods(10)
        self.update_plot()
        self.status_var.set(
            f"Loaded {len(snapshots):,} snapshots for {len(mods):,} mods."
        )

    def _refresh_mod_list(self) -> None:
        selected_ids = {
            self.visible_mod_ids[index]
            for index in self.mod_list.curselection()
            if index < len(self.visible_mod_ids)
        }
        query = self.search_var.get().strip().lower()
        self.mod_list.delete(0, tk.END)
        self.visible_mod_ids = []

        if self.mods.empty:
            return

        for row in self.mods.itertuples(index=False):
            label = (
                f"{row.display_title} [{row.mod_id}]  "
                f"D:{int(row.downloads or 0):,}  "
                f"Δ:{int(row.growth or 0):+,}"
            )
            if query and query not in label.lower():
                continue
            self.visible_mod_ids.append(int(row.mod_id))
            self.mod_list.insert(tk.END, label)
            if int(row.mod_id) in selected_ids:
                self.mod_list.selection_set(tk.END)

    def select_all_mods(self) -> None:
        self.mod_list.selection_set(0, tk.END)

    def clear_mod_selection(self) -> None:
        self.mod_list.selection_clear(0, tk.END)

    def select_top_mods(self, count: int) -> None:
        self.clear_mod_selection()
        if self.mods.empty:
            return
        top_ids = set(
            self.mods.sort_values("growth", ascending=False)
            .head(count)["mod_id"]
            .astype(int)
        )
        for index, mod_id in enumerate(self.visible_mod_ids):
            if mod_id in top_ids:
                self.mod_list.selection_set(index)

    def _combine_date_time(self, date_picker: DateSelector, time_value: str) -> pd.Timestamp:
        value = time_value.strip()
        try:
            hour_text, minute_text = value.split(":", 1)
            hour = int(hour_text)
            minute = int(minute_text)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"Invalid time value: {value!r}") from exc

        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError(f"Invalid time value: {value!r}")

        selected_date = date_picker.get_date()
        parsed = pd.Timestamp(
            year=selected_date.year,
            month=selected_date.month,
            day=selected_date.day,
            hour=hour,
            minute=minute,
        )
        return parsed.tz_localize(self.timezone_var.get().strip())

    def _build_plot_options(self) -> PlotOptions:
        selected_indices = self.mod_list.curselection()
        mod_ids = tuple(self.visible_mod_ids[index] for index in selected_indices)
        if not mod_ids:
            raise ValueError("Select at least one mod.")

        metrics = tuple(
            metric
            for metric, variable in self.metric_vars.items()
            if variable.get()
        )
        if not metrics:
            raise ValueError("Select at least one metric.")

        start = self._combine_date_time(self.start_date_picker, self.start_time_var.get())
        end = self._combine_date_time(self.end_date_picker, self.end_time_var.get())
        if start > end:
            raise ValueError("Start date/time must be before the end date/time.")

        smoothing = max(1, int(self.smoothing_var.get()))
        return PlotOptions(
            mod_ids=mod_ids,
            metrics=metrics,
            start=start,
            end=end,
            aggregation=self.aggregation_var.get(),
            mode=self.mode_var.get(),
            chart_type=self.chart_type_var.get(),
            smoothing=smoothing,
            log_scale=self.log_scale_var.get(),
            show_markers=self.markers_var.get(),
            show_legend=self.legend_var.get(),
        )

    def update_plot(self) -> None:
        if self.snapshots.empty:
            return
        try:
            options = self._build_plot_options()
        except (ValueError, TypeError) as exc:
            messagebox.showwarning("Invalid plot options", str(exc))
            return

        self.figure.clear()
        axes = [
            self.figure.add_subplot(len(options.metrics), 1, index + 1)
            for index in range(len(options.metrics))
        ]
        count = render_plot(axes, self.snapshots, options)
        self.figure.suptitle(
            f"WGMods statistics: {options.mode}",
            fontsize=14,
        )
        self.canvas.draw_idle()
        self._update_summary(options)
        self.status_var.set(
            f"Rendered {count} series for {len(options.mod_ids)} selected mods."
        )

    def _update_summary(self, options: PlotOptions) -> None:
        for item in self.summary_tree.get_children():
            self.summary_tree.delete(item)

        summary = make_summary(self.snapshots, options)
        if summary.empty:
            return

        summary = summary.sort_values(
            ["Metric", "Change"], ascending=[True, False]
        )
        for row in summary.itertuples(index=False, name=None):
            values = []
            for index, value in enumerate(row):
                if index >= 3 and pd.notna(value):
                    values.append(f"{float(value):,.4f}".rstrip("0").rstrip("."))
                elif pd.isna(value):
                    values.append("")
                else:
                    values.append(value)
            self.summary_tree.insert("", tk.END, values=values)

    def export_summary(self) -> None:
        if self.snapshots.empty:
            return
        try:
            options = self._build_plot_options()
        except (ValueError, TypeError) as exc:
            messagebox.showwarning("Invalid export options", str(exc))
            return

        path = filedialog.asksaveasfilename(
            title="Export summary",
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")],
        )
        if not path:
            return

        summary = make_summary(self.snapshots, options)
        summary.to_csv(path, index=False)
        self.status_var.set(f"Exported summary to {path}")


def main() -> None:
    initial_database = sys.argv[1] if len(sys.argv) > 1 else None
    app = WGModsViewer(initial_database)
    app.mainloop()
