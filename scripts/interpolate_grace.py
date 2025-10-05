import pandas as pd
import numpy as np
import argparse
import os
from pathlib import Path
import logging

import run_all as ra

#Written by Munish Sikka and ChatGPT


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                 str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_input_file:     Path = self.grace_dir / "monthly_grace_anomaly" / f"anomaly_timeseries_GRACE_{self.default_basin_safename}_mask.csv"
        self.default_output_filename: str = f"anomaly_timeseries_GRACE_{self.default_basin_safename}_mask.csv"


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Interpolate GRACE data on 15th-of-month")
    parser.add_argument("--input_file", default=options.default_input_file,
                        help=f"Path to input CSV with date, tws, tws_error (default: {os.fspath(options.default_input_file)})")
    parser.add_argument("--output_dir", default=options.timeseries_dir,
                        help=f"Output directory (default: {os.fspath(options.timeseries_dir)})")
    parser.add_argument("--output_file", default=options.default_output_filename,
                        help=f"Output filename (default: {options.default_output_filename})")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    parser.add_argument("--full", action="store_true",
                        help=argparse.SUPPRESS)
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG


def main() -> None:
    """Main function to interpolate GRACE data."""
    options = Options()
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')
    parse_arguments(options)

    df = pd.read_csv(options.args.input_file, parse_dates=["date"], comment="#", skip_blank_lines=True).set_index("date").sort_index()

    # Load CSV
    df = pd.read_csv(options.args.input_file, parse_dates=["date"], comment="#", skip_blank_lines=True).set_index("date").sort_index()

    # Run interpolation
    columns = ["tws", "tws_error"]
    df_result = interpolate_and_filter(df, columns)

    # Save to CSV with formatted dates
    df_result = df_result.reset_index()
    df_result["date"] = df_result["date"].dt.strftime("%m/%d/%Y")

    os.makedirs(options.args.output_dir, exist_ok=True)
    outpath = os.path.join(options.args.output_dir, options.args.output_file)
    df_result.to_csv(outpath, index=False)
    logging.info(f"Saved to {outpath}")


def generate_15th_dates(df: pd.DataFrame) -> pd.DatetimeIndex:
    """
    Generate all 15th-of-month dates between min and max of df index.

    Args:
        df: DataFrame with datetime index.
    
    Returns:
        DatetimeIndex of all 15th-of-month dates in the range of df's index.

    Raises:
        None.
    """
    start = df.index.min().replace(day=1)
    end = df.index.max().replace(day=1)
    month_starts = pd.date_range(start=start, end=end, freq='MS')
    return month_starts + pd.Timedelta(days=14)


def interpolate_and_filter(df: pd.DataFrame, columns: list, max_gap_days: int = 10000) -> pd.DataFrame:
    """
    Interpolate specified columns to 15th of each month, filtering out months without any data.

    Args:
        df:           DataFrame with datetime index and columns to interpolate.
        columns:       List of column names to interpolate.
        max_gap_days: Maximum gap in days to allow interpolation (default 10000, effectively no limit).

    Returns:
        DataFrame with interpolated values on 15th of each month, filtered to only include months with at least one known value.
    
    Raises:
        None.
    """
    # Ensure datetime index
    df = df.copy()
    df.index = pd.to_datetime(df.index)

    # Interpolation target: all 15ths of months in data range
    fifteenth_dates = generate_15th_dates(df)

    # Union index: original + 15ths
    df_interp = df.reindex(df.index.union(fifteenth_dates)).sort_index()
    
    # Interpolate time-based
    for col in columns:
        df_interp[col] = df_interp[col].interpolate(method='time')

    # Get only interpolated values on the 15th
    fifteenths_only = df_interp.loc[df_interp.index.isin(fifteenth_dates)].copy()

    # Filter: keep only months that had at least one known value in original data
    results = {}
    for col in columns:
        valid_months = set(zip(df.index.year[df[col].notna()], df.index.month[df[col].notna()]))
        fifteenths_only_col = fifteenths_only[[col]].copy()
        fifteenths_only_col["year_month"] = list(zip(fifteenths_only_col.index.year, fifteenths_only_col.index.month))
        fifteenths_only_col = fifteenths_only_col[fifteenths_only_col["year_month"].isin(valid_months)]
        fifteenths_only_col.drop(columns=["year_month"], inplace=True)
        results[col] = fifteenths_only_col

    # Combine outputs: only keep dates common to all valid columns
    common_dates = set.intersection(*(set(df_.index) for df_ in results.values()))
    final = pd.DataFrame(index=sorted(common_dates))
    for col in columns:
        final[col] = results[col].loc[final.index, col]

    final.index.name = "date"
    return final


if __name__ == "__main__":
    main()


#Example usage : python interpolate_grace.py <input anomaly data> <output dir> <output interpolated csv filename>

