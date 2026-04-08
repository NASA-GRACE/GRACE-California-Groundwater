#!/usr/bin/env python3
"""
Written in 2025/2026 at JPL by Emmy Killett (she/her), Munish Sikka (he/him), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), GitHub Copilot (it/its), and Claude Opus 4.6 extended (it/its)


Compute a "groundwater" time series by subtracting snow water equivalent mass,
soil moisture mass, and reservoirs mass from total water mass (obtained from GRACE),
while propagating (presumably independent) uncertainties as variances.

Each input CSV should have at least these columns:
    date:        Date or datetime (ISO format)
    value:       Measured mass (e.g., mm water equivalent)
    error:       Associated uncertainty (standard deviation)

The output CSV will include:
    date:        Aligned datetime index
    groundwater: Computed groundwater mass
    error:       Propagated uncertainty
"""
import os
import argparse
import pandas as pd
import numpy as np
import logging
from pathlib import Path
import json
import re
import datetime as dt

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                   str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_soil_moisture_csv: str = f"LATEST_{self.soil_moisture_model}_FOR_BASIN.csv"
        self.default_reservoirs_csv:    str = f"LATEST_{self.reservoirs_model}_FOR_BASIN.csv"
        self.default_swe_csv:           str = f"LATEST_{self.swe_model}_FOR_BASIN.csv"
        self.default_grace_csv:         str = "LATEST_GRACE_FOR_BASIN.csv"
        self.default_output_csv:        str = f"anomaly_timeseries_groundwater_{self.default_basin_safename}_DATA_START_to_DATA_END_created_on_CURRENT_DATETIME.csv"
        self.default_output_gw_tws_csv: str = f"anomaly_timeseries_groundwater_and_tws_{self.default_basin_safename}_DATA_START_to_DATA_END_created_on_CURRENT_DATETIME.csv"
        self.default_all_output_csv:    str = f"anomaly_timeseries_all_{self.default_basin_safename}_DATA_START_to_DATA_END_created_on_CURRENT_DATETIME.csv"
        self.default_window_size:       int = 3  # default window size for the moving average used in smoothing the output
        self.timeseries_dir.mkdir(parents=True, exist_ok=True)  # Ensure the timeseries directory exists


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Compute groundwater series with uncertainty propagation")
    parser.add_argument("-b", "--basin", type=str, default=options.default_basin,
                        help=f"Basin identifier ({', '.join(options.valid_basins)}).")
    parser.add_argument(f"--soilm", type=str, default=options.default_soil_moisture_csv,
                        help=f"Input  {options.soil_moisture_model} CSV file in {options.timeseries_dir} (default: {options.default_soil_moisture_csv})")
    parser.add_argument(f"--reservoirs", type=str, default=options.default_reservoirs_csv,
                        help=f"Input   {options.reservoirs_model} CSV file in {options.timeseries_dir} (default: {options.default_reservoirs_csv})")
    parser.add_argument(f"--swe", type=str, default=options.default_swe_csv,
                        help=f"Input {options.swe_model} CSV file in {options.timeseries_dir} (default: {options.default_swe_csv})")
    parser.add_argument("--grace", type=str, default=options.default_grace_csv,
                        help=f"Input  GRACE CSV file in {options.timeseries_dir} (default: {options.default_grace_csv})")
    parser.add_argument("--output", type=str, default=options.default_output_csv,
                        help=f"Output CSV path (default: {options.default_output_csv})")
    parser.add_argument("--window_size", type=int, default=options.default_window_size,
                        help=f"Window size for the moving average used in smoothing the output (default: {options.default_window_size})")
    parser.add_argument("--full", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG


def main() -> None:
    """Main function to parse arguments, load data, compute groundwater, and save results."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    basin_title = ra.safestring(options.args.basin)
    window_size = options.args.window_size

    if options.args.grace == options.default_grace_csv:  # If user-specified input GRACE file is the default placeholder
        options.args.grace      = (options.timeseries_dir / f"anomaly_timeseries_GRACE_{basin_title}_mask.csv").resolve()
        logging.info(f"Using GRACE data from {options.args.grace}")
    if options.args.swe == options.default_swe_csv:  # If user-specified input SWE file is the default placeholder
        options.args.swe        = (options.timeseries_dir / f"anomaly_timeseries_{options.swe_model}_{basin_title}_mask.csv").resolve()
        logging.info(f"Using {options.swe_model} data from {options.args.swe}")
    if options.args.reservoirs == options.default_reservoirs_csv:  # If user-specified input reservoirs file is the default placeholder
        options.args.reservoirs = (options.timeseries_dir / f"anomaly_timeseries_{options.reservoirs_model}_{basin_title}_mask.csv").resolve()
        logging.info(f"Using {options.reservoirs_model} data from {options.args.reservoirs}")
    if options.args.soilm == options.default_soil_moisture_csv:  # If user-specified input soil moisture file is the default placeholder
        # Find the latest soil moisture file in the directory
        glob_pattern = f"*{options.soil_moisture_model}_{basin_title}*.csv"
        if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug(f"Looking for soil moisture files with pattern: {glob_pattern}")
        soil_moisture_files = list(options.timeseries_dir.glob(glob_pattern))
        if soil_moisture_files:
            options.args.soilm = max(soil_moisture_files, key=os.path.getmtime)
            logging.info(f"Using {options.soil_moisture_model} data from {options.args.soilm}")
        else:
            raise FileNotFoundError(f"No {options.soil_moisture_model} files found for {options.args.basin}.")
    # Create a timestamp for the output filename
    timestamp = ra.parse_datetime("NOW", timezone="America/Los_Angeles").strftime("%Y%m%d-%H%M%S")
    if options.args.output == options.default_output_csv:
        options.args.output = options.output_dir / options.default_output_csv.replace("CURRENT_DATETIME", timestamp)
    options.args.output        = Path(options.args.output).expanduser().resolve()
    options.args.output_gw_tws = options.output_dir_gw_tws / options.default_output_gw_tws_csv.replace("CURRENT_DATETIME", timestamp)
    options.args.output_gw_tws = Path(options.args.output_gw_tws).expanduser().resolve()
    options.args.output_all    = options.output_dir_gw_tws / options.default_all_output_csv.replace("CURRENT_DATETIME", timestamp)
    options.args.output_all    = Path(options.args.output_all).expanduser().resolve()
    logging.info(f"Output will be saved to {options.args.output}")

    # Load input series

    grace = load_series(options.args.grace)
    logging.info(f"Loaded GRACE data with {len(grace)} entries.")
    show_monthly_duplicates(grace, "GRACE")
    # Read GRACE header from its CSV and prepare multi-section header for outputs
    grace_header_attrs = _read_csv_header_attrs(options.args.grace)

    swe = load_series(options.args.swe)
    logging.info(f"Loaded {options.swe_model} data with {len(swe)} entries.")
    show_monthly_duplicates(swe, options.swe_model)
    # Read SWE header from its CSV and prepare multi-section header for outputs
    swe_header_attrs = _read_csv_header_attrs(options.args.swe)

    soil_moisture = load_series(options.args.soilm)
    logging.info(f"Loaded {options.soil_moisture_model} data with {len(soil_moisture)} entries.")
    show_monthly_duplicates(soil_moisture, options.soil_moisture_model)
    # Read soil moisture header from its CSV and prepare multi-section header for outputs
    soil_header_attrs = _read_csv_header_attrs(options.args.soilm)

    reservoirs = load_series(options.args.reservoirs)
    logging.info(f"Loaded {options.reservoirs_model} data with {len(reservoirs)} entries.")
    show_monthly_duplicates(reservoirs, options.reservoirs_model)
    # Read reservoirs header from its CSV and prepare multi-section header for outputs
    reservoirs_header_attrs = _read_csv_header_attrs(options.args.reservoirs)

    header_sections = {
        "soil_moisture":         soil_header_attrs,
        "snow_water_equivalent": swe_header_attrs,
        "reservoirs":            reservoirs_header_attrs,
        "grace":                 grace_header_attrs,
    }

    # Resolve basin area and volume→thickness conversion factor from input CSV headers
    mean_area, unit_factor = ra.resolve_unit_factor(options,
        options.args.grace, options.args.swe, options.args.soilm,
        area_diff_max=0.05, context=basin_title,
    )
    options.mean_area = mean_area  # used by _write_df_with_header

    # Compute groundwater and error
    sw, tws, df_all_components = compute_groundwater(options, grace, swe, soil_moisture, reservoirs)
    df_tws_gw = pd.concat([sw, tws], axis=1)
    logging.info(f"Computed groundwater series with {len(sw)} entries.")

    # Include the actual baseline period used for mean removal in each output header
    baseline_start_str = options.actual_baseline_start.strftime("%Y-%m-%d")
    baseline_end_str   = options.actual_baseline_end.strftime("%Y-%m-%d")
    for _sec in header_sections:
        header_sections[_sec]["mean_removal_baseline_start"] = [baseline_start_str]
        header_sections[_sec]["mean_removal_baseline_end"]   = [baseline_end_str]

    # Record actual start and end dates of the combined time series:
    data_start_monthly = sw.index.min().strftime("%Y-%m")
    data_end_monthly   = sw.index.max().strftime("%Y-%m")
    data_start_yearly  = sw.index.min().strftime("%Y")
    data_end_yearly    = sw.index.max().strftime("%Y")

    desc_monthly_unsmoothed    =  "Monthly unsmoothed values. No temporal smoothing has been applied."
    desc_monthly_smoothed      = f"Monthly values smoothed with a {window_size}-month centered moving average. Errors are propagated through the same moving window."
    desc_cal_year_averages     = "Calendar-year averages. Each value represents the average of all months in that calendar year."
    desc_water_year_averages   = "Water-year averages. Each value represents the average of all months in that water year (starting in October of the previous calendar year and ending in September of the calendar year)."

    # Save results
    monthly_unsmoothed_output_path = _append_suffix_before_ext(options.args.output, "_monthly_unsmoothed")
    if "DATA_START_to_DATA_END" in monthly_unsmoothed_output_path.name:
        monthly_unsmoothed_output_path = monthly_unsmoothed_output_path.with_name(monthly_unsmoothed_output_path.name.replace("DATA_START", data_start_monthly).replace("DATA_END", data_end_monthly))
    _write_df_with_header(options, sw, monthly_unsmoothed_output_path, index_label="date",
                          sections=header_sections, digits_after_decimal=options.digits_after_decimal,
                          description=desc_monthly_unsmoothed)
    logging.info(f"Groundwater series (monthly, unsmoothed) written to {monthly_unsmoothed_output_path}")

    # Save separate CSV file for groundwater and tws
    monthly_unsmoothed_output_path_gw_tws = _append_suffix_before_ext(options.args.output_gw_tws, "_monthly_unsmoothed")
    if "DATA_START_to_DATA_END" in monthly_unsmoothed_output_path_gw_tws.name:
        monthly_unsmoothed_output_path_gw_tws = monthly_unsmoothed_output_path_gw_tws.with_name(monthly_unsmoothed_output_path_gw_tws.name.replace("DATA_START", data_start_monthly).replace("DATA_END", data_end_monthly))
    df_tws_gw_for_disk = df_tws_gw.rename(columns={
        "grace"     : "total water storage",
        "err_grace" : "total water storage error",
        "error"     : "groundwater error",
    })
    _write_df_with_header(options, df_tws_gw_for_disk, monthly_unsmoothed_output_path_gw_tws, index_label="date",
                          sections=header_sections, digits_after_decimal=options.digits_after_decimal,
                          description=desc_monthly_unsmoothed)

    # Save smoothed version of the groundwater and tws CSV
    smoothed_gw_tws = df_tws_gw_for_disk.copy()
    smoothed_gw_tws = ra.smooth_value_error(smoothed_gw_tws, value_col="groundwater",         error_col="groundwater error",         window=window_size)
    smoothed_gw_tws = ra.smooth_value_error(smoothed_gw_tws, value_col="total water storage", error_col="total water storage error", window=window_size)
    smoothed_output_path_gw_tws = _append_suffix_before_ext(options.args.output_gw_tws, f"_monthly_smoothed_{window_size}mo")
    if "DATA_START_to_DATA_END" in smoothed_output_path_gw_tws.name:
        smoothed_output_path_gw_tws = smoothed_output_path_gw_tws.with_name(smoothed_output_path_gw_tws.name.replace("DATA_START", data_start_monthly).replace("DATA_END", data_end_monthly))
    _write_df_with_header(options, smoothed_gw_tws, smoothed_output_path_gw_tws, index_label="date",
                          sections=header_sections, digits_after_decimal=options.digits_after_decimal,
                          description=desc_monthly_smoothed)
    logging.info(f"Groundwater-and-TWS series (monthly, smoothed) written to {smoothed_output_path_gw_tws}")

# Save CSV with all components (TWS, SWE, soil moisture, reservoirs, groundwater)
    ALL_COLUMN_PAIRS = [
        ("total water storage",    "total water storage error"),
        ("snow water equivalent",  "snow water equivalent error"),
        ("soil moisture",          "soil moisture error"),
        ("reservoirs",             "reservoirs error"),
        ("groundwater estimate",   "groundwater estimate error"),
    ]
    # The "reservoirs" column doesn't need renaming (the internal name already matches the desired output name),
    # so it's intentionally absent from the rename dict.
    df_all = df_all_components.rename(columns={
        "grace":          "total water storage",
        "err_grace":      "total water storage error",
        "swe":            "snow water equivalent",
        "err_swe":        "snow water equivalent error",
        "soilm":          "soil moisture",
        "err_soilm":      "soil moisture error",
        "err_reservoirs": "reservoirs error",
        "groundwater":    "groundwater estimate",
        "error":          "groundwater estimate error",
    })[[col for pair in ALL_COLUMN_PAIRS for col in pair]]

    monthly_unsmoothed_output_path_all = _append_suffix_before_ext(options.args.output_all, "_monthly_unsmoothed")
    if "DATA_START_to_DATA_END" in monthly_unsmoothed_output_path_all.name:
        monthly_unsmoothed_output_path_all = monthly_unsmoothed_output_path_all.with_name(monthly_unsmoothed_output_path_all.name.replace("DATA_START", data_start_monthly).replace("DATA_END", data_end_monthly))
    _write_df_with_header(options, df_all, monthly_unsmoothed_output_path_all, index_label="date",
                          sections=header_sections, digits_after_decimal=options.digits_after_decimal,
                          description=desc_monthly_unsmoothed)
    logging.info(f"All-component series (monthly, unsmoothed) written to {monthly_unsmoothed_output_path_all}")

    smoothed_all = df_all.copy()
    for val_col, err_col in ALL_COLUMN_PAIRS:
        smoothed_all = ra.smooth_value_error(smoothed_all, value_col=val_col, error_col=err_col, window=window_size)
    smoothed_output_path_all = _append_suffix_before_ext(options.args.output_all, f"_monthly_smoothed_{window_size}mo")
    if "DATA_START_to_DATA_END" in smoothed_output_path_all.name:
        smoothed_output_path_all = smoothed_output_path_all.with_name(smoothed_output_path_all.name.replace("DATA_START", data_start_monthly).replace("DATA_END", data_end_monthly))
    _write_df_with_header(options, smoothed_all, smoothed_output_path_all, index_label="date",
                          sections=header_sections, digits_after_decimal=options.digits_after_decimal,
                          description=desc_monthly_smoothed)
    logging.info(f"All-component series (monthly, smoothed) written to {smoothed_output_path_all}")

    # Smooth the time series
    logging.info(f"Smoothing the groundwater series with a centered moving average of {window_size} months.")
    sw_smoothed = ra.smooth_value_error(sw, value_col="groundwater", error_col="error", window=window_size)
    smoothed_output_path = _append_suffix_before_ext(options.args.output, f"_monthly_smoothed_{window_size}mo")
    if "DATA_START_to_DATA_END" in smoothed_output_path.name:
        smoothed_output_path = smoothed_output_path.with_name(smoothed_output_path.name.replace("DATA_START", data_start_monthly).replace("DATA_END", data_end_monthly))
    _write_df_with_header(options, sw_smoothed, smoothed_output_path, index_label="date",
                          sections=header_sections, digits_after_decimal=options.digits_after_decimal,
                          description=desc_monthly_smoothed)
    logging.info(f"Groundwater series (monthly, smoothed) written to {smoothed_output_path}")

    # Compute calendar-year averages
    logging.info("Computing calendar-year averages of the groundwater series.")
    sw_cal_yr = ra.average_timeseries(sw, year_type="calendar", value_col="groundwater", error_col="error")
    cal_yr_output_path = _append_suffix_before_ext(options.args.output, "_calendar_year_averages")
    if "DATA_START_to_DATA_END" in cal_yr_output_path.name:
        cal_yr_output_path = cal_yr_output_path.with_name(cal_yr_output_path.name.replace("DATA_START", data_start_yearly).replace("DATA_END", data_end_yearly))
    _write_df_with_header(options, sw_cal_yr, cal_yr_output_path, index_label="date",
                          sections=header_sections, digits_after_decimal=options.digits_after_decimal,
                          description=desc_cal_year_averages)
    logging.info(f"Groundwater series (calendar-year averages) written to {cal_yr_output_path}")

    # Compute water-year averages
    logging.info("Computing water-year averages of the groundwater series.")
    sw_wat_yr = ra.average_timeseries(sw, year_type="water", value_col="groundwater", error_col="error")
    wat_yr_output_path = _append_suffix_before_ext(options.args.output, "_water_year_averages")
    if "DATA_START_to_DATA_END" in wat_yr_output_path.name:
        wat_yr_output_path = wat_yr_output_path.with_name(wat_yr_output_path.name.replace("DATA_START", data_start_yearly).replace("DATA_END", data_end_yearly))
    _write_df_with_header(options, sw_wat_yr, wat_yr_output_path, index_label="date",
                          sections=header_sections, digits_after_decimal=options.digits_after_decimal,
                          description=desc_water_year_averages)
    logging.info(f"Groundwater series (water-year averages) written to {wat_yr_output_path}")


def load_series(path: str | os.PathLike[str], date_col: str = "date", target_day_of_month: int = 15) -> pd.DataFrame:
    """
    Load a time series CSV with one date column and two data columns.
    Whatever the column names are, they get renamed to ["value","error"].

    Args:
        path:                Path to the input CSV file.
        date_col:            Name of the date column in the CSV (default "date").
        target_day_of_month: Day of month to which all dates are aligned (default 15).

    Returns:
        DataFrame with index as datetime and columns ["value","error"].

    Raises:
        ValueError: If the CSV does not have exactly two data columns besides the date column.
    """

    logging.info(f"Loading time series from {path} with date column '{date_col}', setting the day of the month to target_day_of_month to ignore differences between datasets that record data at different times of the month.")
    df = pd.read_csv(
        path,
        comment="#",
        skip_blank_lines=True,
        # engine="python",           # uncomment if you ever hit odd parsing cases
        converters={date_col: lambda x: pd.to_datetime(x).replace(day=target_day_of_month)}
    )

    df = df.set_index(date_col)
    # collapse multiple points in the same month to one average value
    df = df.resample("MS").first()
    df.index = df.index + pd.DateOffset(days=target_day_of_month-1)  # shift timestamps to the target day of month
    # assume the only other two columns are the series + its error
    data_cols = list(df.columns)
    if len(data_cols) != 2:
        raise ValueError(f"Expected exactly two data columns, got {data_cols!r}")
    df = df.rename(columns={
        data_cols[0]: "value",
        data_cols[1]: "error"
    })
    return df[["value", "error"]]


def show_monthly_duplicates(df: pd.DataFrame, name: str) -> None:
    """
    Show any duplicate months in the DataFrame index.

    Args:
        df:   The DataFrame to check for duplicate months.
        name: A name to identify the DataFrame in log messages.

    Returns:
        None

    Raises:
        None
    """
    # keep=False marks *all* occurrences of a duplicated label
    dup_idx = df.index[df.index.duplicated(keep=False)]
    if not dup_idx.empty:
        logging.info(f"\n{name} has {len(dup_idx)} total rows on these duplicate months:")
        for month in sorted(dup_idx.unique()):
            # show each month and the rows that fell into it
            logging.info(f"\n–– {month.date()} ––")
            logging.info(df.loc[month])


def _read_csv_header_attrs(path: str | os.PathLike[str]) -> dict[str, list[str]]:
    """
    Read top-of-file commented header lines of the strict form:
        # key: [json-array]
    Stop at the first non-comment line. Returns {key: list[str]}.
    """
    header: dict[str, list[str]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            # strip leading '#', keep empty comment lines out
            text = line[1:].strip()
            # If the comment is a bare URL like "https://..." or "ftp://...", store as {scheme: [full_url]}
            m = re.match(r'^([A-Za-z][A-Za-z0-9+.\-]*)://.+$', text)
            if m:
                header.setdefault(m.group(1), []).append(text)
                continue
            if not text or ":" not in text:
                continue
            key, raw = text.split(":", 1)
            key = key.strip()
            raw = raw.strip()
            try:
                val = json.loads(raw)
                if isinstance(val, list):
                    # Special-case: for a "history" list with multiple entries,
                    # keep only the most recent ISO timestamp.
                    if key.lower() == "history" and len(val) > 1:
                        ts = []
                        for item in val:
                            mm = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(item))
                            if mm:
                                try:
                                    ts.append(dt.datetime.fromisoformat(mm.group(0)))
                                except Exception:
                                    pass
                        if ts:
                            latest = max(ts)
                            header[key] = [f"most recent created on date: {latest.isoformat()}"]
                            continue
                    header[key] = [str(x) for x in val]
                else:
                    header[key] = [str(val)]
            except Exception:
                header[key] = [raw]
    return header


def _write_df_with_header(options: Options, df: pd.DataFrame,
                          out_path: os.PathLike[str] | str,
                          index_label: str = "date",
                          sections: dict[str, dict[str, list[str]]] | None = None,
                          digits_after_decimal: int | None = None,
                          description: str | None = None) -> None:
    """
    Write a multi-section commented header followed by the CSV body.
    sections: {"soil_moisture": {...}, "snow_water_equivalent": {...}, ...}
              Each inner dict maps key -> list[str].
    description: Optional free-text line written at the very top of the header.
    """
    float_format = None
    if digits_after_decimal is not None:
        float_format = f"%.{digits_after_decimal}f"

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        fh.write(f"# Values are in units of {options.volume_description}.\n")
        mean_area = getattr(options, "mean_area", None)
        if mean_area is not None:
            fh.write(f"# Average area of the {options.args.basin} basin using these datasets: {options.format_area(mean_area)} {options.area_units_text}\n")
            fh.write(f"# Multiply these values by {ra.volume_to_thickness_factor(options, mean_area):.4f}"
                     f" to convert from {options.volume_description} to {options.thickness_description}.\n")
        if description:
            fh.write(f"# {description}\n#\n")
        if sections:
            # Emit sections in a stable, readable order if present
            order = ["soil_moisture", "snow_water_equivalent", "reservoirs", "grace"]
            for section in order:
                fh.write(f"# === {section} ===\n")
                attrs = sections.get(section, {}) if isinstance(sections, dict) else {}
                for k, vlist in attrs.items():
                    fh.write(f"# {k}: {json.dumps(list(vlist), ensure_ascii=False)}\n")
                fh.write("#\n")
        df.to_csv(fh, index_label=index_label, float_format=float_format)


def _append_suffix_before_ext(path: os.PathLike[str] | str, suffix: str) -> Path:
    """
    Append a suffix before the file extension in a given path.
    
    Args:
        path:   The original file path.
        suffix: The suffix to append before the file extension.
    
    Returns:
        A Path object with the modified file name.
    """
    p = Path(path)
    return p.with_name(f"{p.stem}{suffix}{p.suffix}")


def remove_mean(series:         pd.Series,
                baseline_start: pd.Timestamp | dt.datetime | str,
                baseline_end:   pd.Timestamp | dt.datetime | str) -> pd.Series:
    """
    Subtracts the mean of "series" over [start_time, end_time] from the entire series.

    Args:
        series:         Time-indexed data.
        baseline_start: Start of the window over which to compute the mean.
        baseline_end:   End   of the window over which to compute the mean.

    Returns:
        The demeaned series.

    Raises:
        None.
    """
    # ensure pandas timestamps
    start = pd.to_datetime(baseline_start)
    end   = pd.to_datetime(baseline_end)

    # extract the window, compute its mean
    window = series.loc[start:end]
    if window.empty:
        raise ValueError(f"Baseline window {start.date()} to {end.date()} contains no data for '{series.name}'.")

    μ = window.mean()
    logging.info(f"Removing mean {μ} from '{series.name}' over {baseline_start} to {baseline_end}")

    # subtract and return
    return series - μ


def compute_groundwater(options:    Options,
                        grace:      pd.DataFrame,
                        swe:        pd.DataFrame,
                        soilm:      pd.DataFrame,
                        reservoirs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Aligns the four series on their shared dates, removes their respective
    long-term means over [start_time, end_time], subtracts snow water equivalent (SWE),
    soil moisture, and reservoirs mass from GRACE total water storage (TWS),
    and propagates the uncertainties assuming independence:

        sigma_sw = sqrt(sigma_grace^2 + sigma_swe^2 + sigma_soilm^2 + sigma_reservoirs^2)

    Args:
        options:    Global options including baseline start and end dates. Contains:
            - baseline_start: Requested start date for baseline mean removal (YYYY-MM-DD).
            - baseline_end:   Requested end   date for baseline mean removal (YYYY-MM-DD).
        grace:      DataFrame with GRACE TWS data, columns ["value","error"]
        swe:        DataFrame with snow water equivalent data, columns ["value","error"]
        soilm:      DataFrame with soil moisture data, columns ["value","error"]
        reservoirs: DataFrame with reservoirs data, columns ["value","error"]

    Returns:
        A tuple of three DataFrames:
            - groundwater  DataFrame with columns ["groundwater", "error"]
            - grace        DataFrame with columns ["grace",       "err_grace"]
            - full aligned DataFrame with all component columns and error columns

    Raises:
        None.
    """

    # Combine into one DataFrame (with errors untouched)
    df = pd.DataFrame({
        "grace":          grace[     'value'],
        "swe":            swe[       'value'],
        "soilm":          soilm[     'value'],
        "reservoirs":     reservoirs['value'],
        "err_grace":      grace[     'error'],
        "err_swe":        swe[       'error'],
        "err_soilm":      soilm[     'error'],
        "err_reservoirs": reservoirs['error'],
    })

    if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug(f"DataFrame overview before dropping dates with missing data:\n{df.describe()}")

    logging.info("Dropping any dates with missing data...")
    df = df.dropna()

    if df.empty:
        raise ValueError("No overlapping dates across all inputs after alignment (post-dropna). Check input coverage and masking.")

    if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug(f"DataFrame overview after dropping missing dates:\n{df.describe()}")

    # Now that df has had missing dates dropped, extract start and end times
    data_start = df.index.min()
    data_end   = df.index.max()
    logging.info(f"\nData start: {data_start.date()}\nData end: {data_end.date()}")
    # Compute the actual baseline interval.
    # Start by trying to find the intersection of [data_start, data_end] and [options.baseline_start, options.baseline_end]
    # If they don't overlap, create a baseline starting at data_start with the same duration as the requested baseline (if possible).
    options.actual_baseline_start, options.actual_baseline_end = ra.compute_baseline(data_start, data_end, options.baseline_start, options.baseline_end)
    logging.info(f"Using baseline interval {options.actual_baseline_start.date()} to {options.actual_baseline_end.date()} for mean removal.")

    logging.info("Removing long-term means from each series after dropping missing dates.")
    for col in ["grace", "swe", "soilm", "reservoirs"]:
        df[col] = remove_mean(df[col], options.actual_baseline_start, options.actual_baseline_end)
    logging.info(f"All series have been demeaned after dropping missing dates:\n{df.describe()}")

    # Compute groundwater anomaly and propagated error
    df["groundwater"] = (df["grace"] - (df["swe"] + df["soilm"] + df["reservoirs"]))
    df["error"]       = np.sqrt(df["err_grace"]**2 + df["err_swe"]**2 + df["err_soilm"]**2 + df["err_reservoirs"]**2)

    return df[["groundwater", "error"]], df[["grace", "err_grace"]], df


if __name__ == "__main__":
    main()
