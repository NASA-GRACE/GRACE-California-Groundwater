#!/usr/bin/env python3
"""
Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), and GitHub Copilot (it/its).


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

    if options.args.grace == options.default_grace_csv:  # If user-specified input GRACE file is the default placeholder
        options.args.grace = (options.timeseries_dir / f"anomaly_timeseries_GRACE_{basin_title}_mask.csv").resolve()
        logging.info(f"Using GRACE data from {options.args.grace}")
    if options.args.swe == options.default_swe_csv:  # If user-specified input SWE file is the default placeholder
        options.args.swe = (options.timeseries_dir / f"anomaly_timeseries_{options.swe_model}_{basin_title}_mask.csv").resolve()
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
            options.args.soilm = max(soil_moisture_files, key=os.path.getctime)
            logging.info(f"Using {options.soil_moisture_model} data from {options.args.soilm}")
        else:
            raise FileNotFoundError(f"No {options.soil_moisture_model} files found for {options.args.basin}.")
    if options.args.output == options.default_output_csv:
        # Create a timestamp for the output filename
        timestamp = ra.parse_datetime("NOW", timezone="America/Los_Angeles").strftime("%Y%m%d-%H%M%S")
        options.args.output = options.output_dir / f"anomaly_timeseries_groundwater_{basin_title}_DATA_START_to_DATA_END_monthly_unsmoothed_created_on_{timestamp}.csv"
    else:
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

    # Compute groundwater and error
    sw = compute_groundwater(options, grace, swe, soil_moisture, reservoirs)
    logging.info(f"Computed groundwater series with {len(sw)} entries.")

    # Include the actual baseline period used for mean removal in each output header
    baseline_start_str = options.actual_baseline_start.strftime("%Y-%m-%d")
    baseline_end_str   = options.actual_baseline_end.strftime("%Y-%m-%d")
    for _sec in header_sections:
        header_sections[_sec]["mean_removal_baseline_start"] = [baseline_start_str]
        header_sections[_sec]["mean_removal_baseline_end"]   = [baseline_end_str]

    if "DATA_START_to_DATA_END" in options.args.output.name:
        # Replace placeholders in each output filename with actual start and end dates of the combined time series:
        data_start_monthly = sw.index.min().strftime("%Y-%m")
        data_end_monthly   = sw.index.max().strftime("%Y-%m")
        data_start_yearly  = sw.index.min().strftime("%Y")
        data_end_yearly    = sw.index.max().strftime("%Y")

    # Save results
    monthly_unsmoothed_output_path = options.args.output
    if "DATA_START_to_DATA_END" in monthly_unsmoothed_output_path.name:
        monthly_unsmoothed_output_path = monthly_unsmoothed_output_path.with_name(monthly_unsmoothed_output_path.name.replace("DATA_START", data_start_monthly).replace("DATA_END", data_end_monthly))
    _write_df_with_header(sw, monthly_unsmoothed_output_path, index_label="date", sections=header_sections)
    logging.info(f"Groundwater series (monthly, unsmoothed) written to {monthly_unsmoothed_output_path}")

    # Smooth the time series
    window_size = 3  # centered moving average of 3 months
    logging.info(f"Smoothing the groundwater series with a centered moving average of {window_size} months.")
    sw_smoothed = smooth_timeseries(sw, window=window_size)
    smoothed_output_path = options.args.output.with_name(options.args.output.name.replace("monthly_unsmoothed", f"monthly_smoothed_{window_size}mo"))
    if "DATA_START_to_DATA_END" in smoothed_output_path.name:
        smoothed_output_path = smoothed_output_path.with_name(smoothed_output_path.name.replace("DATA_START", data_start_monthly).replace("DATA_END", data_end_monthly))
    _write_df_with_header(sw_smoothed, smoothed_output_path, index_label="date", sections=header_sections)
    logging.info(f"Groundwater series (monthly, smoothed) written to {smoothed_output_path}")

    # Compute calendar-year averages
    logging.info("Computing calendar-year averages of the groundwater series.")
    sw_cal_yr = average_timeseries(sw, year_type="calendar")
    cal_yr_output_path = options.args.output.with_name(options.args.output.name.replace("monthly_unsmoothed", "calendar_year_averages"))
    if "DATA_START_to_DATA_END" in cal_yr_output_path.name:
        cal_yr_output_path = cal_yr_output_path.with_name(cal_yr_output_path.name.replace("DATA_START", data_start_yearly).replace("DATA_END", data_end_yearly))
    _write_df_with_header(sw_cal_yr, cal_yr_output_path, index_label="date", sections=header_sections)
    logging.info(f"Groundwater series (calendar-year averages) written to {cal_yr_output_path}")

    # Compute water-year averages
    logging.info("Computing water-year averages of the groundwater series.")
    sw_wat_yr = average_timeseries(sw, year_type="water")
    wat_yr_output_path = options.args.output.with_name(options.args.output.name.replace("monthly_unsmoothed", "water_year_averages"))
    if "DATA_START_to_DATA_END" in wat_yr_output_path.name:
        wat_yr_output_path = wat_yr_output_path.with_name(wat_yr_output_path.name.replace("DATA_START", data_start_yearly).replace("DATA_END", data_end_yearly))
    _write_df_with_header(sw_wat_yr, wat_yr_output_path, index_label="date", sections=header_sections)
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
                header[m.group(1)] = [text]
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


def _write_df_with_header(df: pd.DataFrame, out_path: os.PathLike[str] | str,
                          index_label: str = "date",
                          sections: dict[str, dict[str, list[str]]] | None = None) -> None:
    """
    Write a multi-section commented header followed by the CSV body.
    sections: {"soil_moisture": {...}, "snow_water_equivalent": {...}, ...}
              Each inner dict maps key -> list[str].
    """
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        if sections:
            # Emit sections in a stable, readable order if present
            order = ["soil_moisture", "snow_water_equivalent", "reservoirs", "grace"]
            for section in order:
                fh.write(f"# === {section} ===\n")
                attrs = sections.get(section, {}) if isinstance(sections, dict) else {}
                for k, vlist in attrs.items():
                    fh.write(f"# {k}: {json.dumps(list(vlist), ensure_ascii=False)}\n")
                fh.write("#\n")
        df.to_csv(fh, index_label=index_label)


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
    μ = window.mean()
    logging.info(f"Removing mean {μ} from '{series.name}' over {baseline_start} to {baseline_end}")

    # subtract and return
    return series - μ


def compute_groundwater(options:    Options,
                        grace:      pd.DataFrame,
                        swe:        pd.DataFrame,
                        soilm:      pd.DataFrame,
                        reservoirs: pd.DataFrame) -> pd.DataFrame:
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
        DataFrame with columns ["groundwater","error"].

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
    df["error"] = np.sqrt(df["err_grace"]**2 + df["err_swe"]**2 + df["err_soilm"]**2 + df["err_reservoirs"]**2)

    return df[["groundwater", "error"]]


def smooth_timeseries(sw: pd.DataFrame, window: int = 3) -> pd.DataFrame:
    """
    Smooths the groundwater series (and its propagated error) with a centered
    moving average of length "window" (in months).

    Args:
    sw:     DataFrame with columns ["groundwater", "error"] indexed by date.
    window: Size of the moving window (default is 3).

    Returns:
        A new DataFrame "sw_smoothed" with the same structure as "sw",
        where both "groundwater" and "error" have been smoothed.

    Raises:
        None.
    """
    # make a copy so we don't overwrite the original
    sw_smoothed = sw.copy()
    # apply centered rolling mean; use min_periods=1 so edges are handled gracefully
    sw_smoothed['groundwater'] = (sw['groundwater'].rolling(window=window, center=True, min_periods=1).mean())
    sw_smoothed['error']       = (sw['error'      ].rolling(window=window, center=True, min_periods=1).mean())
    return sw_smoothed


def average_timeseries(sw: pd.DataFrame, year_type: str = "calendar") -> pd.DataFrame:
    """
    Aggregate a monthly groundwater series into yearly averages.

    Args:
    ----------
    sw:     DataFrame with columns ["groundwater","error"] indexed by month (date).
    year_type: Type of year to use for averaging:
        - "calendar": Jan 1–Dec 31
        - "water"   : Oct 1–Sep 30 (water year).
        Default is "calendar".

    Returns:
        Yearly-averaged DataFrame with index = year (as Timestamp at Dec 31 for
        calendar years, or Sep 30 for water years), and columns ["groundwater","error"].

    Raises:
        ValueError: If year_type is not "calendar" or "water".
    """
    if year_type not in ("calendar", "water"):
        raise ValueError(f"year_type must be 'calendar' or 'water', got '{year_type}'")

    if year_type == "calendar":
        # Resample by calendar year and take the mean
        # "A-DEC" means year-end frequency on Dec 31
        yearly = sw.resample("YE-DEC").mean()
        # shift the Dec 31 index back by 6 months → mid‐year
        yearly.index = yearly.index - pd.DateOffset(months=6)
        yearly.index.name = "date"
        return yearly

    # water year: Oct 1–Sep 30
    # assign each month to its water year label
    df = sw.copy()
    # For months Oct–Dec, water_year = year + 1; else = year
    water_year = df.index.to_series().apply(lambda d: d.year + 1 if d.month >= 10 else d.year)
    df['water_year'] = water_year

    # group by water_year and average
    yearly = (df.groupby('water_year')[['groundwater', 'error']].mean())

    # move Sep 30 back by 6 months → center of Oct 1–Sep 30
    yearly.index = pd.to_datetime(yearly.index.astype(str) + "-09-30") \
                   - pd.DateOffset(months=6)
    yearly.index.name = "date"

    return yearly


if __name__ == "__main__":
    main()
