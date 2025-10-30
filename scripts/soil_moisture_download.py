# Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o1 (it/its), ChatGPT o4-mini-high (it/its), ChatGPT 5 Thinking (it/its), and GitHub Copilot (it/its).
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
from urllib.parse import urlparse
import shutil
from typing import Iterable

import earthaccess

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                      str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_doi:                  str = "10.5067/NL7JTZYO2RVK"  # NLDAS VIC LSM L4 Monthly 0.125 degree v2.0
        self.default_timespan: tuple[str, str] = (self.test_start, self.test_end)  # Quick test timespan (strings)
        self.full_timespan:    tuple[str, str] = (self.full_start, self.full_end)  # Full timespan (strings)
        self.default_local_dir:           Path = self.soil_moisture_dir / "data_individual"  # Also in soil_moisture_process.py
        self.retry_attempts:               int = 3
        self.default_region: tuple[float, float, float, float] = (-180, -90, 180, 90)  # defaults to global region


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Download specified data files using Earthaccess. If this program is called without input arguments, it will download a single 8 MB file to the current directory. However, this will only work if Earthdata prerequisite files have already been generated. See https://disc.gsfc.nasa.gov/information/howto?title=How%20to%20Generate%20Earthdata%20Prerequisite%20Files", formatter_class=argparse.RawTextHelpFormatter)  # RawTextHelpFormatter preserves newlines in the help text
    parser.add_argument("--doi", default=options.default_doi,
        help=(f"DOI to use for the search_data call (default: {options.default_doi})\n"
              "More choices:\n"
              f"10.5067/45T7K120BJ2S : {options.soil_moisture_model} VIC    LSM L4 Hourly  0.125 degree v2.0\n"
              f"10.5067/NL7JTZYO2RVK : {options.soil_moisture_model} VIC    LSM L4 Monthly 0.125 degree v2.0\n"
              f"10.5067/T4OW83T8EXDO : {options.soil_moisture_model} Noah   LSM L4 Hourly  0.125 degree v2.0\n"
              f"10.5067/WB224IA3PVOJ : {options.soil_moisture_model} Noah   LSM L4 Monthly 0.125 degree v2.0\n"
              f"10.5067/TS58ZCJZIWT5 : {options.soil_moisture_model} Mosaic LSM L4 Hourly  0.125 degree v2.0\n"
              f"10.5067/YQ1P3OP48R8M : {options.soil_moisture_model} Mosaic LSM L4 Monthly 0.125 degree v2.0\n\n"))
    parser.add_argument("--timespan", type=str, nargs=2, default=options.default_timespan,
                        help=f"Timespan as two dates or datetimes in YYYY, YYYY-MM, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS format. A datetime of 'NOW' will return the current datetime. For example: '-timespan 1980-01-01 1981-01-01' or 'timespan 1980-01-01T00:00:00 1980-01-01T12:30:00' or 'timespan 2017-02 NOW' (default: {' '.join(options.default_timespan)})\n\n")
    parser.add_argument("--region", type=float, nargs=4, default=options.default_region,
                        help=f"Optional region specified as four floats: west south east north. If not provided, the script will default to ({' '.join(map(str, options.default_region))}).\n\n")
    parser.add_argument("--local_dir", type=Path, default=options.default_local_dir,
                        help=f"Local directory to download files to (default: '{options.default_local_dir}').")
    parser.add_argument("--full", action="store_true",
                        help=f"If set, download the full timespan ({options.full_timespan}).")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    if getattr(options.args, "full", False):
        options.args.timespan = options.full_timespan
    options.args.local_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Main function to download soil moisture data."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    if options.soil_moisture_model == "NLDAS":
        download_NLDAS_data(options)
    else:
        raise ValueError(f"Unsupported soil moisture model: {options.soil_moisture_model}")


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
    logging.info(f"Downloading soil moisture data from {options.soil_moisture_model} using Earthaccess...")
    logging.info("Logging in...")
    auth = earthaccess.login()  # (requires that Earthdata credentials/files already exist)

    results = _search_data_with_retries(
        doi=options.args.doi,
        temporal=(start_dt, end_dt),
        bounding_box=options.args.region,
        num_retries=5  # total attempts
    )

    if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug(f"{results = }")

    logging.info("Downloading and validating data...")
    ok_files, bad_files = _download_with_validation_and_retry(options, results)
    logging.info("Valid files: %d", len(ok_files))
    if bad_files:
        logging.warning("Quarantined/unusable files: %d (see _quarantine_bad_netcdf)", len(bad_files))
    else:
        logging.info("All granules validated successfully.")


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

    start_dt, end_dt = map(ra.parse_datetime, options.args.timespan)
    if start_dt > end_dt:
        raise ValueError("Start date must be before end date.")

    options.args.local_dir.mkdir(parents=True, exist_ok=True)

    logging.info(f"Local directory: {options.args.local_dir}")
    logging.info(f"DOI: {options.args.doi}")
    logging.info(f"Timespan:\nStart: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}\n  End: {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Region: {options.args.region}")

    return start_dt, end_dt


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


def _looks_like_netcdf(path: Path) -> bool:
    """
    Cheap magic-byte sniff: HDF5 or classic netCDF.

    Args:
        path: The file path to check.

    Returns:
        True if the file looks like a NetCDF/HDF file; False otherwise.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
        return head.startswith(b"\x89HDF\r\n\x1a\n") or head.startswith(b"CDF\x01") or head.startswith(b"CDF\x02")
    except Exception:
        return False


def _openable_by_xarray(path: Path) -> tuple[bool, str]:
    """
    Try opening with xarray/netcdf4; return (ok, reason_if_not_ok).

    Args:
        path: The file path to check.

    Returns:
        A tuple (True, "") if the file can be opened; (False, reason) otherwise.
    """
    try:
        import xarray as xr  # heavy import only when needed
        with xr.open_dataset(path, engine="netcdf4", decode_times=False) as ds:
            _ = list(ds.variables)  # touch structure
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def validate_netcdf_file(path: Path) -> tuple[bool, str]:
    """
    Validate a single NetCDF file by magic bytes and xarray openability.

    Args:
        path: The file path to check.

    Returns:
        (True, "") if valid; (False, reason) otherwise.
    """
    path = Path(path)  # ensure Path object
    if not path.exists():
        return False, "File does not exist"
    if path.stat().st_size == 0:
        return False, "File is empty (size == 0 bytes)"
    if not _looks_like_netcdf(path):
        return False, "Bad magic bytes (not NetCDF/HDF)"
    ok, why = _openable_by_xarray(path)
    if not ok:
        return False, why
    return True, ""


def validate_netcdf_integrity(paths: Iterable[Path],
                              quarantine_dir: Path | None = None,
                              strict: bool = True) -> list[tuple[Path, str]]:
    """
    Validate a list of NetCDF files; optionally move bad ones to a quarantine directory.

    Args:
        paths:          Iterable of file paths to validate.
        quarantine_dir: If provided, bad files will be moved to this directory.
        strict:         If True, raises FileNotFoundError if any bad files are found.

    Returns:
        A list of (bad_path, reason).
    """
    bad: list[tuple[Path, str]] = []
    qdir = Path(quarantine_dir) if quarantine_dir is not None else None
    if qdir is not None:
        qdir.mkdir(parents=True, exist_ok=True)

    for p in map(Path, paths):
        ok, why = validate_netcdf_file(p)
        if not ok:
            if qdir is not None and p.exists():
                try:
                    dst = qdir / p.name
                    shutil.move(str(p), str(dst))
                    logging.warning("Quarantined invalid NetCDF: %s -> %s (%s)", p, dst, why)
                except Exception as m:
                    logging.error("Failed to quarantine %s: %s", p, m)
            bad.append((p, why))

    if strict and bad:
        report = "\n".join(f" - {p.name}: {why}" for p, why in bad)
        raise FileNotFoundError("Invalid/corrupt NetCDF files detected:\n" + report)

    return bad


def _granule_expected_filename(granule) -> str:
    """
    Derive the local filename from the granule's HTTPS data link.

    Args:
        granule: An earthaccess.results.DataGranule instance.

    Returns:
        The expected filename as a string.

    Raises:
        ValueError: If the granule has no downloadable HTTP(S) data link."""
    try:
        links = granule.data_links()
    except Exception:
        links = []
    https = next((u for u in links if u.lower().startswith("http")), links[0] if links else None)
    if not https:
        raise ValueError("Granule has no downloadable HTTP(S) data link")
    return Path(urlparse(https).path).name


def _download_with_validation_and_retry(options: Options, results) -> tuple[list[Path], list[Path]]:
    """
    Download all granules; validate each file and retry up to options.retry_attempts.
    Bad files are moved to a quarantine directory.

    Args:
        options: An Options instance with parsed arguments. Contains:
           - local_dir:   Local directory to download files to.
           - retry_attempts: Number of validation/download attempts per file.
        results: List of earthaccess.results.DataGranule instances to download.

    Returns:
        (ok_files, bad_files).
    """
    local_dir      = Path(options.args.local_dir)
    quarantine_dir = local_dir / "_quarantine_bad_netcdf"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    # Map granules to intended paths
    items: list[tuple[object, Path]] = []
    for g in results:
        try:
            name = _granule_expected_filename(g)
            items.append((g, local_dir / name))
        except Exception as e:
            logging.error("Skipping granule with no usable data link: %s", e)

    ok_files:      list[Path] = []
    bad_files:     list[Path] = []
    to_download: list[object] = []

    # Pre-validate existing files; delete invalid to force clean re-download
    for g, fpath in items:
        if fpath.exists():
            ok, why = validate_netcdf_file(fpath)
            if ok:
                # Touch file to update its modified time so that it's not considered "old" later
                fpath.touch()
                logging.info("Already present and valid: %s", fpath.name)
                ok_files.append(fpath)
            else:
                logging.warning("Existing file invalid: %s (%s) — deleting for re-download", fpath.name, why)
                try:
                    fpath.unlink()
                except Exception as e:
                    logging.error("Failed to delete %s: %s", fpath, e)
                to_download.append(g)
        else:
            to_download.append(g)

    # Batch download missing ones
    if to_download:
        logging.info("Downloading %d missing granule(s)...", len(to_download))
        try:
            earthaccess.download(to_download, local_path=local_dir)
        except Exception as e:
            logging.warning("Batch download raised %s; will continue with per-granule retries.", e)

    # Validate and per-granule retry
    for g, fpath in items:
        if fpath in ok_files:
            continue
        for attempt in range(1, options.retry_attempts + 1):
            if not fpath.exists():
                try:
                    earthaccess.download([g], local_path=local_dir)
                except Exception as e:
                    logging.warning("Download error on %s (attempt %d/%d): %s",
                                    fpath.name, attempt, options.retry_attempts, e)
            ok, why = validate_netcdf_file(fpath) if fpath.exists() else (False, "missing after download")
            if ok:
                logging.info("Validated: %s", fpath.name)
                ok_files.append(fpath)
                break
            else:
                logging.warning("Invalid NetCDF: %s — %s (attempt %d/%d)",
                                fpath.name, why, attempt, options.retry_attempts)
                try:
                    if fpath.exists():
                        fpath.unlink()
                except Exception as e:
                    logging.error("Failed to remove invalid file %s: %s", fpath, e)
                if attempt < options.retry_attempts:
                    time.sleep(2 * attempt)  # simple backoff
        else:
            # Exhausted attempts → quarantine
            dst = quarantine_dir / fpath.name
            try:
                if fpath.exists():
                    fpath.replace(dst)
                logging.error("Giving up on %s; moved to %s", fpath.name, dst)
            except Exception as e:
                logging.error("Could not quarantine %s: %s", fpath, e)
            bad_files.append(fpath)

    return ok_files, bad_files


if __name__ == "__main__":
    main()
