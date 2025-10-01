import os
import requests
import subprocess
from datetime import datetime, timedelta
import argparse
import logging
import tarfile
from pathlib import Path
import gzip
import shutil
import run_all as ra
from osgeo import gdal
import numpy as np 
import warnings
import re

gdal.UseExceptions()
# Written by Munish Sikka and ChatGPT


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:             str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_daily_dir:  Path = self.swe_dir /   "daily_data"
        self.default_monthly_dir: Path = self.swe_dir / "monthly_data"
        current_time = datetime.now()
        self.default_log_file: Path = self.swe_dir /  f"swe_download_{current_time.strftime('%Y-%m-%d_%H-%M-%S')}.log" 
        self.default_scale_factor: float = 1000.0
        self.default_cleanup_daily: bool = True #True: if users want to remove daily files  # False if users want to keep daily GeoTIFFs 

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Compute monthly mean rasters from daily .tif files")
    parser.add_argument("--start_date", default=options.test_start,
                        help=f"Start date (default: {options.test_start})")
    parser.add_argument("--end_date", default=options.test_end,
                        help=f"End date (default: {options.test_end})")
    parser.add_argument("--daily_dir", default=options.default_daily_dir,
                        help="Directory to download, untar and save daily data swe files from SNODAS")
    parser.add_argument("--monthly_dir", default=options.default_monthly_dir,
                        help="Directory to save monthly swe files from SNODAS")
    parser.add_argument("--scale_factor", default=options.default_scale_factor, type=float,
                        help="Scale factor to apply to raster values")
    parser.add_argument("--cleanup_daily", default=options.default_cleanup_daily, type=bool,
                        help="flag to remove or keep daily swe geotif files after computing monthly")
    parser.add_argument("--log_file", default=options.default_log_file,
                        help=f"Path to log file (e.g., {options.default_log_file})")
    parser.add_argument("--full", action="store_true",
                        help=f"If set, download the full timespan ({options.full_start} - {options.full_end})")
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
    """Main function to download and process snow water equivalent (SWE) data over a date range."""
    gdal.UseExceptions()  # Enable GDAL exceptions for error handling
    options = Options()
    parse_arguments(options)

    # Add timestamp to log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_base = options.args.log_file
    log_path = os.path.join(
        os.path.dirname(log_file_base),
        f"{os.path.splitext(os.path.basename(log_file_base))[0]}_{timestamp}.log"
    )

    setup_logger(options, log_path)
    if options.swe_model == "SNODAS":
        snodas_monthly_pipeline(options)
    else:
        raise ValueError(f"Unsupported snow water equivalent (SWE) model: {options.swe_model}")

def setup_logger(options: Options, log_path: str) -> None:
    """Setup logging to file and console."""
    logging.basicConfig(
        filename=log_path,
        filemode='a',
        format='%(asctime)s - %(levelname)s - %(message)s',
        level=options.log_mode
    )
    logging.getLogger().addHandler(logging.StreamHandler())  # Also print to console

# ------------------ 1. DOWNLOAD & PROCESS ONE DAY ------------------ #
def download_and_process_day(date: datetime, daily_dir: str, product_code: str = '1034') -> None:
    """
    Download, extract, gunzip, and convert SNODAS data for a given date.
    Skips if .tif for that day already exists.
    Returns True if successfully processed or already exists.
    """
    date_str = date.strftime("%Y%m%d")
    tif_target = os.path.join(daily_dir, f'SNODAS_{date_str}.tif')
    tif_target = Path(tif_target)
    if tif_target.exists():
        logging.info(f"[Skip] GeoTIFF already exists: {tif_target.name}")
        return True
    year_str = date.strftime('%Y')
    month_name = date.strftime('%m_%b')

    # URL and local paths
    url = f'https://noaadata.apps.nsidc.org/NOAA/G02158/masked/{year_str}/{month_name}/SNODAS_{date_str}.tar'
    #tar_file = os.path.join(daily_dir, f'SNODAS_{date_str}.tar')
    tar_file = Path(daily_dir) / f"SNODAS_{date_str}.tar"
    
    try:
        os.makedirs(daily_dir, exist_ok=True)
        logging.info(f"Downloading {url}...")
        r = requests.get(url, stream=True, timeout=60)
        if r.status_code != 200:
            logging.warning(f"File not found or inaccessible: {url}")
            return
        # Save TAR
        with open(tar_file, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.info(f"Downloaded {tar_file}")

        # Extract TAR
        try:
            with tarfile.open(tar_file) as tar:
                tar.extractall(path=daily_dir, filter="data")
            tar_file.unlink()
            logging.info(f"Extracted and removed: {tar_file}")
        except tarfile.TarError as e:
            logging.error(f"Failed to extract or remove {tar_file}: {e}")
            return
        
        # Gunzip swe product
        for file in os.listdir(daily_dir):
            if f"{product_code}" in file and file.endswith(".gz"):
                gz_path = os.path.join(daily_dir, file)
                unzipped_path = gz_path.replace(".gz", "")
                try:
                    with gzip.open(gz_path, 'rb') as f_in:
                        with open(unzipped_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(gz_path)  # Remove .gz file after extraction
                    logging.info(f"Unzipped: {file}")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Failed to unzip {file}: {e}")
        
        # Convert .txt to GeoTIFF using GDAL Python API        
        for file in os.listdir(daily_dir):
            if f"{product_code}" in file and file.endswith(".txt"):
                input_path = os.path.join(daily_dir, file)
                try:
                    ds = gdal.Open(input_path)
                    if ds is None:
                        logging.error(f"GDAL failed to open {input_path}")
                        continue
                    gdal.Translate(str(tif_target), ds, format="GTiff")
                    ds = None
                    logging.info(f"Converted to GeoTIFF: {tif_target.name}")
                except Exception as e:
                    logging.error(f"Failed to convert {file} to GeoTIFF: {e}")
                    
        # Clean up extras
        for file in os.listdir(daily_dir):
            if file.endswith(".txt") or file.endswith(".gz") or file.endswith(".dat") :
                os.remove(os.path.join(daily_dir, file))
                logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Removed: {file}")

    except Exception as e:
        logging.error(f"Error on {date_str}: {e}")

# ------------------ 2. COMPUTE MONTHLY MEAN ------------------ #
def compute_monthly_mean(file_list : list[str], output_path: str, scale_factor: float) -> None:
    """
    Computes the mean of a list of raster (.tif) files at each pixel location
    and saves the result as a new raster with filename containing start and end day.

    Args:
        file_list:  Sorted list of raster file paths.
        output_dir: Directory to save the output mean raster.
        
    Returns:
        None. Saves the mean raster to output_path.
    
    Raises:
        ValueError: If file_list is empty.
    """
    if not file_list:
        raise ValueError("No valid daily GeoTIFF files provided.")

    # Open the first raster to get dimensions
    first_ds = gdal.Open(file_list[0])
    band = first_ds.GetRasterBand(1)
    rows, cols = band.YSize, band.XSize
    # Initialize an array to hold stacked data
    data_stack = np.full((len(file_list), rows, cols), np.nan, dtype=np.float32)
    
    # Read each file and stack them
    for i, file in enumerate(file_list):
        ds = gdal.Open(file)
        arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
        nodata = ds.GetRasterBand(1).GetNoDataValue()
        if nodata is not None:
            arr[arr == nodata] = np.nan
        data_stack[i, :, :] = arr / scale_factor
        ds = None
    # Compute the mean across the time axis
    # Suppress warnings about empty slices
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean_raster = np.nanmean(data_stack, axis=0)

    # Replace all-NaN pixels with a NoData value (e.g., NaN or -9999)
    mean_raster = np.where(np.isnan(mean_raster), np.nan, mean_raster)

    # Save output raster
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(output_path, cols, rows, 1, gdal.GDT_Float32)
    # Copy geotransform and projection from first input file
    out_ds.SetGeoTransform(first_ds.GetGeoTransform())
    out_ds.SetProjection(first_ds.GetProjection())
    # Write mean array to raster
    out_band = out_ds.GetRasterBand(1)
    out_band.WriteArray(mean_raster)
    # Set NoData value to NaN for consistency
    out_band.SetNoDataValue(np.nan)
    out_band.FlushCache()
    out_ds = None
    logging.info(f"Monthly mean saved: {output_path}")

# ------------------ MAIN PIPELINE ------------------ #
def snodas_monthly_pipeline(options: Options) -> None:
    """
    End-to-end SNODAS SWE pipeline:
      1. Downloads daily data (skipping existing)
      2. Converts to GeoTIFF
      3. Computes monthly mean
      4. Optionally removes daily GeoTIFFs after each month

    Args:
    options: An Options instance with parsed command line arguments in options.args. Contains:
        - start_date:  Start date (YYYY-MM-DD).
        - end_date:    End date (YYYY-MM-DD).
        - output_dir:  Directory to save files.

    Returns:
        None. Downloads and processes files to the specified local directory.
    
    Raises:
        None.
    """

    start_date = datetime.strptime(options.args.start_date, "%Y-%m-%d")
    end_date   = datetime.strptime(options.args.end_date,   "%Y-%m-%d")
    daily_dir    = options.args.daily_dir
    monthly_dir = options.args.monthly_dir
    scale_factor = options.args.scale_factor
    cleanup_daily= options.args.cleanup_daily
    
    os.makedirs(monthly_dir, exist_ok=True)
    os.makedirs(daily_dir, exist_ok=True)

    #start = datetime.strptime(start_date, "%Y-%m-%d")
    #end = datetime.strptime(end_date, "%Y-%m-%d")
 
    current = start_date.replace(day=1)
    while current <= end_date:
        month_end = (current.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if month_end > end_date:
            month_end = end_date

        logging.info(f"Processing month: {current.strftime('%Y-%m')}")

        # --- Step 1: Download daily data for this month ---
        d = current
        while d <= month_end:
            download_and_process_day(d, daily_dir)
            d += timedelta(days=1)

        # --- Step 2: Compute monthly mean ---
        # Get the YYYYMM string for the current month being processed
        current_month_str = current.strftime('%Y%m')
        
        # Filter the files by the date string in the filename
        monthly_files = sorted([
            str(f) for f in daily_dir.glob("SNODAS_*.tif") 
            if f.is_file() and f.name.startswith(f"SNODAS_{current_month_str}")
        ])
        #monthly_files = sorted([str(f) for f in daily_dir.glob("SNODAS_*.tif") if f.is_file()])

        if monthly_files:
            output_path = monthly_dir / f"monthly_mean_{current.strftime('%Y%m')}.tif"
            compute_monthly_mean(monthly_files, str(output_path), scale_factor=scale_factor)
        else:
            logging.warning("No daily GeoTIFFs found for this month, skipping mean computation.")

        # --- Step 3: Cleanup ---
        if cleanup_daily:
            for f in daily_dir.glob("SNODAS_*.tif"):
                f.unlink()
            logging.info(f"Cleaned up daily GeoTIFFs for {current.strftime('%Y-%m')}")

        # Advance to next month
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)

if __name__ == "__main__":
   main()
