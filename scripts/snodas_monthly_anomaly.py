import argparse
from pathlib import Path
from osgeo import gdal
import numpy as np
import os
import glob
import pandas as pd
from datetime import datetime, timedelta
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
        self.my_name: Path = Path(__file__).stem  # The name of this script without the .py extension
        self.default_err_coeff: float = 0.1  # Default error coefficient (10%)


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Process SNODAS SWE data by region and date thresholds.")

    parser.add_argument("--input_dir", required=True, help="Directory containing SWE .tif files")
    parser.add_argument("--err_coeff", type=float, default=options.default_err_coeff,
                        help=f"Fraction of weighted sum used as error (e.g., {options.default_err_coeff} for {options.default_err_coeff * 100}%)")
    #parser.add_argument("--err_coeff", required=True, help="fraction of value to be used as errors")
    parser.add_argument("--output_dir", required=True,
                        help="Directory for output results")
    parser.add_argument("--mask1_dir", required=True,
                        help="Directory for first mask set")
    parser.add_argument("--mask2_dir", required=True,
                        help="Directory for second mask set")
    parser.add_argument("--regions", nargs="+", required=True,
                        help="List of region codes (e.g., a b v d)")
    parser.add_argument("--output_regions", nargs="+", required=True,
                        help="List of output mask names")
    parser.add_argument("--start_date", required=True,
                        help="Start date for alternate period (YYYY-MM-DD)")
    parser.add_argument("--end_date", required=True,
                        help="End date for alternate period (YYYY-MM-DD)")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = "DEBUG"


def main() -> None:
    """Main function to calculate monthly anomaly timeseries from snow water equivalent (SWE) data."""
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
           - mask1_dir:      Directory for first set of masks.
           - mask2_dir:      Directory for second set of masks.
           - regions:        List of region names.
           - output_regions: List of output region names for filenames.
           - start_alt:      Start date for alternate mask period.
           - end_alt:        End date for alternate mask period.

    Returns:
        None. Saves output CSV files.
    
    Raises:
        None.
    """
    input_dir      = options.args.input_dir
    err_coeff      = options.args.err_coeff
    output_dir     = options.args.output_dir
    mask1_dir      = options.args.mask1_dir
    mask2_dir      = options.args.mask2_dir
    regions        = options.args.regions
    output_regions = options.args.output_regions

    # Convert dates
    start_alt = datetime.strptime(options.start_date, "%Y-%m-%d")
    end_alt   = datetime.strptime(options.end_date,   "%Y-%m-%d")

    # Change directory if desired
    os.chdir(input_dir)

    # Collect SWE files
    swe_files = sorted(glob.glob(os.path.join(input_dir, '*.tif')))
    logging.info(f"Found {len(swe_files)} SWE files")

    # Print summary (for now - replace with your actual processing code)
    logging.info(f"err_coeff: {err_coeff}")
    logging.info(f"Output directory: {output_dir}")
    logging.info(f"Mask1 directory: {mask1_dir}")
    logging.info(f"Mask2 directory: {mask2_dir}")
    logging.info(f"Regions: {regions}")
    logging.info(f"Output region names: {output_regions}")
    logging.info(f"Date range for alt processing: {start_alt.date()} to {end_alt.date()}")

    # processing
    region_masks = load_region_masks_from_subdirs(regions, mask1_dir, mask2_dir)
    sample_filename = swe_files[0]
    # Compute latitude array using any sample file
    ds_sample = gdal.Open(sample_filename)
    gt = ds_sample.GetGeoTransform()
    origin_y = gt[3]
    pixel_height = gt[5]
    nrows = ds_sample.RasterYSize
    latitudes = origin_y + np.arange(nrows) * pixel_height  
    res = np.round(gt[1],5) #longitude resolution
    dx = res/2
    max_lat = np.round(np.max(latitudes),3)   
    # --- Define latitude centers (from north to south) ---
    lat_centers = max_lat - np.arange(nrows) * res  # North to south
    # --- Get area per row ---
    area_per_row = area(lat_centers,dx)  # shape: (3351,)
    # --- Repeat for all columns (6935) ---
    ncols = ds_sample.RasterXSize
    area_grid = np.tile(area_per_row[:, np.newaxis], (1, ncols))  # shape: (3351, 6935)

    # Compute means
    compute_means_with_mask_switch(swe_files, region_masks,regions, output_regions,output_dir,err_coeff,area_grid)


def load_region_masks_from_subdirs(regions: list, mask1_dir: str, mask2_dir: str,
                                   template1: str = 'snodas_{region}_mask.csv',
                                   template2: str = 'repaired_{region}_mask.csv') -> dict:
    """
    Load region masks from separate directories for mask1 and mask2.
    
    Args:
        regions:   List of region names (e.g., ['region1', 'region2'])
        mask1_dir: Directory where mask1 CSVs are stored
        mask2_dir: Directory where mask2 CSVs are stored
        template1: File name template for mask1 (default: 'snodas_{region}_mask.csv')
        template2: File name template for mask2 (default: 'repaired_{region}_mask.csv')

    Returns:
        Dictionary with keys like (region_index, 'mask1') -> numpy array
    
    Raises:
        FileNotFoundError: If any mask file is not found.
    """
    masks = {}
    for i, region in enumerate(regions):
        # Paths for mask1 and mask2
        mask1_path = os.path.join(mask1_dir, template1.format(region=region))
        mask2_path = os.path.join(mask2_dir, template2.format(region=region))
        # Read and convert to boolean arrays
        masks[(i, 'basin_mask')] = pd.read_csv(mask1_path, header=None).values.astype(bool)
        masks[(i, 'repaired_mask')] = pd.read_csv(mask2_path, header=None).values.astype(bool)
    return masks


def compute_means_with_mask_switch(file_list: list, region_masks: dict,
                                   region_names: list, output_regions: list,
                                   output_dir: str, err_coeff: float,
                                   area_weights: np.ndarray) -> None:
    """
    Compute area-weighted means for each region, switching masks based on date range.

    Args:
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

        if mid_date < datetime(2014, 10, 1) or mid_date > datetime(2019, 11, 1):
            period = 'basin_mask'
        else:
            period = 'repaired_mask'

        logging.info(f"{mid_date.strftime('%Y-%m')}: Using {period}")

        for j in range(len(region_names)):
            mask = region_masks[(j, period)]  # use tuple key here
            weighted_mean, weighted_sum, total_weight = area_weighted_stats(swe, area_weights, mask)
            #weighted_sum = np.nan_to_num(weighted_sum, nan=np.nan)  # ensure numeric
            #weighted_sum = float(weighted_sum)  # make scalar, not array
            #mean_val = area_weighted_stats(swe, area_weights, mask)
            error_val = float(err_coeff) * weighted_sum if not np.isnan(weighted_sum) else np.nan
            all_results[j].append((weighted_sum, error_val))
            
    # Save CSV files per region
    for i, region_data in enumerate(all_results):
        df = pd.DataFrame(region_data, columns=["swe", "swe_error"])
        df.insert(0, "date", all_dates)
        safe_name = output_regions[i].replace(" ", "_")
        os.makedirs(output_dir, exist_ok=True)
        df['swe'] = df['swe']/1000000000 #swe multiplied by area in m3 to km3
        df['swe_error'] = df['swe_error']/1000000000
        # compute anomaly
        # Filter the period from Jan 2004 to Dec 2009
        swe_values = df['swe'] 
        df['YearMonth'] = pd.to_datetime(df['date']).dt.to_period('M')
        start_period = pd.Period('2004-01', freq='M')
        end_period = pd.Period('2009-12', freq='M')
        time_mask = (df['YearMonth'] >= start_period) & (df['YearMonth'] <= end_period)
        baseline_mean = swe_values[time_mask].mean()
        df['swe'] = swe_values - baseline_mean
        df.drop(columns=['YearMonth']).to_csv(f"{output_dir}/anomaly_timeseries_snodas_{safe_name}.csv", index=False)
    logging.info("CSV files saved:", [f"{output_dir}/{r.replace(' ','_')}.csv" for r in region_names])


def extract_date_from_filename(filename: str) -> datetime:
    """
    Extract date from filenames like snowds_yyyy_mm.tif

    Args:
        filename: Filename string.
    
    Returns:
        datetime: Extracted date (15th of month).
    
    Raises:
        ValueError: If date cannot be parsed from filename.
    """
    match = re.search(r'monthly_mean_(\d{4})(\d{2})\.tif', filename)
    if not match:
        raise ValueError(f"Could not parse date from {filename}")
    year, month = map(int, match.groups())
    return datetime(year, month, 15)  # Mid-month


if __name__ == "__main__":
    main()

'''
This script reads Snodas swe monthly grid data from geotif and csv masks (reg and repaired repaired (for 2014-2019)) 
and generates monthly timeseries for swe anomaly and error values as percentage of monthly mean before computing anomaly.
 
Example usage 
python grace_toolkit\snodas_monthly_anomaly.py `
  --input_dir "C:/data/snodas/monthly_data" `
  --err_coeff 0.20 `
  --output_dir "C:/data/snodas/monthly_anomaly" `
  --mask1_dir "C:/data/snodas/masks/basin_masks/" `
  --mask2_dir "C:/data/snodas/masks/repaired_masks/" `
  --regions ca Sacramento San_Joaquin Tulare `
  --output_regions california_mask sacramento_mask san_joaquin_mask tulare_buena_vista_lakes_mask `
  --start_date 2014-10-01 `
  --end_date 2019-10-31
'''
