from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from matplotlib.axes import Axes


METRIC_LABELS = {
    "downloads": "Downloads",
    "votes": "Votes",
    "rating": "Public rating",
    "internal_rating": "Internal rating",
}


@dataclass(frozen=True)
class PlotOptions:
    mod_ids: tuple[int, ...]
    metrics: tuple[str, ...]
    start: pd.Timestamp
    end: pd.Timestamp
    aggregation: str
    mode: str
    chart_type: str
    smoothing: int
    log_scale: bool
    show_markers: bool
    show_legend: bool


def _resample_mod(mod_frame: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    data = mod_frame.set_index("timestamp").sort_index()
    if aggregation == "Raw snapshots":
        return data

    rule = {
        "Hourly": "1h",
        "Daily": "1D",
        "Weekly": "1W",
    }[aggregation]

    # Tracker values are counters/state values. The last observation in a period
    # is the most faithful representation of the period ending state.
    return data.resample(rule).last().dropna(how="all")


def _transform(series: pd.Series, mode: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")

    if mode == "Absolute value":
        return numeric
    if mode == "Cumulative growth":
        first_valid = numeric.dropna()
        return numeric - first_valid.iloc[0] if not first_valid.empty else numeric
    if mode == "Period change":
        return numeric.diff()
    if mode == "Percentage growth":
        first_valid = numeric.dropna()
        if first_valid.empty or first_valid.iloc[0] == 0:
            return numeric * np.nan
        return ((numeric / first_valid.iloc[0]) - 1.0) * 100.0
    if mode == "Indexed growth (100)":
        first_valid = numeric.dropna()
        if first_valid.empty or first_valid.iloc[0] == 0:
            return numeric * np.nan
        return (numeric / first_valid.iloc[0]) * 100.0
    raise ValueError(f"Unsupported mode: {mode}")


def _metric_axis_label(metric: str, mode: str) -> str:
    base = METRIC_LABELS[metric]
    if mode == "Cumulative growth":
        return f"{base} gained"
    if mode == "Period change":
        return f"{base} change"
    if mode == "Percentage growth":
        return f"{base} growth (%)"
    if mode == "Indexed growth (100)":
        return f"{base} index"
    return base


def build_series(
    frame: pd.DataFrame,
    options: PlotOptions,
) -> list[tuple[int, str, str, pd.Series]]:
    selected = frame[
        frame["mod_id"].isin(options.mod_ids)
        & (frame["timestamp"] >= options.start)
        & (frame["timestamp"] <= options.end)
    ].copy()

    results: list[tuple[int, str, str, pd.Series]] = []
    for mod_id in options.mod_ids:
        mod_frame = selected[selected["mod_id"] == mod_id]
        if mod_frame.empty:
            continue

        title = str(mod_frame["display_title"].iloc[-1])
        aggregated = _resample_mod(mod_frame, options.aggregation)

        for metric in options.metrics:
            if metric not in aggregated.columns:
                continue
            series = _transform(aggregated[metric], options.mode)
            if options.smoothing > 1:
                series = series.rolling(
                    options.smoothing, min_periods=1
                ).mean()
            series = series.dropna()
            if not series.empty:
                results.append((mod_id, title, metric, series))
    return results


def render_plot(
    axes: list[Axes],
    frame: pd.DataFrame,
    options: PlotOptions,
) -> int:
    series_data = build_series(frame, options)
    if not series_data:
        for axis in axes:
            axis.clear()
            axis.text(
                0.5,
                0.5,
                "No data for the selected filters.",
                ha="center",
                va="center",
                transform=axis.transAxes,
            )
        return 0

    metrics = list(options.metrics)
    axis_by_metric = {
        metric: axes[index]
        for index, metric in enumerate(metrics)
    }

    for axis in axes:
        axis.clear()

    for mod_id, title, metric, series in series_data:
        axis = axis_by_metric[metric]
        label = f"{title} ({mod_id})"

        if options.chart_type == "Line":
            axis.plot(
                series.index,
                series.values,
                label=label,
                marker="o" if options.show_markers else None,
                markersize=3,
                linewidth=1.8,
            )
        elif options.chart_type == "Step":
            axis.step(
                series.index,
                series.values,
                label=label,
                where="post",
                linewidth=1.8,
            )
        elif options.chart_type == "Area":
            line = axis.plot(
                series.index,
                series.values,
                label=label,
                linewidth=1.6,
            )[0]
            axis.fill_between(
                series.index,
                series.values,
                alpha=0.12,
                color=line.get_color(),
            )
        elif options.chart_type == "Bar":
            width = 0.75 / max(len(options.mod_ids), 1)
            offset = (
                list(options.mod_ids).index(mod_id)
                - (len(options.mod_ids) - 1) / 2
            ) * width
            x = np.arange(len(series)) + offset
            axis.bar(x, series.values, width=width, label=label)
            axis.set_xticks(np.arange(len(series)))
            axis.set_xticklabels(
                [timestamp.strftime("%d %b") for timestamp in series.index],
                rotation=45,
                ha="right",
            )
        else:
            raise ValueError(f"Unsupported chart type: {options.chart_type}")

    for metric, axis in axis_by_metric.items():
        axis.set_title(_metric_axis_label(metric, options.mode))
        axis.set_ylabel(_metric_axis_label(metric, options.mode))
        axis.grid(True, alpha=0.25)
        if options.log_scale and options.mode not in {
            "Period change",
            "Percentage growth",
        }:
            axis.set_yscale("symlog", linthresh=1)
        if options.show_legend:
            axis.legend(loc="best", fontsize="small")
        axis.tick_params(axis="x", rotation=35)

    axes[-1].set_xlabel("Time")
    return len(series_data)


def make_summary(
    frame: pd.DataFrame,
    options: PlotOptions,
) -> pd.DataFrame:
    selected = frame[
        frame["mod_id"].isin(options.mod_ids)
        & (frame["timestamp"] >= options.start)
        & (frame["timestamp"] <= options.end)
    ].copy()

    rows: list[dict[str, object]] = []
    for mod_id in options.mod_ids:
        mod = selected[selected["mod_id"] == mod_id].sort_values("timestamp")
        if mod.empty:
            continue
        title = str(mod["display_title"].iloc[-1])
        for metric in options.metrics:
            values = pd.to_numeric(mod[metric], errors="coerce").dropna()
            if values.empty:
                continue
            first = float(values.iloc[0])
            last = float(values.iloc[-1])
            delta = last - first
            percent = (delta / first * 100.0) if first else np.nan
            rows.append(
                {
                    "Mod": title,
                    "ID": mod_id,
                    "Metric": METRIC_LABELS[metric],
                    "Start": first,
                    "End": last,
                    "Change": delta,
                    "Change %": percent,
                }
            )
    return pd.DataFrame(rows)
