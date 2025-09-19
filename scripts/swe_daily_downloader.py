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
gdal.UseExceptions()
# Written by Munish Sikka and ChatGPT


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:             str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_output_dir: Path = self.swe_dir / "daily_data"
        current_time = datetime.now()
        self.default_log_file: Path = self.swe_dir /  f"swe_download_{current_time.strftime('%Y-%m-%d_%H-%M-%S')}.log" 
        #self.default_log_file: Path = self.swe_dir /  "logs" / f"swe_download_{current_time.strftime('%Y-%m-%d_%H-%M-%S')}.log" 

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--start_date", default=options.test_start,
                        help=f"Start date (default: {options.test_start})")
    parser.add_argument("--end_date", default=options.test_end,
                        help=f"End date (default: {options.test_end})")
    parser.add_argument("--output_dir", default=options.default_output_dir,
                        help="Directory to download, untar and save swe files from SNODAS")
    parser.add_argument("--log_file", default=options.default_log_file,
                        help=f"Path to log file (e.g., {options.default_log_file})")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    # Format dates as YYYY-MM-DD regardless of their original format by parsing and reformatting.
    options.args.start_date = (ra.parse_datetime(options.args.start_date)).strftime("%Y-%m-%d")
    options.args.end_date   = (ra.parse_datetime(options.args.end_date  )).strftime("%Y-%m-%d")

def main() -> None:
    """Main function to download and process snow water equivalent (SWE) data over a date range."""
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
        download_SNODAS(options)
    else:
        raise ValueError(f"Unsupported snow water equivalent (SWE) model: {options.swe_model}")


def download_SNODAS(options: Options) -> None:
    """
    Download and process SNODAS data over a date range.
    
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
    output_dir = options.args.output_dir

    os.makedirs(output_dir, exist_ok=True)

    current = start_date
    while current <= end_date:
        download_and_process(current, out_dir=output_dir)
        current += timedelta(days=1)


def setup_logger(options: Options, log_path: str) -> None:
    """Setup logging to file and console."""
    logging.basicConfig(
        filename=log_path,
        filemode='a',
        format='%(asctime)s - %(levelname)s - %(message)s',
        level=options.log_mode
    )
    logging.getLogger().addHandler(logging.StreamHandler())  # Also print to console


def download_and_process(date: datetime, product_code: str = '1034', out_dir: str = '.') -> None:
    """Download, extract, gunzip, and convert SNODAS data for a given date."""
    year_str = date.strftime('%Y')
    month_name = date.strftime('%m_%b')
    date_str = date.strftime('%Y%m%d')

    # URL and local paths
    url = f'https://noaadata.apps.nsidc.org/NOAA/G02158/masked/{year_str}/{month_name}/SNODAS_{date_str}.tar'
    tar_file = os.path.join(out_dir, f'SNODAS_{date_str}.tar')

    try:
        os.makedirs(out_dir, exist_ok=True)
        logging.info(f"Downloading {url}...")
        r = requests.get(url, stream=True, timeout=30)
        if r.status_code != 200:
            logging.warning(f"File not found or inaccessible: {url}")
            return
        with open(tar_file, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.info(f"Downloaded {tar_file}")

        # Extract TAR
        try:
            with tarfile.open(tar_file) as tar:
                tar.extractall(path=out_dir, filter="data")
                logging.info(f"Extracted: {tar_file}")
        except tarfile.TarError as e:
            logging.error(f"Failed to extract {tar_file}: {e}")
            return
        
        # Remove TAR after successful extraction
        os.remove(tar_file)
        logging.info(f"Extracted and removed: {tar_file}")

        # Gunzip and convert
        for file in os.listdir(out_dir):
            if f"{product_code}" in file and file.endswith(".gz"):
                gz_path = os.path.join(out_dir, file)
                unzipped_path = gz_path.replace(".gz", "")
                try:
                    with gzip.open(gz_path, 'rb') as f_in:
                        with open(unzipped_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(gz_path)  # Remove .gz file after extraction
                    #subprocess.run(["gunzip", file], cwd=out_dir, check=True)
                    logging.info(f"Unzipped: {file}")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Failed to unzip {file}: {e}")
        # Convert .txt to GeoTIFF using GDAL Python API        
        for file in os.listdir(out_dir):
            if f"{product_code}" in file and file.endswith(".txt"):
                input_path = os.path.join(out_dir, file)
                output_path = os.path.join(out_dir, file.replace(".txt", ".tif"))
                #txt_file = os.path.join(out_dir, file)
                #tif_file = os.path.join(out_dir, file.replace(".txt", ".tif"))
                try:
                    ds = gdal.Open(input_path)
                    if ds is None:
                        logging.error(f"GDAL failed to open {input_path}")
                        continue
                    gdal.Translate(output_path, ds, format="GTiff")
                    ds = None
                    logging.info(f"Converted to GeoTIFF: {output_path}")
                except Exception as e:
                    logging.error(f"Failed to convert {file} to GeoTIFF: {e}")
                    
        # Clean up extras
        for file in os.listdir(out_dir):
            if file.endswith(".txt") or file.endswith(".gz") or file.endswith(".dat") :
                os.remove(os.path.join(out_dir, file))
                logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Removed: {file}")

    except Exception as e:
        logging.error(f"Error on {date_str}: {e}")


if __name__ == "__main__":
   main()

#ex usage
#python SNODAS_downloader.py 2004-01-01 2004-03-31 /home/SNODAS/output /home/SNODAS_download.log