import argparse
from pathlib import Path
from osgeo import gdal
import numpy as np
import os
import glob
import pandas as pd
from datetime import datetime
import re
from pyproj import Geod
import numpy as np
import logging

from ellipsoidal_area import area
from area_weighted import area_weighted_stats

import run_all as ra

# Written by Munish Sikka and ChatGPT


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                 str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_err_coeff:     float = 0.20  # Default error coefficient (20%)
        self.default_input_dir:      Path = self.swe_dir / "monthly_data"
        self.default_mask_dir:      Path = self.swe_dir / "masks" / "basin_masks"
        self.default_regions:        list = [self.default_basin_safename]
        self.default_output_regions: list = [f"{self.default_basin_safename}_mask"]


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description=f"Process {options.swe_model} SWE data by region and date thresholds.")

    parser.add_argument("--input_dir", default=options.default_input_dir,
                        help="Directory containing monthly SWE .tif files")
    parser.add_argument("--err_coeff", type=float, default=options.default_err_coeff,
                        help=f"Fraction of weighted sum used as error (e.g., {options.default_err_coeff} for {options.default_err_coeff * 100}%)")
    parser.add_argument("--output_dir", default=options.timeseries_dir,
                        help=f"Directory for output results (default: {os.fspath(options.timeseries_dir)})")
    parser.add_argument("--mask_dir", default=options.default_mask_dir,
                        help=f"Directory for base mask generated using our scripts (default: {os.fspath(options.default_mask_dir)})")
    parser.add_argument("--regions", default=options.default_regions, nargs="+",
                        help=f"List of region codes (default: {options.default_regions})")
    parser.add_argument("--output_regions", default=options.default_output_regions, nargs="+",
                        help=f"List of output mask names (default: {options.default_output_regions})")
    parser.add_argument("--start_date", default=options.test_start,
                        help=f"Start date for alternate period (YYYY-MM-DD, default: {options.test_start})")
    parser.add_argument("--end_date", default=options.test_end,
                        help=f"End date for alternate period (YYYY-MM-DD, default: {options.test_end})")
    parser.add_argument("--full", action="store_true",
                        help=f"If set, calculate the full timespan ({options.full_start} - {options.full_end})")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    if options.args.full:
        options.args.start_date = options.full_start
        options.args.end_date   = options.full_end
    # Format dates as YYYY-MM-DD regardless of their original format by parsing and reformatting.
    options.args.start_date = (ra.parse_datetime(options.args.start_date)).strftime("%Y-%m-%d")
    options.args.end_date   = (ra.parse_datetime(options.args.end_date  )).strftime("%Y-%m-%d")


def main() -> None:
    """Main function to calculate monthly anomaly timeseries from snow water equivalent (SWE) data."""
    gdal.UseExceptions()  # Enable GDAL exceptions for error handling
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    if options.swe_model == "SNODAS":
        monthly_anomalies_for_SNODAS(options)
    else:
        raise ValueError(f"Unsupported snow water equivalent (SWE) model: {options.swe_model}")


def monthly_anomalies_for_SNODAS(options: Options) -> None:
    """
    Calculate monthly anomaly timeseries from SNODAS SWE data using region masks.

    Args:
        options: An Options instance with parsed command line arguments in options.args. Contains:
           - input_dir:      Directory with SWE .tif files.
           - err_coeff:      Coefficient for error calculation.
           - output_dir:     Directory to save output CSVs.
           - mask_dir:      Directory for set of masks.
           - regions:        List of region names.
           - output_regions: List of output region names for filenames.
           
    Returns:
        None. Saves output CSV files.
    
    Raises:
        None.
    """
    input_dir      = options.args.input_dir
    err_coeff      = options.args.err_coeff
    output_dir     = options.args.output_dir
    mask_dir      = options.args.mask_dir
    regions        = options.args.regions
    output_regions = options.args.output_regions

    # Change directory if desired
    os.chdir(input_dir)

    # Collect SWE files
    swe_files = sorted(glob.glob(os.path.join(input_dir, '*.tif')))
    logging.info(f"Found {len(swe_files)} SWE files")

    # Load masks
    region_masks = load_region_masks(options, regions, mask_dir)

    # Print summary (for now - replace with your actual processing code)
    logging.info(f"err_coeff: {err_coeff}")
    logging.info(f"Output directory: {output_dir}")
    logging.info(f"Mask directory: {mask_dir}")
    logging.info(f"Regions: {regions}")
    logging.info(f"Output region names: {output_regions}")

    # processing
    sample_filename = swe_files[0]
    # Compute latitude array using any sample file
    ds_sample = gdal.Open(sample_filename)
    gt = ds_sample.GetGeoTransform()
    origin_y = gt[3]
    pixel_height = gt[5]
    nrows = ds_sample.RasterYSize
    latitudes = origin_y + np.arange(nrows) * pixel_height
    res = np.round(gt[1], 5)  # longitude resolution
    dx = res/2
    max_lat = np.round(np.max(latitudes), 3)
    # --- Define latitude centers (from north to south) ---
    lat_centers = max_lat - np.arange(nrows) * res  # North to south
    # --- Get area per row ---
    area_per_row = area(lat_centers, dx)  # shape: (3351,)
    # --- Repeat for all columns (6935) ---
    ncols = ds_sample.RasterXSize
    area_grid = np.tile(area_per_row[:, np.newaxis], (1, ncols))  # shape: (3351, 6935)

    # Compute means
    compute_means(options, swe_files, region_masks, regions, output_regions, output_dir, err_coeff, area_grid)


def load_region_masks(options: Options, regions: list, mask_dir: str,
                                   template: str = '{swe_model}_{region}_mask.csv') -> dict:
    """
    Load region masks from separate directories for mask1 and mask2.

    Args:
        options:   Options instance containing 'swe_model' for use in the templates.
        regions:   List of region names (e.g., ['region1', 'region2'])
        mask_dir: Directory where mask CSVs are stored
        template: File name template for mask (default: '{swe_model}_{region}_mask.csv')
        
    Returns:
        Dictionary with keys like (region_index, 'mask1') -> numpy array

    Raises:
        FileNotFoundError: If any mask file is not found.
    """
    masks = {}
    for i, region in enumerate(regions):
        mask_path = os.path.join(mask_dir, template.format(swe_model=options.swe_model, region=region))
        # Read and convert to boolean arrays
        masks[i]  = pd.read_csv(mask_path, header=None, comment="#", skip_blank_lines=True).values.astype(bool)
    return masks


def compute_means(options: Options, file_list: list, region_masks: dict,
                                   region_names: list, output_regions: list,
                                   output_dir: str, err_coeff: float,
                                   area_weights: np.ndarray) -> None:
    """
    Compute area-weighted means for each region, switching masks based on date range.

    Args:
        options:        Options instance containing command line arguments.
        file_list:      List of SWE .tif file paths.
        region_masks:   Dictionary of region masks loaded from CSVs.
        region_names:   List of region names.
        output_regions: List of output region names for filenames.
        output_dir:     Directory to save output CSVs.
        err_coeff:      Coefficient to compute error as fraction of weighted sum.
        area_weights:   2D numpy array of area weights (same shape as SWE data).
    
    Returns:
        None. Saves CSV files for each region with monthly anomaly timeseries.
    
    Raises:
        None.
    """
    all_results = [[] for _ in range(len(region_names))]
    all_dates = []

    for i, file in enumerate(file_list):
        ds = gdal.Open(file)
        swe = ds.ReadAsArray().astype(np.float32)
        ds = None

        mid_date = extract_date_from_filename(os.path.basename(file))
        all_dates.append(mid_date.strftime("%Y-%m"))

        logging.info(f"{mid_date.strftime('%Y-%m')}")

        for j in range(len(region_names)):
            mask = region_masks[j]
            weighted_mean, weighted_sum, total_weight = area_weighted_stats(swe, area_weights, mask)
            # weighted_sum = np.nan_to_num(weighted_sum, nan=np.nan)  # ensure numeric
            # weighted_sum = float(weighted_sum)  # make scalar, not array
            # mean_val = area_weighted_stats(swe, area_weights, mask)
            error_val = float(err_coeff) * weighted_sum if not np.isnan(weighted_sum) else np.nan
            all_results[j].append((weighted_sum, error_val))

    # Save CSV files per region
    for i, region_data in enumerate(all_results):
        df = pd.DataFrame(region_data, columns=["swe", "swe_error"])
        df.insert(0, "date", all_dates)
        safe_name = output_regions[i].replace(" ", "_")
        os.makedirs(output_dir, exist_ok=True)
        df['swe'] /= 1e9  # swe multiplied by area in m3 to km3
        df['swe_error'] /= 1e9
        # compute anomaly
        # Filter the period from Jan 2004 to Dec 2009
        swe_values = df['swe']
        df['YearMonth'] = pd.to_datetime(df['date']).dt.to_period('M')
        df = df.sort_values('date')
        # Convert baseline periods to datetime.date
        base_start = pd.Period(options.baseline_start, freq='M').to_timestamp().date()
        base_end   = (pd.Period(options.baseline_end, freq='M') + 1).to_timestamp().date() - pd.Timedelta(days=1)
        first_period = df['YearMonth'].iloc[0]
        last_period  = df['YearMonth'].iloc[-1]
        # Convert actual periods to datetime.date
        actual_start = first_period.to_timestamp().date()
        actual_end   = (last_period + 1).to_timestamp().date() - pd.Timedelta(days=1)
        result_start, result_end = ra.compute_baseline(actual_start, actual_end,base_start, base_end) 
        logging.info(f"baseline: {result_start} to {result_end}")
        #Convert adaptive baseline dates back to Period for filtering
        result_start_period = pd.Period(result_start.strftime("%Y-%m"), freq='M')
        result_end_period   = pd.Period(result_end.strftime("%Y-%m"), freq='M')
        time_mask = (df['YearMonth'] >= result_start_period) & (df['YearMonth'] <= result_end_period)
        baseline_mean = df.loc[time_mask, 'swe'].mean()
        df['swe']       = df['swe'] - baseline_mean
        # baseline mean subtracted now save the csv file along with metadata   
        csv_file        = output_dir / f"anomaly_timeseries_{options.swe_model}_{safe_name}.csv"
        df = df.drop(columns=['YearMonth'],errors="ignore")
        header_lines = options.swe_url_prefix
        if isinstance(header_lines, str):
            header_lines = [header_lines]
        total_area = float(np.sum(area_weights[region_masks[i]])) * options.area_m2_scale
        with open(csv_file, "w", encoding="utf-8") as f:
            for line in header_lines:
                # Automatically prefix with "# " if not already
                if not line.startswith("#"):
                    f.write(f"# {line}\n")
                else:
                    f.write(line + "\n")
            f.write(f"# total_area_SWE: {options.format_area(total_area)}\n")
            f.write(f"# total_area_units: {options.area_units_text}\n")
        # Optional blank line for readability
            f.write("#\n")
        # --- Step 2: Append the dataframe ---
        df.to_csv(csv_file, mode="a", index=False)
        #df.drop(columns=['YearMonth']).to_csv(csv_file, index=False)


def extract_date_from_filename(filename: str) -> datetime:
    """
    Extract date from filenames like snowdas_yyyymm_.tif

    Args:
        filename: Filename string.
    
    Returns:
        datetime: Extracted date (15th of month).
    
    Raises:
        ValueError: If date cannot be parsed from filename.
    """
    match = re.search(r'(\d{6})', filename)
    if not match:
        raise ValueError(f"Could not parse date from {filename}")

    yyyymm = match.group(1)
    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])

    return datetime(year, month, 15)  # Mid-month


if __name__ == "__main__":
    main()

'''
This script reads SWE monthly grid data from geotif and csv masks (reg and repaired repaired (for 2014-2019)) 
and generates monthly timeseries for swe anomaly and error values as percentage of monthly mean before computing anomaly.
'''
