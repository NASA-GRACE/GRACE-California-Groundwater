#!/usr/bin/env python3
# Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), and GitHub Copilot (it/its).

import os
from pathlib import Path
import argparse
import pandas as pd
import matplotlib.pyplot as plt
import logging
import datetime as dt
import re

import run_all as ra

# For trend estimation:
import numpy as np
import matplotlib.dates as mdates


class Options(ra.PlotOptions):
    """Options for plotting time series data."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.PlotOptions and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                          str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_csv_files:         list[Path] = [self.timeseries_dir /  "LATEST.csv"]  # default to intermediate files (not the final groundwater files) by loading the latest CSV in self.timeseries_dir
        self.default_groundwater_files: list[Path] = [self.output_dir     / f"LATEST_groundwater_{self.default_basin_safename}*unsmoothed*.csv"]

        self.timeseries_dir.mkdir(parents=True, exist_ok=True)  # Ensure the timeseries directory exists
        self.output_dir.mkdir(    parents=True, exist_ok=True)  # Ensure the output directory exists

        # Dates at which to break the plotted lines (list of datetime.datetime)
        # self.discontinuities: list[dt.datetime] = []  # Uncomment this line to have no discontinuities
        self.discontinuities: list[dt.datetime] = [ra.parse_datetime(d, timezone='naive') for d in ['2018-05-01']]
        self.estimate_trends = 1  # 1 = estimate trends, 0 = do not estimate
        self.units           = "km³"
        self.dark_mode       = 0  # 1 = dark mode, 0 = light mode


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Plot time series from CSV file(s)")
    parser.add_argument("--csv_files",  nargs="+", type=Path, default=options.default_csv_files, metavar="CSV",
                        help=f"Path(s) to your CSV file(s); if none given, uses the latest .csv file in {os.fspath(options.timeseries_dir)})")
    parser.add_argument("--groundwater", action="store_true",
                        help=f"If set, plot groundwater time series by loading {list(map(os.fspath, options.default_groundwater_files))} (overrides --csv_files if given)")
    parser.add_argument("--full", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    if getattr(options.args, "groundwater", False):
        options.args.csv_files = options.default_groundwater_files
        logging.info(f"--groundwater argument set: using groundwater CSV files {list(map(os.fspath, options.args.csv_files))}")


def main() -> None:
    """Main function to parse arguments and make the plot."""
    options = Options()
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    parse_arguments(options)

    # Any file with "LATEST"
    csv_files = options.args.csv_files
    for i, csv_file in enumerate(csv_files):
        resolved = csv_file
        if "LATEST" in csv_file.name:
            pattern = csv_file.name.replace("LATEST", "*")
            matches = list(csv_file.parent.glob(pattern))
            if not matches:
                raise FileNotFoundError(
                    f"No files matching pattern {pattern} found in {os.fspath(csv_file.parent)}"
                )
            resolved = max(matches, key=lambda p: p.stat().st_mtime)
        # normalize
        csv_files[i] = resolved.expanduser().resolve()
    logging.info(f"Resolved CSV files: {list(map(os.fspath, csv_files))}")

    # Extract datatype for each file, ensure they all match
    dlist = []
    print(f"CSV files to plot: {list(map(os.fspath, csv_files))}")
    print(f"Available datatypes: {options.datatypes}")
    for f in csv_files:
        found = [datatype for datatype in options.datatypes if datatype.casefold() in f.name.casefold()]
        if not found:
            raise ValueError(f"CSV file must contain one of {options.datatypes}: got {f}")
        dlist.append(found[0])
    if len(set(dlist)) != 1:
        logging.warning(f"Expected all CSV files to share the same datatype, but they are: {set(dlist)}")
    datatype = dlist[0]

    # Extract basin title for each file
    basin_titles = []
    for f in csv_files:
        matches = [m for m in options.basin_safenames if m in f.name.casefold()]
        if len(matches) != 1:
            raise ValueError(f"CSV files must contain exactly one basin mask; got {os.fspath(f)}")
        basin_titles.append(options.reverse_safename_map[matches[0]])

    make_plot(options, csv_files, datatype, basin_titles)


def extract_blurb(options: Options, path: str | os.PathLike[str]) -> str | None:
    """
    Extract a blurb from the filename, e.g. "groundwater_smoothed_3mo_water_year.csv" → "smoothed (3mo)".
    Only applies if options.args.groundwater is True.

    Args:
        options: Options instance with various settings. Contains:
           - args.groundwater: boolean flag showing if blurbs are needed.
        path: Path to the CSV file.

    Returns:
        A blurb string if found, else None.
    
    Raises:
        None.
    """
    # Only activate for groundwater plots
    if not getattr(options.args, "groundwater", False):
        return None
    path_str = os.fspath(path)
    path_lower = path_str.casefold()
    m = re.search(r"_smoothed_(\d+)mo_", path_lower)
    if m:
        return f"smoothed ({m.group(1)}mo)"
    if      "unsmoothed" in path_lower:
        return "unsmoothed"
    elif    "water_year" in path_lower:
        return "water year"
    elif "calendar_year" in path_lower:
        return "calendar year"
    logging.warning(f"Could not determine smoothing or year type from filename: {path_str}")
    return None


def make_plot(options: Options, csv_paths: list[Path], datatype: str, basin_titles: list[str],
              plot_title: str | None = None, y_label:  str | None = None) -> None:
    """
    Makes a plot. If len(csv_paths) > 1, put several time series on one axis, cycling through style lists.
    
    Args:
        options:      Options instance with plotting parameters.
        csv_paths:    List of CSV file paths to plot.
        datatype:     Datatype string (available datatypes: options.datatypes).
        basin_titles: List of basin names corresponding to each CSV file.
        plot_title:   Optional plot title override.
        y_label:      Optional y-axis label override.
    
    Returns:
        None. The plot is saved to a PNG file.
    
    Raises:
        ValueError:        If CSV files do not have exactly three columns.
        FileNotFoundError: If any of the CSV files do not exist (raised when pandas tries to read them).
    """
    if len(csv_paths) == 1:
        title  = plot_title or f"{datatype} anomaly in {basin_titles[0]}"
        ylabel = y_label    or f"{datatype} anomaly ({options.units})"
    else:
        title  = plot_title or f"{datatype} anomalies"
        ylabel = y_label    or f"{datatype} anomaly ({options.units})"

    plt.rcParams.update({"font.size": options.fsize, "figure.facecolor": options.background_color})
    fig, ax = plt.subplots(figsize=options.myfigsize, facecolor=options.background_color)
    ax.set_facecolor(options.background_color)
    ax.xaxis.label.set_color(options.text_color)
    ax.yaxis.label.set_color(options.text_color)
    ax.title.set_color(options.text_color)
    ax.tick_params(colors=options.text_color)
    for spine in ax.spines.values():
        spine.set_color(options.text_color)

    # Pull out every blurb
    blurbs = [extract_blurb(options, p) for p in csv_paths]
    # keep only non‐None blurbs
    non_empty = [b for b in blurbs if b]
    # if there's more than one line to plot and exactly one unique blurb, treat it as "common"
    common_blurb = None
    if len(csv_paths) > 1 and non_empty and len(set(non_empty)) == 1:
        common_blurb = non_empty[0]
        title = f"{title}, {common_blurb}"
        include_blurb = False
    else:
        include_blurb = True

    for idx, (path, basin) in enumerate(zip(csv_paths, basin_titles)):
        df = pd.read_csv(path, parse_dates=[0], comment="#", skip_blank_lines=True)
        if df.shape[1] != 3:
            raise ValueError(f"Expected CSV with three columns, got {list(df.columns)} in {os.fspath(path)}")
        # Eliminate any rows with NaN values
        df = df.dropna()
        date_col, val_col, err_col = df.columns

        m  = options.markers        [idx % len(options.markers)]
        ls = options.linestyles     [idx % len(options.linestyles)]
        if options.dark_mode:
            c  = options.lightcolors[idx % len(options.lightcolors)]
            fc = options.colors     [idx % len(options.colors)]
        else:
            c  = options.colors     [idx % len(options.colors)]
            fc = options.lightcolors[idx % len(options.lightcolors)]
        if c == "black":
            edgecolor = "white"
        elif c == "blue":
            edgecolor = "lightgrey"
        else:
            edgecolor = "black"

        the_label = f"{basin}"
        this_blurb = extract_blurb(options, path)
        if include_blurb and this_blurb:
            the_label = f"{the_label}, {this_blurb}"

        # Trend estimation:
        if options.estimate_trends and len(df) >= 2:  # don't try to fit to < 2 pts
            # Convert dates to matplotlib's internal date format
            x = mdates.date2num(df[date_col])
            # fit a line: slope is in "units per day"
            slope, intercept = np.polyfit(x, df[val_col], 1)
            # convert slope to units per year (≈365.25 days)
            trend_per_year = slope * 365.25
            # format it as "+0.23 km³/yr"
            the_label += f", {trend_per_year:+.2f} {options.units}/yr"

        # split df into segments at each discontinuity date
        segments: list[pd.DataFrame]
        if options.discontinuities:
            segments = []
            # make sure all discontinuity datetimes are sorted
            sorted_disc = sorted(d for d in options.discontinuities)
            start = df[date_col].min()
            for disc_date in sorted_disc:
                seg = df[(df[date_col] >= start) & (df[date_col] < disc_date)]
                if not seg.empty:
                    segments.append(seg)
                start = disc_date
            # final segment
            last = df[df[date_col] >= start]
            if not last.empty:
                segments.append(last)
        else:
            segments = [df]

        # now loop over each segment to plot
        first = True
        for seg in segments:
            seg_upper = seg[val_col] + seg[err_col]
            seg_lower = seg[val_col] - seg[err_col]
            ax.plot(seg[date_col], seg[val_col],
                    marker=m, linestyle=ls, color=c,
                    markerfacecolor=c, markeredgecolor=edgecolor,
                    markeredgewidth=0.5, zorder=2, label=the_label if first else None)
            ax.fill_between(seg[date_col], seg_lower, seg_upper,
                            color=fc, alpha=0.5, zorder=1)
            first = False

    ax.set_title(title,   fontsize=options.fsize + 4, color=options.text_color)
    ax.set_ylabel(ylabel, fontsize=options.fsize,     color=options.text_color)

    date_fmt = mdates.DateFormatter("%Y")
    ax.xaxis.set_major_formatter(date_fmt)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")

    if len(csv_paths) > 1 or options.estimate_trends:
        ax.legend(fontsize=options.fsize - 4, facecolor=options.background_color,
                  edgecolor=options.text_color, labelcolor=options.text_color)

    timestamp   = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    darkstring = "dark_mode" if options.dark_mode else "light_mode"
    output_path = options.graphics_dir / (ra.filename_format(f"{datatype}_comparison_{darkstring}_{timestamp}") + ".png")
    fig.savefig(output_path, dpi=options.dpi_choice, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
