import argparse
import os
import pandas as pd
from pathlib import Path
import logging

import run_all as ra

#Written by Munish Sikka and ChatGPT
'''
For each input CSV (like a_monthly_km3.csv, b_monthly_km3.csv, etc.):

1. Reads the CSV (must have a 'date' column and one magnitude column).
2. Computes:
   - `error` = |magnitude| * err_val (as a fraction, e.g., 0.05 = 5%)
   - `anomaly` = magnitude - mean(magnitude) over the baseline period.
3. Saves the result as: anomaly_timeseries_cdec_{region}.csv
'''


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:            Path = Path(__file__).stem  # The name of this script without the .py extension
        self.default_cdec_dir:   Path = self.project_root / "input_data" / "reservoirs" / "CDEC"
        self.default_csv_files:  list[Path] = [self.default_cdec_dir / "monthly_sums" / f"{self.default_basin}_monthly_km3.csv"]
        self.default_output_dir: Path = self.default_cdec_dir / "monthly_anomaly"
        self.default_baseline_start: str = "2005-01-01" #"2004-01-01"
        self.default_baseline_end: str = "2005-03-31" #"2009-12-31"
        self.default_err_val: float = 0.05  # Default error coefficient (5%)

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Compute anomalies and error values for CDEC regional CSVs.")
    parser.add_argument("--csv_files", default=options.default_csv_files, nargs="+",
                        help="List of CSV files (e.g., a_monthly_km3.csv b_monthly_km3.csv)")
    parser.add_argument("--output_dir", default=options.default_output_dir,
                        help="Directory to save anomaly CSVs")
    parser.add_argument("--start_date", default=options.default_baseline_start,
                        help=f"Baseline start date ({options.default_baseline_start})")
    parser.add_argument("--end_date", default=options.default_baseline_end,
                        help=f"Baseline end date ({options.default_baseline_end})")
    parser.add_argument("--err_val", type=float, default=options.default_err_val,
                        help=f"Error coefficient (e.g., {options.default_err_val} for {options.default_err_val * 100}%)")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = "DEBUG"


def main() -> None:
    """Main function to compute reservoirs regional anomaly and error value time series."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    if options.reservoirs_model == "CDEC":
        calculate_anomaly_and_errors_for_CDEC(options)
    else:
        raise ValueError(f"Unsupported reservoirs model: {options.reservoirs_model}")


def calculate_anomaly_and_errors_for_CDEC(options: Options) -> None:
    """
    Compute anomalies and error values for CDEC regional CSV files.
    
    Args:
        options: An Options instance with parsed command line arguments in options.args. Contains:
           - csv_files:   List of CSV files (e.g., a_monthly_km3.csv b_monthly_km3.csv).
           - output_dir:  Directory to save anomaly CSVs.
           - start_date:  Baseline start date (YYYY-MM-DD).
           - end_date:    Baseline end date (YYYY-MM-DD).
           - err_val:     Error coefficient (e.g., 0.05 for 5%).
    
    Returns:
        None. Saves anomaly CSVs to output_dir.

    Raises:
        None.
    """
    for csv_file in options.args.csv_files:
        process_csv(csv_file, options.args.output_dir, options.args.start_date, options.args.end_date, options.args.err_val)


def process_csv(file_path: str, output_dir: str, start_date: str, end_date: str, err_val: float) -> None:
    """
    Reads a region CSV, computes error, baseline mean, and anomaly, 
    then saves the output as a new CSV.

    Args:
        file_path:   Path to the input CSV file.
        output_dir:  Directory to save the output CSV.
        start_date:  Baseline start date (YYYY-MM-DD).
        end_date:    Baseline end date (YYYY-MM-DD).
        err_val:     Error coefficient (e.g., 0.05 for 5%).
    
    Returns:
        None. Saves output CSV to output_dir.
    
    Raises:
        ValueError: If the input CSV does not have the expected format.
    """
    region_name = os.path.splitext(os.path.basename(file_path))[0].replace('_monthly_km3', '')

    # Load the CSV
    df = pd.read_csv(file_path)
    if 'date' not in df.columns:
        raise ValueError(f"CSV {file_path} must have a 'date' column")
    
    df['date'] = pd.to_datetime(df['date'])

    # Assume the magnitude column is the only one besides 'date'
    value_cols = [col for col in df.columns if col != 'date']
    if len(value_cols) != 1:
        raise ValueError(f"CSV {file_path} must have exactly one value column besides 'date'. Found: {value_cols}")
    value_col = value_cols[0]

    # Compute error values
    df['error'] = df[value_col].abs() * err_val  # magnitude * percentage

    # Compute baseline mean for given period
    baseline_mask = (df['date'] >= pd.to_datetime(start_date)) & (df['date'] <= pd.to_datetime(end_date))
    baseline_mean = df.loc[baseline_mask, value_col].mean()

    # Compute anomaly (subtract baseline mean)
    df['anomaly'] = df[value_col] - baseline_mean

    # Save output CSV
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"anomaly_timeseries_cdec_{region_name}_mask.csv")
    df[['date','anomaly', 'error']].to_csv(output_file, index=False)

    logging.info(f"Saved anomaly CSV for {region_name} → {output_file}")


if __name__ == "__main__":
    main()

'''
Example usage
python cdec_regional_anomaly_mean_err_vals.py --csv_files "C:\output\a_monthly_km3.csv" "C:\output\b_monthly_km3.csv" --output_dir "C:\output\anomalies" --start_date 2004-01-01 --end_date 2009-12-31 --err_val 0.05
  
will create in output dir
    anomaly_timeseries_cdec_a_mask.csv
    anomaly_timeseries_cdec_b_mask.csv  
'''
