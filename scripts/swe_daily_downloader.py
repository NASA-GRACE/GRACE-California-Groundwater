import os
import requests
import subprocess
from datetime import datetime, timedelta
import argparse
import logging
import tarfile
from pathlib import Path

import run_all as ra

# Written by Munish Sikka and ChatGPT


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name: Path = Path(__file__).stem  # The name of this script without the .py extension
        self.default_swe_start_date: str = "2005-01-01"
        self.default_swe_end_date:   str = "2005-06-31"
        current_time = datetime.datetime.now()
        self.default_log_file: Path = self.swe_dir /  "logs" / f"swe_download_{current_time.strftime('%Y-%m-%d_%H-%M-%S')}.log" 

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser()
    parser.add_argument("start_date", default=options.default_swe_start_date,
                        help=f"Start date (YYYY-MM-DD) (default: {options.default_swe_start_date})")
    parser.add_argument("end_date", default=options.default_swe_end_date,
                        help=f"End date (YYYY-MM-DD) (default: {options.default_swe_end_date})")
    parser.add_argument("output_dir", default=options.default_output_dir,
                        help="Directory to download, untar and save swe files from Snodas")
    parser.add_argument("log_file", default=options.default_log_file,
                        help=f"Path to log file (e.g., {options.default_log_file})")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = "DEBUG"


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
    start_date    = datetime.strptime(options.args.start_date, "%Y-%m-%d")
    end_date      = datetime.strptime(options.args.end_date, "%Y-%m-%d")
    output_dir    = options.args.output_dir

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
                tar.extractall(path=out_dir)
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
                try:
                    subprocess.run(["gunzip", file], cwd=out_dir, check=True)
                    logging.info(f"Unzipped: {file}")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Failed to unzip {file}: {e}")
                

        for file in os.listdir(out_dir):
            if f"{product_code}" in file and file.endswith(".txt"):
                tif_file = file.replace(".txt", ".tif")
                try:
                    subprocess.run(["gdal_translate", "-of", "GTiff", file, tif_file], cwd=out_dir, check=True)
                    logging.info(f"Converted to GeoTIFF: {tif_file}")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Failed to run gdal translate {file}: {e}")

        # Clean up extras
        for file in os.listdir(out_dir):
            if file.endswith(".txt") or file.endswith(".gz") or file.endswith(".dat") :
                os.remove(os.path.join(out_dir, file))
                logging.info(f"Removed: {file}")

    except Exception as e:
        logging.error(f"Error on {date_str}: {e}")


if __name__ == "__main__":
   main()

#ex usage
#python snodas_downloader.py 2004-01-01 2004-03-31 /home/snodas/output /home/snodas_download.log