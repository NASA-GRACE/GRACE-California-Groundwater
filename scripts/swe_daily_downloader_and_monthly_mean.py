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
import calendar

gdal.UseExceptions()
# Written by Munish Sikka and ChatGPT

TEST_SKIP_LAST_MONTH_LAST_DAY = False  # TEMP: set to False or delete after testing


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_daily_dir:     Path = self.swe_dir /   "daily_data"
        self.default_monthly_dir:   Path = self.swe_dir / "monthly_data"
        current_time:           datetime = datetime.now()
        self.default_log_file:      Path = self.swe_dir /  f"swe_download_{current_time.strftime('%Y-%m-%d_%H-%M-%S')}.log"
        self.default_scale_factor: float = 1000.0
        self.default_cleanup_daily: bool = True  # True: if users want to remove daily files  # False if users want to keep daily GeoTIFFs


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
    date_str   = date.strftime("%Y%m%d")
    tif_target = os.path.join(daily_dir, f'SNODAS_{date_str}.tif')
    tif_target = Path(tif_target)
    if tif_target.exists():
        logging.info(f"[Skip] GeoTIFF already exists: {tif_target.name}")
        return True
    year_str   = date.strftime('%Y')
    month_name = date.strftime('%m_%b')

    # URL and local paths
    url = f'https://noaadata.apps.nsidc.org/NOAA/G02158/masked/{year_str}/{month_name}/SNODAS_{date_str}.tar'
    # tar_file = os.path.join(daily_dir, f'SNODAS_{date_str}.tar')
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
                if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug(f"Removed: {file}")

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


# -------- Helpers for "_missing_days" filenames -------- #
MONTHTIF_RE = re.compile(
    r"^monthly_mean_(\d{6})_(\d{2})_(\d{2})(?:_missing_((?:\d{2}(?:_\d{2})*)))?\.tif$"
)


def parse_monthly_mean_filename(p: Path) -> dict | None:
    """
    Parse a monthly_mean_*.tif filename and return components:
    {
        'ym': 'YYYYMM',
        'first': int,
        'last': int,
        'missing': [ints],
        'days_used': [ints]     # fully enumerated days used to compute the file
    }
    """
    m = MONTHTIF_RE.match(p.name)
    if not m:
        return None
    ym, first, last, miss = m.groups()
    first_i, last_i = int(first), int(last)
    missing_days = []
    if miss:
        missing_days = [int(x) for x in miss.split("_") if x]
    # days actually used (first..last minus explicit missing)
    days_used = [d for d in range(first_i, last_i + 1) if d not in set(missing_days)]
    return {
        "ym": ym,
        "first": first_i,
        "last": last_i,
        "missing": missing_days,
        "days_used": days_used,
    }


def build_missing_suffix_inrange(first_day: int, last_day: int, available_days: list[int]) -> str:
    """
    Only encode missing days strictly within the observed range [first_day, last_day].
    Trailing days after last_day (or leading before first_day) are NOT listed in the suffix.
    """
    avail = {d for d in available_days if first_day <= d <= last_day}
    missing = sorted(set(range(first_day, last_day + 1)) - avail)
    if not missing:
        return ""
    return "_missing_" + "_".join(f"{d:02d}" for d in missing)


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

    start_date    = datetime.strptime(options.args.start_date, "%Y-%m-%d")
    end_date      = datetime.strptime(options.args.end_date,   "%Y-%m-%d")
    daily_dir     = options.args.daily_dir
    monthly_dir   = options.args.monthly_dir
    scale_factor  = options.args.scale_factor
    cleanup_daily = options.args.cleanup_daily

    os.makedirs(monthly_dir, exist_ok=True)
    os.makedirs(daily_dir, exist_ok=True)

    def cleanup_month_if_needed(current_dt: datetime, yyyymm: str) -> None:
        """Month-scoped cleanup that honors the 'last-month & missing-last-day' exception."""
        is_last_month           = (current_dt.year == end_date.year and current_dt.month == end_date.month)
        cal_last_day            = calendar.monthrange(current_dt.year, current_dt.month)[1]
        last_day_fname          = f"SNODAS_{yyyymm}{cal_last_day:02d}.tif"
        has_last_day            = (Path(daily_dir) / last_day_fname).exists()
        skip_cleanup_this_month = is_last_month and (not has_last_day)

        if cleanup_daily and not skip_cleanup_this_month:
            for f in (daily_dir).glob(f"SNODAS_{yyyymm}*.tif"):
                f.unlink()
            logging.info(f"Cleaned up daily GeoTIFFs for {current_dt.strftime('%Y-%m')}")
        elif cleanup_daily and skip_cleanup_this_month:
            logging.info(
                f"Preserving daily GeoTIFFs for {current_dt.strftime('%Y-%m')} "
                f"because it's the last month being processed and the last calendar day ({cal_last_day:02d}) is missing."
            )

    current = start_date.replace(day=1)
    while current <= end_date:
        month_end = (current.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)  # "Last day of month"
        if month_end > end_date:
            month_end = end_date

        logging.info(f"Processing month: {current.strftime('%Y-%m')}")

        # Skip month if output already exists
        current_month_str = current.strftime('%Y%m')

        # --- Check if a monthly file exists and whether it's complete; if not, try to fill it --- #
        existing_monthlies = sorted(monthly_dir.glob(f"monthly_mean_{current_month_str}_*.tif"))
        if existing_monthlies:
            # Prefer the most recent one by modification time (latest computation)
            existing_monthlies.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            existing = existing_monthlies[0]
            parts = parse_monthly_mean_filename(existing)
            if parts is None:
                logging.warning(f"Found monthly file with unexpected name: {existing.name}. Will not skip month.")
            else:
                days_in_this_month = month_end.day
                # What the *complete* set should be for this run window (1..month_end.day)
                complete_set = set(range(1, days_in_this_month + 1))
                used_set = set(parts["days_used"])

                # Local daily files we already have (regardless of what the monthly file used)
                local_daily = sorted([
                    int(Path(f).stem.split("_")[1][-2:])
                    for f in (daily_dir).glob(f"SNODAS_{current_month_str}*.tif")
                ])
                local_set = set(local_daily)

                # If the monthly file used all required days for this run window, skip.
                # Do NOT require local daily files to still be present (they may have been cleaned up).
                if used_set == complete_set:
                    logging.info(f"Monthly file for {current_month_str} is already complete. Skipping.")
                    current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)  # "next month"
                    continue

                # Otherwise, try to download any missing days that are not local yet
                needed_days = sorted(complete_set - local_set)
                if needed_days:
                    logging.info(f"Attempting to fill missing local daily files for {current_month_str}: {needed_days}")
                    for dnum in needed_days:
                        ddate = current.replace(day=dnum)
                        download_and_process_day(ddate, daily_dir)

                # Re-scan local dailies after attempted downloads
                local_daily_after = sorted([
                    int(Path(f).stem.split("_")[1][-2:])
                    for f in (daily_dir).glob(f"SNODAS_{current_month_str}*.tif")
                ])
                local_set_after = set(local_daily_after)

                # If nothing changed, keep existing and move on
                if local_set_after == local_set:
                    logging.info(f"No new daily files became available for {current_month_str}. Keeping existing monthly.")
                    current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
                    continue

                # We have more daily files now; recompute monthly and replace the old one
                monthly_files = sorted([
                    str(f) for f in (daily_dir).glob(f"SNODAS_{current_month_str}*.tif")
                    if f.is_file()
                ])
                if monthly_files:
                    day_nums           = sorted(int(Path(f).stem.split("_")[1][-2:]) for f in monthly_files)
                    first_day          = f"{min(day_nums):02d}"
                    last_day           = f"{max(day_nums):02d}"
                    missing_suffix     = build_missing_suffix_inrange(int(first_day), int(last_day), day_nums)
                    new_output         = monthly_dir / f"monthly_mean_{current_month_str}_{first_day}_{last_day}{missing_suffix}.tif"

                    logging.info(f"Recomputing monthly mean for {current_month_str} using {len(day_nums)} daily files.")
                    compute_monthly_mean(monthly_files, str(new_output), scale_factor=scale_factor)

                    try:
                        existing.unlink()
                        logging.info(f"Removed older monthly file: {existing.name}")
                    except Exception as e:
                        logging.warning(f"Could not remove older monthly file {existing.name}: {e}")

                    # Cleanup for this month after recompute (DRY helper)
                    cleanup_month_if_needed(current, current_month_str)
                else:
                    logging.warning(f"No daily GeoTIFFs found after attempted fill for {current_month_str}.")
                # Advance to next month
                current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
                continue

        # --- Step 1: Download daily data for this month ---
        # Identify whether this is the final month and what its calendar last day is
        is_last_month = (current.year == end_date.year and current.month == end_date.month)
        cal_last_day = calendar.monthrange(current.year, current.month)[1]
        d = current
        while d <= month_end:
            # TEST HOOK: skip the very last day's file for the final month
            if (
                TEST_SKIP_LAST_MONTH_LAST_DAY
                and is_last_month
                and d.day == cal_last_day
            ):
                logging.info("TEST ONLY: Skipping download of the last month's last day to simulate an incomplete month.")
                d += timedelta(days=1)
                continue
            download_and_process_day(d, daily_dir)
            d += timedelta(days=1)

        # --- Step 2: Compute monthly mean ---
        # Filter the files by the date string in the filename
        monthly_files = sorted([
            str(f) for f in daily_dir.glob("SNODAS_*.tif")
            if f.is_file() and f.name.startswith(f"SNODAS_{current_month_str}")
        ])

        if monthly_files:
            # Available day numbers from local daily GeoTIFFs for this month
            day_nums = sorted(int(Path(f).stem.split("_")[1][-2:]) for f in monthly_files)

            # Determine month length respecting end_date (partial month allowed)
            days_in_this_month = month_end.day  # 1..month_end.day

            first_day = f"{min(day_nums):02d}"
            last_day  = f"{max(day_nums):02d}"

            # NEW: add suffix if any day in 1..month_end.day is missing locally
            missing_suffix = build_missing_suffix_inrange(int(first_day), int(last_day), day_nums)


            output_path = monthly_dir / f"monthly_mean_{current_month_str}_{first_day}_{last_day}{missing_suffix}.tif"
            compute_monthly_mean(monthly_files, str(output_path), scale_factor=scale_factor)
        else:
            logging.warning("No daily GeoTIFFs found for this month, skipping mean computation.")

        # --- Step 3: Cleanup ---
        cleanup_month_if_needed(current, current_month_str)

        # Advance to next month
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


if __name__ == "__main__":
   main()
