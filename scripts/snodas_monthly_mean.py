import os
from pathlib import Path
import re
from collections import defaultdict
from datetime import datetime
import logging
import argparse

# Import compute_mean_raster function
from compute_mean_geotif import compute_mean_raster  

import run_all as ra

#Written by Munish Sikka and ChatGPT


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name: Path = Path(__file__).stem  # The name of this script without the .py extension
        self.default_daily_dir: Path = self.swe_dir /  "daily_data"
        self.default_output_dir: Path = self.swe_dir / "monthly_data"
        self.default_scale_factor: float = 1000.0
        

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Compute monthly mean rasters from daily .tif files")
    parser.add_argument("daily_dir", default=options.default_daily_dir
                        help="Directory with daily .tif files")
    parser.add_argument("output_dir", default=options.default_output_dir,
                        help="Directory to save monthly mean rasters")
    parser.add_argument("scale_factor", default=options.default_scale_factor,
                        type=float,
                        help="Scale factor to apply to raster values")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = "DEBUG"


def main() -> None:
    """Main function to process monthly means for snow water equivalent (SWE) data."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    if options.swe_model == "SNODAS":
        process_all_months_for_SNODAS(options)
    else:
        raise ValueError(f"Unsupported snow water equivalent (SWE) model: {options.swe_model}")


def process_all_months_for_SNODAS(options: Options) -> None:
    """
    For each month found in daily_dir, compute mean raster and save output to output_dir.

    Args:
        options: An Options instance with parsed command line arguments in options.args. Contains:
           - daily_dir:    Directory with daily .tif files.
           - output_dir:   Directory to save monthly mean rasters.
           - scale_factor: Scale factor to apply to raster values.

    Returns:
        None. Saves monthly mean rasters to output_dir.
    
    Raises:
        None.
    """
    daily_dir    = options.args.daily_dir
    output_dir   = options.args.output_dir
    scale_factor = options.args.scale_factor

    os.makedirs(output_dir, exist_ok=True)
    monthly_files = find_monthly_files(daily_dir)

    for ym, files in sorted(monthly_files.items()):
        if not files:
            logging.info(f"No files for month {ym}, skipping.")
            continue
        files.sort()
        output_path = os.path.join(output_dir, f"monthly_mean_{ym}.tif")
        try:
            compute_mean_raster(files, output_path, scale_factor)
        except Exception as e:
            logging.error(f"Failed processing month {ym}: {e}")


def find_monthly_files(daily_dir: str) -> dict[str, list[str]]:
    """
    Scan daily data dir for .tif files, parse YYYYMMDD from filename,
    group files by YYYYMM string.
    Assumes filenames contain dates like '...YYYYMMDD...tif'.

    Args:
        daily_dir: Directory with daily .tif files.
    
    Returns:
        dict: Mapping from 'YYYYMM' to list of file paths for that month.
    
    Raises:
        None.
    """
    monthly_files = defaultdict(list)
    pattern = re.compile(r'(\d{8})')  # look for 8-digit date

    for fname in os.listdir(daily_dir):
        if fname.endswith('.tif'):
            match = pattern.search(fname)
            if match:
                date_str = match.group(1)
                try:
                    dt = datetime.strptime(date_str, "%Y%m%d")
                    ym = dt.strftime("%Y%m")  # e.g. '200401'
                    full_path = os.path.join(daily_dir, fname)
                    monthly_files[ym].append(full_path)
                except ValueError:
                    logging.warning(f"Invalid date in filename {fname}, skipping.")
            else:
                logging.warning(f"No date found in filename {fname}, skipping.")
    return monthly_files


if __name__ == "__main__":
    main()
