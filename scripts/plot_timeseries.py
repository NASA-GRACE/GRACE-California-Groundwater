#!/usr/bin/env python3
# Written in 2025/2026 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), GitHub Copilot (it/its), and Claude Opus 4.6 extended (it/its).
import os
from pathlib import Path
import argparse
import numpy             as np
import pandas            as pd
import matplotlib.pyplot as plt
import matplotlib.dates  as mdates
import datetime          as dt
import logging
import re

import run_all as ra


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

        # ---- Plot selection, choose AT LEAST one. ----
        self.plot_csv_timeseries:             bool = bool(1)  # run the original csv_files-based plot
        self.plot_groundwater_yearly_panels:  bool = bool(1)  # 2-panel: calendar-year + water-year (disabled if --groundwater argument is not set)
        self.plot_components_all_basins:      bool = bool(1)  # 3-panel: SWE / reservoirs / groundwater across basins (disabled if --groundwater argument is not set)
        self.plot_components_one_basin: str | None = self.valid_basins[0]     # e.g. None or "Tulare-Buena Vista Lakes" or self.valid_basins[0,1,2,3]

        # If making groundwater yearly panels, which basin's output files to use:
        # (this is a safename because the filenames use safenames)
        self.yearly_basin_safename:                       str = self.default_basin_safename

        # ---- Styling / behavior knobs ----
        # Break lines at time gaps >= this many years (None disables gap splitting).
        # Matches the notebook’s "split_gaps" concept for yearly plots.
        self.split_gaps_years:                   float | None = 1.5

        # For yearly groundwater plots, only include years with >= this many months used
        # (expects yearly CSV to have column "n_months_used"; if missing, no filtering happens).
        self.min_months_yearly:                           int = 5

        # Component plots (multi-basin and one-basin) gap splitting (months)
        self.components_split_gaps_months:         int | None = 6

        # Component plots: smooth groundwater with this window (months) (None disables)
        self.components_groundwater_smooth_window: int | None = 3

        # If True, rebase all component series to zero at their first point (notebook-like behavior); if False, plot the raw values.
        self.rebase_components_to_first_point:           bool = bool(1)

        self.area_diff_max:        float | None = 0.05     # For comparing areas across CSV files, set to None to disable the warning
        self.plot_thickness:               bool = bool(1)  # If True, plot water equivalent height if basin area is available. Otherwise, plot volume.

        # Dates at which to break the plotted lines (list of datetime.datetime)
        # self.discontinuities: list[dt.datetime] = []  # Uncomment this line to have no discontinuities
        self.discontinuities: list[dt.datetime] = [ra.parse_datetime(d, timezone='naive') for d in ['2018-05-01']]
        self.estimate_trends:               int =  1  # 1 = estimate trends, 0 = do not estimate
        self.title_font:                    int = 16
        self.subtitle_font:                 int = 14
        self.legend_font:                   int =  9
        self.dark_mode:                     int =  0  # 1 = dark mode, 0 = light mode

    @property
    def rc_plot(self) -> dict[str, object]:
        """
        Return a dictionary of rc parameters for plotting.
        This is a property so it can be dynamically generated based on other options (e.g. dark_mode).
        """
        return {
            "font.size"         : self.fsize,
            "figure.facecolor"  : self.background_color,
            # "axes.grid"         : True,
            # "axes.spines.top"   : False,
            # "axes.spines.right" : False,
        }

    @property
    def rc_plot_multipanel(self) -> dict[str, object]:
        """RC parameters for multipanel plots (matching notebook font sizes)."""
        return {
            "font.size"        : 10,
            "figure.facecolor" : self.background_color,
        }


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
    else:
        # Only produce the multi-panel and component plots on the final
        # groundwater invocation, not on every intermediate data-type call.
        options.plot_groundwater_yearly_panels = False
        options.plot_components_all_basins     = False
        logging.info(f"--groundwater argument not set: disabling multi-panel and component plots")


def main() -> None:
    """Main function to parse arguments and make the plot."""
    options = Options()
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    parse_arguments(options)

    options.gap_threshold_years = None
    if options.split_gaps_years is not None:
        options.gap_threshold_years = pd.Timedelta(days=365.25 * float(options.split_gaps_years))

    options.gap_threshold_months = None
    if options.components_split_gaps_months is not None:
        options.gap_threshold_months = pd.Timedelta(days=30.4375 * float(options.components_split_gaps_months))

    did_any = False

    if options.plot_groundwater_yearly_panels:
        make_groundwater_yearly_panels(options)
        did_any = True

    if options.plot_components_all_basins:
        make_components_all_basins_plot(options)
        did_any = True

    if options.plot_components_one_basin:
        make_components_one_basin_plot(options, options.plot_components_one_basin)
        did_any = True

    if options.plot_csv_timeseries:
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
        did_any = True

    if not did_any:
        logging.warning("No plots selected: enable one of the options.plot_* flags.")


def _latest_matching(parent: Path, pattern: str) -> Path:
    """Return the latest file in parent matching pattern, where pattern can contain wildcards like *LATEST*."""
    matches = list(parent.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No files matching {pattern} in {parent}")
    return max(matches, key=lambda p: p.stat().st_mtime)


def _apply_axes_theme(options: Options, ax: plt.Axes) -> None:
    """Apply the background and text colors from options to the given axes."""
    ax.set_facecolor(  options.background_color)
    ax.xaxis.label.set_color(options.text_color)
    ax.yaxis.label.set_color(options.text_color)
    ax.title.set_color(      options.text_color)
    ax.tick_params(   colors=options.text_color)
    for spine in ax.spines.values():
        spine.set_color(options.text_color)


def _resolve_unit_factor(options: Options, path: str | os.PathLike[str],
                         context: str = "") -> tuple[float, str]:
    """
    If plot_thickness is True, attempt to read basin area from the CSV header and
    compute the options.volume_units_pretty -> options.thickness_units conversion factor.
    When area metadata is absent, fall back to (1.0, options.volume_units_pretty).

    Returns:
        (unit_factor, effective_units) — e.g. (6.547, "mm") or (1.0, "km³").
    """
    if not options.plot_thickness:
        return 1.0, options.volume_units_pretty
    mean_area_m2, unit_factor = ra.resolve_unit_factor(
        path, area_diff_max=options.area_diff_max, context=context,
    )
    if mean_area_m2 is not None:
        return unit_factor, options.thickness_units
    return 1.0, options.volume_units_pretty


def make_groundwater_yearly_panels(options: Options) -> None:
    """
    Create a figure with two panels showing groundwater anomalies for the default basin,
    one panel for calendar-year averages and one for water-year averages.
    """
    with plt.rc_context(options.rc_plot_multipanel):
        basin_safe  = options.yearly_basin_safename
        basin_title = options.reverse_safename_map.get(basin_safe, basin_safe)

        cal_path = _latest_matching(options.output_dir, f"*groundwater_{basin_safe}_*calendar_year_averages*.csv")
        wat_path = _latest_matching(options.output_dir, f"*groundwater_{basin_safe}_*water_year_averages*.csv")

        unit_factor, effective_units = _resolve_unit_factor(
            options, cal_path,
            context=f"{basin_title} yearly groundwater ({cal_path.name})")
        if options.plot_thickness and effective_units != options.thickness_units:
            raise ValueError(f"plot_thickness=True but no total_area_m2* entries found in yearly groundwater CSV header for {basin_title}.")

        cal = ra.load_plot_timeseries(cal_path, date_col="date")
        wat = ra.load_plot_timeseries(wat_path, date_col="date")

        if options.plot_thickness:
            cal                 = cal.copy()
            wat                 = wat.copy()
            cal["groundwater"] *= unit_factor
            cal["error"]       *= unit_factor
            wat["groundwater"] *= unit_factor
            wat["error"]       *= unit_factor

        min_months = options.min_months_yearly
        if "n_months_used" in cal.columns:
            cal = cal[cal["n_months_used"] >= min_months]
        if "n_months_used" in wat.columns:
            wat = wat[wat["n_months_used"] >= min_months]

        fig, axes = plt.subplots(2, 1, figsize=(12, 10), sharex=False)
        _apply_axes_theme(options, axes[0])
        _apply_axes_theme(options, axes[1])

        ra.plot_with_uncertainty(
            axes[0], cal, value_col="groundwater", error_col="error",
            label=f"Calendar-year average (only years with {min_months}+ months of data)",
            marker="o", linestyle="-",
            gap_threshold=getattr(options, "gap_threshold_years", None),
        )
        axes[0].set_title(f"Calendar-year groundwater anomalies – {basin_title}", fontsize=options.title_font)
        axes[0].set_ylabel(f"Groundwater anomaly ({effective_units}, yearly mean)")
        axes[0].legend()
        axes[0].grid(True)

        ra.plot_with_uncertainty(
            axes[1], wat, value_col="groundwater", error_col="error",
            label=f"Water-year average (only years with {min_months}+ months of data)",
            marker="s", linestyle="-",
            gap_threshold=getattr(options, "gap_threshold_years", None),
        )
        axes[1].set_title(f"Water-year groundwater anomalies – {basin_title}", fontsize=options.title_font)
        axes[1].set_xlabel("Year (centered)")
        axes[1].set_ylabel(f"Groundwater anomaly ({effective_units}, yearly mean)")
        axes[1].legend()
        axes[1].grid(True)

        plt.tight_layout()

        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = options.graphics_dir / f"groundwater_yearly_panels_{basin_safe}_{timestamp}.png"
        fig.savefig(out, dpi=options.dpi_choice, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)


def make_components_all_basins_plot(options: Options) -> None:
    """
    Create a figure with three panels showing SWE, reservoir anomaly, and groundwater anomaly across all basins.
    """
    with plt.rc_context(options.rc_plot_multipanel):
        effective_units = options.thickness_units if options.plot_thickness else options.volume_units_pretty
        components = [
            ("swe",         "Snow water equivalent (SWE)", f"SWE ({effective_units})"),
            ("reservoirs",  "Reservoir storage anomaly",   f"Reservoir anomaly ({effective_units})"),
            ("groundwater", "Groundwater anomaly",         f"Groundwater anomaly ({effective_units})"),
        ]

        series_by_component = {c[0]: {} for c in components}
        basins_with_any_data = set()

        for basin in options.valid_basins:
            for comp, _, _ in components:
                df = ra.load_component_series(options, comp, basin)
                if df is not None and not df.empty:
                    series_by_component[comp][basin] = df
                    basins_with_any_data.add(basin)

        basin_unit_factor: dict[str, float] = {}

        if options.plot_thickness:
            for basin, gw_df in series_by_component.get("groundwater", {}).items():
                src = gw_df.attrs.get("source_path")
                if not src:
                    continue
                uf, eu = _resolve_unit_factor(
                    options, src,
                    context=f"{basin} component plot ({Path(src).name})")
                if eu == options.thickness_units:
                    basin_unit_factor[basin] = uf

        if not basins_with_any_data:
            logging.warning("No multi-basin component data found.")
            return

        basin_list  = sorted(basins_with_any_data)
        color_cycle = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        basin_color = {b: color_cycle[i % len(color_cycle)] for i, b in enumerate(basin_list)}

        fig, axes   = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
        _apply_axes_theme(options, axes[0])
        _apply_axes_theme(options, axes[1])
        _apply_axes_theme(options, axes[2])

        for ax, (comp, title, ylab) in zip(axes, components):
            comp_dict = series_by_component[comp]
            if not comp_dict:
                ax.text(0.5, 0.5, f"No {comp} data found", transform=ax.transAxes, ha="center", va="center")
                ax.set_axis_off()
                continue

            for basin, df in comp_dict.items():
                if options.plot_thickness and basin not in basin_unit_factor:
                    raise ValueError(f"{basin}: plot_thickness=True but could not compute mean area.")
                unit_factor = basin_unit_factor.get(basin, 1.0)

                ra.plot_prepped_with_uncertainty(
                    ax,
                    df,
                    label=basin,
                    color=basin_color[basin],
                    gap_threshold=getattr(options, "gap_threshold_months", None),
                    shift_to_zero=(comp == "swe"),
                    smooth_window=(options.components_groundwater_smooth_window if comp == "groundwater" else None),
                    rebase_to_first_point=options.rebase_components_to_first_point,
                    unit_factor=unit_factor,
                    alpha_band=0.2,
                )

            ax.set_title(title, fontsize=options.subtitle_font)
            ax.set_ylabel(ylab)
            if ax.get_legend_handles_labels()[0]:
                ax.legend(loc="upper left", fontsize=options.legend_font)

        fig.suptitle("Snow water equivalent, reservoirs anomaly, and groundwater anomaly across basins", fontsize=options.title_font)
        fig.tight_layout(rect=[0, 0, 1, 0.96])

        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = options.graphics_dir / f"components_all_basins_{timestamp}.png"
        fig.savefig(out, dpi=options.dpi_choice, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)


def make_components_one_basin_plot(options: Options, basin_name: str) -> None:
    """Create a figure showing SWE, reservoir anomaly, and groundwater anomaly for a single basin."""
    if basin_name not in options.valid_basins:
        raise ValueError(f"Invalid basin '{basin_name}'. Valid basins: {options.valid_basins}")

    with plt.rc_context(options.rc_plot_multipanel):
        components = [
            ("swe",         "Snow water equivalent"),
            ("reservoirs",  "Reservoir storage anomaly"),
            ("groundwater", "Groundwater anomaly"),
        ]

        fig, ax   = plt.subplots(figsize=(12, 6))
        _apply_axes_theme(options, ax)
        found_any = False

        unit_factor     = 1.0
        effective_units = options.volume_units_pretty
        gw_df           = ra.load_component_series(options, "groundwater", basin_name)
        if options.plot_thickness:
            src = gw_df.attrs.get("source_path") if gw_df is not None else None
            if src is not None:
                unit_factor, effective_units = _resolve_unit_factor(
                    options, src,
                    context=f"{basin_name} one-basin component plot ({Path(src).name})")
                if effective_units != options.thickness_units:
                    raise ValueError(f"{basin_name}: plot_thickness=True but could not compute mean area.")
            else:
                raise ValueError(f"{basin_name}: plot_thickness=True but groundwater data not available for area lookup.")

        for comp, pretty in components:
            if comp == "groundwater":
                df = gw_df
            else:
                df = ra.load_component_series(options, comp, basin_name)
            if df is None or df.empty:
                continue
            found_any = True
            ra.plot_prepped_with_uncertainty(
                ax,
                df,
                label=pretty,
                gap_threshold=getattr(options, "gap_threshold_months", None),
                shift_to_zero=(comp == "swe"),
                smooth_window=(options.components_groundwater_smooth_window if comp == "groundwater" else None),
                rebase_to_first_point=options.rebase_components_to_first_point,
                alpha_band=0.2,
                unit_factor=unit_factor,
            )

        if not found_any:
            logging.warning(f"No SWE/reservoir/groundwater data found for basin '{basin_name}'.")
            plt.close(fig)
            return

        ax.set_title(f"Snow water equivalent, reservoirs anomaly, and groundwater anomaly – {basin_name}", fontsize=options.title_font)
        if options.plot_thickness:
            ax.set_ylabel(f"Water height ({effective_units})")
        else:
            ax.set_ylabel(f"Water volume ({effective_units})")
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc="upper left", fontsize=options.legend_font)
        plt.tight_layout()

        safe      = options.basin_safename_map.get(basin_name, ra.safestring(basin_name))
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out       = options.graphics_dir / f"components_one_basin_{safe}_{timestamp}.png"
        fig.savefig(out, dpi=options.dpi_choice, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)


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
    with plt.rc_context(options.rc_plot):
        # Determine effective units: options.thickness_units if area metadata is available, options.volume_units_pretty otherwise.
        # All files in one make_plot call share the same datatype, so the first file
        # is representative.
        _, effective_units = _resolve_unit_factor(
            options, csv_paths[0],
            context=f"make_plot units check ({csv_paths[0].name})")
        if len(csv_paths) == 1:
            title  = plot_title or f"{datatype} anomaly in {basin_titles[0]}"
            ylabel = y_label    or f"{datatype} anomaly ({effective_units})"
        else:
            if len(set(basin_titles)) == 1:
                title = plot_title or f"{datatype} anomalies – {basin_titles[0]}"
            else:
                title = plot_title or f"{datatype} anomalies"
            ylabel = y_label or f"{datatype} anomaly ({effective_units})"

        fig, ax = plt.subplots(figsize=options.myfigsize, facecolor=options.background_color)
        _apply_axes_theme(options, ax)

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
            df = ra.load_plot_timeseries(path, date_col=0)  # returns DatetimeIndex

            # Identify value/error columns robustly
            cols = list(df.columns)

            # Prefer common names
            if "groundwater" in cols and "error" in cols:
                val_col, err_col = "groundwater", "error"
            elif "value" in cols and "error" in cols:
                val_col, err_col = "value", "error"
            else:
                # fallback: first two numeric columns
                num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
                if len(num_cols) < 2:
                    raise ValueError(f"Could not infer value/error columns in {os.fspath(path)}; columns={cols}")
                val_col, err_col = num_cols[0], num_cols[1]

            df = df[[val_col, err_col]].dropna()

            # Unit scaling from volume to thickness (e.g., km³ -> mm water equivalent height). Error scales identically.
            unit_factor, _ = _resolve_unit_factor(
                options, path,
                context=f"{basin} make_plot ({path.name})")
            df[val_col] *= unit_factor
            df[err_col] *= unit_factor

            m  = options.markers        [idx % len(options.markers)]
            ls = options.linestyles     [idx % len(options.linestyles)]
            if options.dark_mode:
                c  = options.lightcolors[idx % len(options.lightcolors)]
            else:
                c  = options.colors     [idx % len(options.colors)]

            the_label = f"{basin}"
            this_blurb = extract_blurb(options, path)
            if include_blurb and this_blurb:
                the_label = f"{the_label}, {this_blurb}"

            # Trend estimation:
            if options.estimate_trends and len(df) >= 2:  # don't try to fit to < 2 pts
                # Convert dates to matplotlib's internal date format
                x = mdates.date2num(df.index.to_pydatetime())
                # fit a line: slope is in "units per day"
                slope, intercept = np.polyfit(x, df[val_col], 1)
                # convert slope to units per year (≈365.25 days)
                trend_per_year = slope * 365.25
                # format it as "+0.23 km³/yr" or "+1.5 mm/yr" depending on effective_units
                the_label += f", {trend_per_year:+.2f} {effective_units}/yr"

            # Build a temporary frame with standardized names for plotting
            plot_df = df[[val_col, err_col]].rename(columns={val_col: "value", err_col: "error"})

            ra.plot_with_uncertainty(
                ax,
                plot_df,
                value_col="value",
                error_col="error",
                label=the_label,
                color=c,
                marker=m,
                linestyle=ls,
                gap_threshold=getattr(options, "gap_threshold_years", None),
                discontinuities=options.discontinuities,
                alpha_band=0.2,
            )

        ax.set_title(title,   fontsize=options.fsize + 4, color=options.text_color)
        ax.set_ylabel(ylabel, fontsize=options.fsize,     color=options.text_color)

        date_fmt = mdates.DateFormatter("%Y")
        ax.xaxis.set_major_formatter(date_fmt)
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")

        if len(csv_paths) > 1 or options.estimate_trends or getattr(options.args, "groundwater", False):
            ax.legend(fontsize=options.fsize - 4,
                      facecolor=options.background_color,
                      edgecolor=options.text_color,
                      labelcolor=options.text_color)

        timestamp   = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        darkstring  = "dark_mode" if options.dark_mode else "light_mode"
        output_path = options.graphics_dir / (ra.filename_format(f"{datatype}_comparison_{darkstring}_{timestamp}") + ".png")
        fig.savefig(output_path, dpi=options.dpi_choice, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)


if __name__ == "__main__":
    main()
