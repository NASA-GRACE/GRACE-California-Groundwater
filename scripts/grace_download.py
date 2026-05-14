#!/usr/bin/env python3
# Written in 2026 by Emmy Killett (she/her), ChatGPT 5.2 Thinking (it/its), and GitHub Copilot (it/its).
# Purpose: Download GRACE/GRACE-FO JPL Mascon CRI (RL06.3 V04) data from PO.DAAC via earthaccess,
#          in the same style as soil_moisture_download.py.
#
# Dataset:
#   Short Name: TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4
#   DOI:        10.5067/TEMSC-3JC634
#   Concept ID: C3195527175-POCLOUD (optional, if you prefer concept_id search)
#
# Notes:
# - Requires Earthdata Login prerequisite files (.netrc, .urs_cookies), same as your NLDAS script.
# - Uses run_all.parse_datetime so you can pass "NOW" for end time.

from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import earthaccess
import requests
import run_all as ra

# Module-level constants for GRACE collection discovery
_GRACE_MASCON_PREFIX = "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL"
_GRACE_SHORT_NAME_RE = re.compile(
    r"^TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL"
    r"(?P<release_major>\d+)\.(?P<release_minor>\d+)"
    r"_V(?P<version>\d+)$"
)
_CMR_COLLECTIONS_URL = "https://cmr.earthdata.nasa.gov/search/collections.umm_json"


def parse_grace_short_name(short_name: str) -> tuple[tuple[int, int], int] | None:
    """Parse a GRACE short name into ((release_major, release_minor), version).

    Args:
        short_name: GRACE collection short name (e.g., "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4")

    Returns:
        Tuple of ((major, minor), version) if valid, None otherwise.

    Examples:
        >>> parse_grace_short_name("TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4")
        ((6, 3), 4)
        >>> parse_grace_short_name("TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL07.0_V1")
        ((7, 0), 1)
        >>> parse_grace_short_name("INVALID")
        None
    """
    match = _GRACE_SHORT_NAME_RE.match(short_name)
    if not match:
        return None

    major = int(match.group("release_major"))
    minor = int(match.group("release_minor"))
    version = int(match.group("version"))

    return ((major, minor), version)


def discover_latest_grace_collection(
    fallback_short_name: str,
    timeout: float = 30.0,
) -> tuple[str, str | None]:
    """Discover the latest GRACE Mascon CRI collection from CMR.

    Queries NASA's CMR for all GRACE Mascon CRI collections, parses versions,
    sorts by (release, version) descending, and verifies the top candidate has
    granules. Falls back to the provided default on any error.

    Args:
        fallback_short_name: Default collection short name to use if discovery fails
        timeout: HTTP request timeout in seconds (default: 30.0)

    Returns:
        Tuple of (short_name, doi_or_none) - the best collection found, or fallback
    """
    try:
        # Query CMR for all matching collections
        params = {
            "provider": "POCLOUD",
            "ShortName": f"{_GRACE_MASCON_PREFIX}*",
            "options[ShortName][pattern]": "true",
            "page_size": 50,
        }

        logging.debug("Querying CMR for GRACE collections: %s", params)
        response = requests.get(_CMR_COLLECTIONS_URL, params=params, timeout=timeout)
        response.raise_for_status()

        data = response.json()
        items = data.get("items", [])

        if not items:
            logging.warning("GRACE collection discovery: CMR returned 0 results. Using fallback: %s", fallback_short_name)
            return (fallback_short_name, None)

        # Parse and sort candidates
        candidates: list[tuple[tuple[tuple[int, int], int], str, str | None]] = []
        for item in items:
            umm = item.get("umm", {})
            short_name = umm.get("ShortName", "")
            parsed = parse_grace_short_name(short_name)

            if parsed is None:
                logging.debug("Skipping unparseable collection: %s", short_name)
                continue

            # Extract DOI if present
            doi_obj = umm.get("DOI")
            doi = doi_obj.get("DOI") if doi_obj else None

            candidates.append((parsed, short_name, doi))

        if not candidates:
            logging.warning("GRACE collection discovery: No parseable collections found. Using fallback: %s", fallback_short_name)
            return (fallback_short_name, None)

        # Sort by (release, version) descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        logging.debug("GRACE collection discovery: found %d candidate(s)", len(candidates))

        # Verify candidates have granules (try from best to worst)
        for parsed_version, short_name, doi in candidates:
            try:
                # Check if collection has any granules
                logging.debug("Verifying granules for: %s", short_name)
                granules = earthaccess.search_data(short_name=short_name, count=1)
                if granules:
                    logging.info("GRACE collection discovery: Selected %s (release %s.%s, version %s)",
                                short_name, parsed_version[0][0], parsed_version[0][1], parsed_version[1])
                    return (short_name, doi)
                else:
                    logging.debug("Skipping empty collection: %s", short_name)
            except Exception as e:
                # On granule verification error, treat as valid (optimistic)
                # The download step will surface any real issues
                logging.debug("Granule check failed for %s: %s. Treating as valid.", short_name, e)
                return (short_name, doi)

        # All candidates were empty
        logging.warning("GRACE collection discovery: All candidates have no granules. Using fallback: %s", fallback_short_name)
        return (fallback_short_name, None)

    except Exception as e:
        logging.warning("GRACE collection discovery failed: %s. Using fallback: %s", e, fallback_short_name)
        return (fallback_short_name, None)


class Options(ra.Options):
    """Global options (inherits your run_all.Options) + GRACE-specific defaults."""

    def __init__(self) -> None:
        super().__init__()

        self.my_name: str = Path(__file__).stem

        # PO.DAAC JPL Mascon CRI RL06.3 Version 04
        self.default_short_name: str = "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4"
        self.default_doi:        str = "10.5067/TEMSC-3JC634"

        # The manual CLI example you gave starts at 2002-04-04; the dataset page lists 2002-Apr-04.
        # We'll use that as the GRACE "full" start, independent of run_all.Options.full_start.
        self.grace_full_start: str = "2002-04-04T00:00:00Z"
        self.grace_full_end:   str = "NOW"

        self.default_timespan: tuple[str, str] = (self.test_start,       self.test_end)
        self.full_timespan:    tuple[str, str] = (self.grace_full_start, self.grace_full_end)

        # Default download target: your existing grace_dir
        self.default_local_dir: Path = self.grace_dir

        # GRACE is global; region is typically irrelevant, but keep the interface consistent
        self.default_region: tuple[float, float, float, float] = (-180, -90, 180, 90)

        self.retry_attempts: int = 3


def parse_arguments(options: Options) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download GRACE/GRACE-FO JPL Mascon CRI (RL06.3 V04) from PO.DAAC using earthaccess.\n"
            "Supports 'NOW' for end date via run_all.parse_datetime.\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--doi",
        type=str,
        default=options.default_doi,
        help=f"Dataset DOI for earthaccess.search_data (default: {options.default_doi})",
    )
    src.add_argument(
        "--collection",
        "--short_name",
        dest="short_name",
        type=str,
        default=None,
        help=(
            "PO.DAAC collection short name (alias: --collection). "
            f"Example: {options.default_short_name}"
        ),
    )
    src.add_argument(
        "--concept_id",
        type=str,
        default=None,
        help="CMR concept-id (e.g., C3195527175-POCLOUD). If set, overrides doi/short_name.",
    )

    parser.add_argument(
        "--timespan",
        type=str,
        nargs=2,
        default=options.default_timespan,
        help=(
            "Timespan as two dates/datetimes. Accepts NOW.\n"
            "Examples:\n"
            "  --timespan 2002-04-04T00:00:00Z NOW\n"
            "  --timespan 2005-01-01 2005-03-31T23:59:59\n"
            f"(default: {' '.join(options.default_timespan)})"
        ),
    )
    parser.add_argument(
        "--region",
        type=float,
        nargs=4,
        default=options.default_region,
        help=(
            "Optional region as four floats: west south east north.\n"
            f"(default: {' '.join(map(str, options.default_region))})"
        ),
    )
    parser.add_argument(
        "--local_dir",
        type=Path,
        default=options.default_local_dir,
        help=f"Local directory to download files to (default: '{options.default_local_dir}').",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help=f"If set, download the full GRACE timespan ({options.full_timespan[0]} - {options.full_timespan[1]}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="If set, delete existing matching files before downloading (useful if you suspect staleness).",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Debug logging.",
    )

    options.args = parser.parse_args()

    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    if getattr(options.args, "full", False):
        options.args.timespan = options.full_timespan

    options.args.local_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    options = Options()
    parse_arguments(options)
    logging.basicConfig(
        level=options.log_mode,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Login early - needed for both discovery and download
    logging.info("Logging in to Earthdata via earthaccess...")
    earthaccess.login()

    # Auto-discover latest collection if user didn't specify a source
    user_specified_source = (
        options.args.short_name is not None
        or options.args.concept_id is not None
    )
    if not user_specified_source:
        discovered_name, discovered_doi = discover_latest_grace_collection(
            fallback_short_name=options.default_short_name,
        )
        options.args.short_name = discovered_name
        if discovered_doi:
            options.args.doi = discovered_doi

    download_grace_data(options)


def download_grace_data(options: Options) -> None:
    start_dt, end_dt = validate_inputs(options)

    # Build search args for earthaccess.search_data
    search_kwargs = dict(
        temporal=(to_cmr_iso(start_dt), to_cmr_iso(end_dt)),
        bounding_box=tuple(options.args.region),
        count=-1,  # "all" (earthaccess supports count; -1 returns all)
    )

    if options.args.concept_id:
        search_kwargs["concept_id"] = options.args.concept_id
        logging.info("Searching granules by concept_id=%s", options.args.concept_id)
    elif options.args.short_name:
        search_kwargs["short_name"] = options.args.short_name
        logging.info("Searching granules by short_name=%s", options.args.short_name)
    else:
        search_kwargs["doi"] = options.args.doi
        logging.info("Searching granules by doi=%s", options.args.doi)

    results = _search_data_with_retries(num_retries=5, **search_kwargs)

    if not results:
        raise RuntimeError("No granules found for the specified search criteria.")

    logging.info("Found %d granule(s). Downloading to %s", len(results), options.args.local_dir)

    ok_files, bad_files = _download_with_validation_and_retry(options, results)
    logging.info("Valid files: %d", len(ok_files))
    if bad_files:
        logging.warning("Unusable/quarantined files: %d", len(bad_files))
    else:
        logging.info("All downloads validated successfully.")


def validate_inputs(options: Options) -> tuple[dt.datetime, dt.datetime]:
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

    logging.info("Local directory: %s", options.args.local_dir)
    logging.info(
        "Timespan:\nStart: %s\n  End: %s",
        start_dt.strftime("%Y-%m-%d %H:%M:%S%z"),
        end_dt.strftime("%Y-%m-%d %H:%M:%S%z"),
    )
    logging.info("Region: %s", options.args.region)
    if options.args.concept_id:
        logging.info("Source: concept_id=%s", options.args.concept_id)
    elif options.args.short_name:
        logging.info("Source: short_name=%s", options.args.short_name)
    else:
        logging.info("Source: doi=%s", options.args.doi)

    return start_dt, end_dt


def to_cmr_iso(t: dt.datetime) -> str:
    """CMR-friendly ISO (UTC, no microseconds, trailing Z)."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    u = t.astimezone(dt.timezone.utc).replace(microsecond=0)
    return u.isoformat().replace("+00:00", "Z")


def _search_data_with_retries(
    num_retries: int = 5,
    initial_delay: float = 1.0,
    backoff: float = 2.0,
    **search_kwargs,
):
    delay = initial_delay
    last_exc = None
    for attempt in range(1, num_retries + 1):
        try:
            logging.info("Searching for data (attempt %d/%d)...", attempt, num_retries)
            return earthaccess.search_data(**search_kwargs)
        except RuntimeError as e:
            msg = str(e)
            transient = any(code in msg for code in ("Internal Error", " 500 ", " 502 ", " 503 ", " 504 "))
            if not transient:
                raise
            logging.warning("Transient CMR error on attempt %d: %s", attempt, msg.strip())
            last_exc = e
            if attempt < num_retries:
                time.sleep(delay)
                delay *= backoff
            else:
                break
    raise last_exc


# ---- Validation helpers (NetCDF-focused, but safe for non-NetCDF too) ----

_NETCDF_SUFFIXES = {".nc", ".nc4", ".h5", ".hdf5"}


def _looks_like_netcdf(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
        return head.startswith(b"\x89HDF\r\n\x1a\n") or head.startswith(b"CDF\x01") or head.startswith(b"CDF\x02")
    except Exception:
        return False


def _openable_by_xarray(path: Path) -> tuple[bool, str]:
    try:
        import xarray as xr
        with xr.open_dataset(path, engine="netcdf4", decode_times=False) as ds:
            _ = list(ds.variables)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def validate_file(path: Path) -> tuple[bool, str]:
    path = Path(path)
    if not path.exists():
        return False, "File does not exist"
    if path.stat().st_size == 0:
        return False, "File is empty (size == 0 bytes)"

    # If it looks like a NetCDF-ish artifact, do stronger checks
    if path.suffix.lower() in _NETCDF_SUFFIXES:
        if not _looks_like_netcdf(path):
            return False, "Bad magic bytes (not NetCDF/HDF)"
        ok, why = _openable_by_xarray(path)
        if not ok:
            return False, why

    return True, ""


def _granule_expected_filename(granule) -> str:
    try:
        links = granule.data_links()
    except Exception:
        links = []
    https = next((u for u in links if u.lower().startswith("http")), links[0] if links else None)
    if not https:
        raise ValueError("Granule has no downloadable HTTP(S) data link")
    return Path(urlparse(https).path).name


def _download_with_validation_and_retry(options: Options, results) -> tuple[list[Path], list[Path]]:
    local_dir = Path(options.args.local_dir)
    quarantine_dir = local_dir / "_quarantine_bad_files"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    # Map granules to intended paths
    items: list[tuple[object, Path]] = []
    for g in results:
        try:
            name = _granule_expected_filename(g)
            items.append((g, local_dir / name))
        except Exception as e:
            logging.error("Skipping granule with no usable data link: %s", e)

    ok_files: list[Path] = []
    bad_files: list[Path] = []
    to_download: list[object] = []

    # Pre-check existing files
    for g, fpath in items:
        if fpath.exists() and options.args.force:
            logging.info("Force mode: deleting existing %s", fpath.name)
            try:
                fpath.unlink()
            except Exception as e:
                logging.error("Failed to delete %s: %s", fpath, e)

        if fpath.exists():
            ok, why = validate_file(fpath)
            if ok:
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

    # Batch download missing
    if to_download:
        logging.info("Downloading %d missing granule(s)...", len(to_download))
        try:
            earthaccess.download(to_download, local_path=local_dir)
        except Exception as e:
            logging.warning("Batch download raised %s; continuing with per-granule retries.", e)

    # Validate + retry per granule
    for g, fpath in items:
        if fpath in ok_files:
            continue

        for attempt in range(1, options.retry_attempts + 1):
            if not fpath.exists():
                try:
                    earthaccess.download([g], local_path=local_dir)
                except Exception as e:
                    logging.warning("Download error on %s (attempt %d/%d): %s", fpath.name, attempt, options.retry_attempts, e)

            ok, why = validate_file(fpath) if fpath.exists() else (False, "missing after download")
            if ok:
                logging.info("Validated: %s", fpath.name)
                ok_files.append(fpath)
                break

            logging.warning("Invalid file: %s — %s (attempt %d/%d)", fpath.name, why, attempt, options.retry_attempts)
            try:
                if fpath.exists():
                    fpath.unlink()
            except Exception as e:
                logging.error("Failed to remove invalid file %s: %s", fpath, e)

            if attempt < options.retry_attempts:
                time.sleep(2 * attempt)

        else:
            # Exhausted attempts -> quarantine
            dst = quarantine_dir / fpath.name
            try:
                if fpath.exists():
                    shutil.move(str(fpath), str(dst))
                logging.error("Giving up on %s; moved to %s", fpath.name, dst)
            except Exception as e:
                logging.error("Could not quarantine %s: %s", fpath, e)
            bad_files.append(fpath)

    return ok_files, bad_files


if __name__ == "__main__":
    main()
