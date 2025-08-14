# Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o1 (it/its), and GitHub Copilot (it/its).
# Based on the example given here: https://disc.gsfc.nasa.gov/information/howto?keywords=python&title=How%20to%20Access%20GES%20DISC%20Data%20Using%20Python
# This program will only work if Earthdata prerequisite files have already been generated. See https://disc.gsfc.nasa.gov/information/howto?title=How%20to%20Generate%20Earthdata%20Prerequisite%20Files
# Documentation:
# https://github.com/nsidc/earthaccess/tree/main/docs
# https://earthaccess.readthedocs.io/en/latest/
# https://earthaccess.readthedocs.io/en/latest/quick-start/

import os
from pathlib import Path
import datetime as dt
import argparse
import logging

import earthaccess

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name: Path = Path(__file__).stem  # The name of this script without the .py extension
        self.default_doi: str = "10.5067/NL7JTZYO2RVK"  # NLDAS VIC LSM L4 Monthly 0.125 degree v2.0
        self.default_timespan: tuple[str, str] = ("1980-01-01", "1980-01-01")
        self.default_region: tuple[float, float, float, float] = (-180, -90, 180, 90)  # defaults to global region
        self.default_local_dir: Path = self.soil_moisture_dir / "data_monthly"


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Download specified data files using Earthaccess. If this program is called without input arguments, it will download a single 8 MB file to the current directory. However, this will only work if Earthdata prerequisite files have already been generated. See https://disc.gsfc.nasa.gov/information/howto?title=How%20to%20Generate%20Earthdata%20Prerequisite%20Files", formatter_class=argparse.RawTextHelpFormatter)  # RawTextHelpFormatter preserves newlines in the help text
    parser.add_argument("-doi", default=options.default_doi,
        help=(f"DOI to use for the search_data call (default: {options.default_doi})\n"
              "More choices:\n"
              "10.5067/45T7K120BJ2S : NLDAS VIC    LSM L4 Hourly  0.125 degree v2.0\n"
              "10.5067/NL7JTZYO2RVK : NLDAS VIC    LSM L4 Monthly 0.125 degree v2.0\n"
              "10.5067/T4OW83T8EXDO : NLDAS Noah   LSM L4 Hourly  0.125 degree v2.0\n"
              "10.5067/WB224IA3PVOJ : NLDAS Noah   LSM L4 Monthly 0.125 degree v2.0\n"
              "10.5067/TS58ZCJZIWT5 : NLDAS Mosaic LSM L4 Hourly  0.125 degree v2.0\n"
              "10.5067/YQ1P3OP48R8M : NLDAS Mosaic LSM L4 Monthly 0.125 degree v2.0\n\n"))
    parser.add_argument("-timespan", nargs=2, default=options.default_timespan,
                        help=f"Timespan as two dates or datetimes in YYYY, YYYY-MM, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS format. A datetime of 'NOW' will return the current datetime. For example: '-timespan 1980-01-01 1981-01-01' or 'timespan 1980-01-01T00:00:00 1980-01-01T12:30:00' or 'timespan 2017-02 NOW' (default: {' '.join(options.default_timespan)})\n\n")
    parser.add_argument("-region", nargs=4, type=float, default=options.default_region,
                        help=f"Optional region specified as four floats: west south east north. If not provided, the script will default to ({' '.join(map(str, options.default_region))}).\n\n")
    parser.add_argument("-local_dir", default=options.default_local_dir,
                        help=f"Local directory to download files to (default: '{options.default_local_dir}').")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = "DEBUG"


def main() -> None:
    """Main function to download soil moisture data."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    if options.soil_moisture_model == "NLDAS":
        download_NLDAS_data(options)
    else:
        raise ValueError(f"Unsupported soil moisture model: {options.soil_moisture_model}")


def download_NLDAS_data(options: Options) -> None:
    """
    Search for and download NLDAS soil moisture data using Earthaccess.

    Args:
        options: An Options instance with parsed command line arguments in options.args.

    Returns:
        None. Downloads files to the specified local directory.

    Raises:
        RuntimeError: If no files are found for the specified search criteria.
    """
    start_dt, end_dt = validate_inputs(options)
    logging.info("Downloading soil moisture data from NLDAS using Earthaccess...")
    logging.info("Logging in...")
    auth = earthaccess.login()  # (requires that Earthdata credentials/files already exist)

    logging.info("Searching for data...")
    results = earthaccess.search_data(
        doi=options.args.doi,
        temporal=(start_dt, end_dt),
        bounding_box=options.args.region
    )
    logging.debug(f"{results = }")

    logging.info("Downloading data...")
    downloaded_files = earthaccess.download(results, local_path=options.args.local_dir)
    logging.info(f"Downloaded files: {downloaded_files}")


def validate_inputs(options: Options) -> tuple[dt.datetime, dt.datetime]:
    """
    Validate the command line input arguments, make the desired local directory if it doesn't exist, print the input arguments, and return the start/end time datetime objects.

    Args:
        options: An Options instance with parsed command line arguments in options.args.

    Returns:
        A tuple of two datetime.datetime objects: (start_dt, end_dt).

    Raises:
        ValueError: If any input arguments are invalid.    
    """
    reminder = "Remember, the region needs to be specified as '--region west south east north'."
    if len(options.args.region) != 4:
        raise ValueError(f"Region must have exactly four values. {reminder}")
    west, south, east, north = options.args.region
    if not (west < east and south < north):
        raise ValueError(f"Invalid region: west < east and south < north must both be true. {reminder}")
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError(f"Longitude values must be between -180 and 180. {reminder}")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError(f"Latitude values must be between -90 and 90. {reminder}")
    if west == east or south == north:
        raise ValueError(f"Invalid region: cannot be a line or a single point. {reminder}")

    try:
        start_dt, end_dt = map(ra.parse_datetime, options.args.timespan)
    except ValueError as e:
        raise ValueError(str(e))
    if start_dt > end_dt:
        raise ValueError("Start date must be before end date.")

    Path(options.args.local_dir).mkdir(parents=True, exist_ok=True)

    logging.info(f"Local directory: {options.args.local_dir}")
    logging.info(f"DOI: {options.args.doi}")
    logging.info(f"Timespan:\nStart: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}\n  End: {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Region: {options.args.region}")

    return start_dt, end_dt


if __name__ == "__main__":
    main()
