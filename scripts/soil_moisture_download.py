# Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o1 (it/its), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), and GitHub Copilot (it/its).
# Based on the example given here: https://disc.gsfc.nasa.gov/information/howto?keywords=python&title=How%20to%20Access%20GES%20DISC%20Data%20Using%20Python
# This program will only work if Earthdata prerequisite files have already been generated. See https://disc.gsfc.nasa.gov/information/howto?title=How%20to%20Generate%20Earthdata%20Prerequisite%20Files
# Documentation:
# https://github.com/nsidc/earthaccess/tree/main/docs
# https://earthaccess.readthedocs.io/en/latest/
# https://earthaccess.readthedocs.io/en/latest/quick-start/

from pathlib import Path
import datetime as dt
import argparse
import logging
import time

import earthaccess

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name: Path = Path(__file__).stem  # The name of this script without the .py extension
        self.default_doi: str = "10.5067/NL7JTZYO2RVK"  # NLDAS VIC LSM L4 Monthly 0.125 degree v2.0
        self.default_timespan: tuple[str, str] = ("2005-01-01", "2005-03-31T23:59:59")
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
    parser.add_argument("-timespan", type=str, nargs=2, default=options.default_timespan,
                        help=f"Timespan as two dates or datetimes in YYYY, YYYY-MM, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS format. A datetime of 'NOW' will return the current datetime. For example: '-timespan 1980-01-01 1981-01-01' or 'timespan 1980-01-01T00:00:00 1980-01-01T12:30:00' or 'timespan 2017-02 NOW' (default: {' '.join(options.default_timespan)})\n\n")
    parser.add_argument("-region", type=float, nargs=4, default=options.default_region,
                        help=f"Optional region specified as four floats: west south east north. If not provided, the script will default to ({' '.join(map(str, options.default_region))}).\n\n")
    parser.add_argument("-local_dir", type=Path, default=options.default_local_dir,
                        help=f"Local directory to download files to (default: '{options.default_local_dir}').")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = logging.DEBUG
    options.args.local_dir.mkdir(parents=True, exist_ok=True)


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


def _search_data_with_retries(doi: str, temporal: tuple[str, str],
                              bounding_box: tuple[float, float, float, float],
                              num_retries: int = 5,
                              initial_delay: float = 1.0,
                              backoff: float = 2.0) -> list[earthaccess.results.DataGranule]:
    """
    Retries earthaccess.search_data when CMR intermittently returns 5xx / Internal Error.

    Args:
        doi:          DOI to use for the search_data call.
        temporal:     Tuple of two strings representing start and end dates/datetimes.
        bounding_box: Tuple of four floats representing west, south, east, north bounding box.

    Returns:
        The result of the earthaccess.search_data call.

    Raises:
        RuntimeError: If the search_data call fails after all retries.
    """
    delay = initial_delay
    last_exc = None
    for attempt in range(1, num_retries + 1):
        try:
            logging.info(f"Searching for data (attempt {attempt}/{num_retries})...")
            return earthaccess.search_data(doi=doi,
                                           temporal=temporal,
                                           bounding_box=bounding_box)
        except RuntimeError as e:
            # earthaccess wraps HTTPError as RuntimeError with the response text
            msg = str(e)
            transient = ("Internal Error" in msg) or (" 500 " in msg) or (" 502 " in msg) or (" 503 " in msg) or (" 504 " in msg)
            if not transient:
                raise  # not a transient CMR error; bubble up immediately
            logging.warning(f"Transient CMR error on attempt {attempt}: {msg.strip()}")
            last_exc = e
            if attempt < num_retries:
                time.sleep(delay)
                delay *= backoff
            else:
                break
    # Exhausted retries
    raise last_exc


def download_NLDAS_data(options: Options) -> None:
    """
    Search for and download NLDAS soil moisture data using Earthaccess.

    Args:
        options: An Options instance with parsed arguments. Contains:
           - doi:         DOI to use for the search_data call.
           - timespan:    Tuple of two strings representing start and end dates/datetimes.
           - region:      Tuple of four floats representing west, south, east, north bounding box.
           - local_dir:   Local directory to download files to.

    Returns:
        None. Downloads files to the specified local directory.

    Raises:
        RuntimeError: If no files are found for the specified search criteria.
    """
    start_dt, end_dt = validate_inputs(options)
    logging.info("Downloading soil moisture data from NLDAS using Earthaccess...")
    logging.info("Logging in...")
    auth = earthaccess.login()  # (requires that Earthdata credentials/files already exist)

    results = _search_data_with_retries(
        doi=options.args.doi,
        temporal=(start_dt, end_dt),
        bounding_box=options.args.region,
        num_retries=5  # total attempts
    )

    logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"{results = }")

    logging.info("Downloading data...")
    downloaded_files = earthaccess.download(results, local_path=options.args.local_dir)
    logging.info(f"Downloaded files: {downloaded_files}")


def validate_inputs(options: Options) -> tuple[dt.datetime, dt.datetime]:
    """
    Validate the command line input arguments, make the desired local directory if it doesn't exist, print the input arguments, and return the start/end time datetime objects.

    Args:
        options: An Options instance with parsed arguments. Contains:
           - region:      Tuple of four floats representing west, south, east, north bounding box.
           - timespan:    Tuple of two strings representing start and end dates/datetimes.
           - local_dir:   Local directory to download files to.

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

    options.args.local_dir.mkdir(parents=True, exist_ok=True)

    logging.info(f"Local directory: {options.args.local_dir}")
    logging.info(f"DOI: {options.args.doi}")
    logging.info(f"Timespan:\nStart: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}\n  End: {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Region: {options.args.region}")

    return start_dt, end_dt


if __name__ == "__main__":
    main()
