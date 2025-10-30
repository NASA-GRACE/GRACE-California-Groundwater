#!/usr/bin/env python3
"""
Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 Thinking (it/its), and GitHub Copilot (it/its).
Concatenate all netCDF files found under a folder (in subdirectories) into a single netCDF file.

Assumptions:
 - Files are named with extensions ".nc" or ".nc4"
 - Each file contains a "time" coordinate and the same set of data variables and dimensions
 - Searches recursively for input files.

"""

import os
from pathlib import Path
import glob
import argparse
import logging
import numpy as np
import xarray as xr
import datetime as dt
import re
import tqdm
from typing import Literal

import run_all as ra
from soil_moisture_download import validate_netcdf_integrity


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:          str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_in_dir:  Path = self.project_root / "input_data" / "soil_moisture" / self.soil_moisture_model / "data_individual"  # Also in soil_moisture_download.py
        self.default_out_dir: Path = self.project_root / "input_data" / "soil_moisture" / self.soil_moisture_model / "data_concatenated"
        # Attributes to collect (union across files) and storage
        self.attrs_to_collect = ["shortname", "title", "version", "doi", "reference", "websites", "history"]
        self.attr_values      = {k: set() for k in self.attrs_to_collect}  # filled during checks
        # Will hold finalized, sorted lists (set→list) after scanning all files:
        self.attr_lists = {}

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(
        description=("Concatenate all netCDF files under a folder into one file."),
        epilog=("Usage example:\n  python3 concatenate_netcdf.py /data/GLDAS_NOAH025 ./combined_output.nc\n"),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("in_dir", type=Path, nargs="?", default=options.default_in_dir,
                        help="Directory containing input .nc/.nc4 files.")
    parser.add_argument("out_dir", type=Path, nargs="?", default=options.default_out_dir,
                        help="Directory where output (.nc or .nc4) files will be written.")
    parser.add_argument("--full", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    options.args.in_dir.mkdir( parents=True, exist_ok=True)
    options.args.out_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Main function to process downloaded soil moisture files."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    if options.soil_moisture_model == "NLDAS":
        process_NLDAS_data(options)
    else:
        raise ValueError(f"Unsupported soil moisture model: {options.soil_moisture_model}")


def process_NLDAS_data(options: Options) -> None:
    """
    Process NLDAS soil moisture data: validate inputs, discover files,
    check consistency, concatenate, and save.

    Args:
        options: An Options instance with parsed arguments.

    Returns:
        None.

    Raises:
        Various exceptions if processing fails.
    """
    validate_inputs(           options)
    discover_files(            options)
    check_variable_consistency(options)
    check_time_continuity(     options)
    infer_model(               options)
    concatenate_and_save(      options)


def validate_inputs(options: Options) -> None:
    """
    Checks that in_dir exists. Creates out_dir if it doesn't exist.

    Args:
        options: An Options instance with parsed arguments.

    Returns:
        None. Updates options.in_dir and options.out_dir to resolved Paths.

    Raises:
        ValueError: If input directory does not exist.
    """
    if not options.args.in_dir.exists():
        raise ValueError(f"Input directory does not exist: {options.args.in_dir}")
    options.in_dir  = options.args.in_dir.resolve()
    options.out_dir = options.args.out_dir.resolve()
    options.out_dir.mkdir(parents=True, exist_ok=True)
    logging.info(f"Input  directory: {options.in_dir}")
    logging.info(f"Output directory: {options.out_dir}")


def _classify_temporal_resolution_and_prefix(fname: str | os.PathLike[str]) -> tuple[Literal["monthly", "daily", "hourly"], str]:
    """
    Inspect a single filename (basename only, no directory) and determine:
      - temporal resolution: "monthly", "daily", or "hourly"
      - the prefix portion of the filename *before* the date stamp

    Rules:
      monthly date looks like YYYYMM
      daily   date looks like YYYYMMDD
      hourly  date looks like YYYYMMDD.HHMM  (e.g. 20050103.1400)

    We always prefer the *most specific* match:
      hourly > daily > monthly
    
    Args:
        fname: Filename to classify.
    
    Returns:
        A tuple of (temporal_resolution, prefix_string).

    Raises:
      ValueError if we can't find any supported date pattern.
    """
    base = Path(fname).name  # just to be safe if we got a path

    # Hourly first: 20050103.1400
    hourly_regex = re.compile(
        r"^(?P<prefix>.*?)(?P<stamp>[12]\d{3}"
        r"(0[1-9]|1[0-2])"
        r"(0[1-9]|[12]\d|3[01])"
        r"\.(?:[01]\d|2[0-3])[0-5]\d)"
    )
    m = hourly_regex.search(base)
    if m:
        return "hourly", m.group("prefix")

    # Daily next: 20050103
    daily_regex = re.compile(
        r"^(?P<prefix>.*?)(?P<stamp>[12]\d{3}"
        r"(0[1-9]|1[0-2])"
        r"(0[1-9]|[12]\d|3[01]))"
    )
    m = daily_regex.search(base)
    if m:
        return "daily", m.group("prefix")

    # Monthly last: 200501
    monthly_regex = re.compile(
        r"^(?P<prefix>.*?)(?P<stamp>[12]\d{3}(0[1-9]|1[0-2]))"
    )
    m = monthly_regex.search(base)
    if m:
        return "monthly", m.group("prefix")

    raise ValueError(f"Could not infer temporal resolution/date stamp from filename: {fname}")


def _filter_files_by_pattern(filepaths: list[str | os.PathLike[str]]) -> list[str]:
    """
    Given a list of candidate NetCDF filepaths, choose the *most recent* file
    (by modification time on disk), infer that file's temporal resolution and
    its pre-date prefix, and then return ONLY the files that match BOTH:
      - same temporal resolution ("monthly" vs "daily" vs "hourly")
      - same prefix before the date

    Notes / edge cases handled:
      - If multiple files share the same mtime, max() will just pick one; that's fine.
      - We intentionally compare prefix strings *exactly* (no fuzzy matching).
      - If classification fails for the most recent file, we raise.
      - We do NOT check variable consistency here; that's done later.

    Raises:
      ValueError if input list is empty or classification fails.
    """
    if not filepaths:
        raise ValueError("No candidate .nc/.nc4 files were found to filter.")

    # Pick the most recent file by modification timestamp
    most_recent = max(filepaths, key=lambda p: Path(p).stat().st_mtime)

    temporal_res, wanted_prefix = _classify_temporal_resolution_and_prefix(Path(most_recent).name)

    logging.info(f"Most recent file: {most_recent}")
    logging.info(f"Inferred temporal resolution: {temporal_res}")
    logging.info(f"Inferred prefix: {wanted_prefix}")

    filtered = []
    for f in filepaths:
        try:
            this_res, this_prefix = _classify_temporal_resolution_and_prefix(Path(f).name)
        except ValueError:
            # skip files that don't even look like our YYYY.. pattern
            continue

        if this_res == temporal_res and this_prefix == wanted_prefix:
            filtered.append(f)

    if not filtered:
        raise ValueError(
            f"No files matched the temporal resolution '{temporal_res}' "
            f"and prefix '{wanted_prefix}' inferred from most recent file {most_recent}"
        )

    # We'll sort them for determinism (alphabetical by path, which for these filenames
    # usually implies chronological order if the date stamp is embedded).
    return sorted(filtered)


def discover_files(options: Options) -> None:
    """
    Populate options.in_files with all matching .nc/.nc4 files found recursively inside the in_dir.

    Args:
        options: An Options instance with parsed arguments. Contains:
        - in_dir: Directory to search for .nc/.nc4 files.
        - out_dir: Directory where output files will be written.

    Returns:
        None. Updates options.in_files with list of file paths.

    Raises:
        FileNotFoundError: If no .nc/.nc4 files are found.
        ValueError:        If duplicate, empty, non-netCDF, non-readable, or mismatched-extension files are found.
    """
    pattern = options.in_dir / "**" / "*.nc*"
    # Grab *all* .nc/.nc4-ish candidates
    all_candidates = glob.glob(str(pattern), recursive=True)

    if not all_candidates:
        raise FileNotFoundError(f"No .nc/.nc4 files found under {options.in_dir}")

    # Filter down to just the cohort we actually want to merge
    options.in_files = _filter_files_by_pattern(all_candidates)

    # Move "bad" files to this quarantine folder:
    quarantine = options.in_dir / "_quarantine_bad_netcdf"

    # Basic checks on the filtered list:

    # We'll iteratively build a cleaned list and quarantine any broken files.
    cleaned_files: list[str] = []

    # 1. Handle duplicates by keeping only the first occurrence.
    #    We'll iterate in order and skip repeats.
    seen: set[str] = set()

    for fpath in options.in_files:
        if fpath in seen:
            logging.warning("Duplicate file detected and skipped: %s", fpath)
            continue
        seen.add(fpath)

        p = Path(fpath)

        # 2. Check readability
        try:
            with p.open("r"):
                pass
        except (FileNotFoundError, PermissionError) as e:
            logging.warning("Unreadable file will be quarantined and skipped: %s (%s)", fpath, e)
            try:
                quarantine.mkdir(parents=True, exist_ok=True)
                p.replace(quarantine / p.name)
            except Exception as move_err:
                logging.warning("Failed to move unreadable file %s to quarantine: %s", fpath, move_err)
            continue  # don't keep this file

        # 3. Check empty file
        if p.stat().st_size == 0:
            logging.warning("Empty file will be quarantined and skipped: %s", fpath)
            try:
                quarantine.mkdir(parents=True, exist_ok=True)
                p.replace(quarantine / p.name)
            except Exception as move_err:
                logging.warning("Failed to move empty file %s to quarantine: %s", fpath, move_err)
            continue  # don't keep this file

        cleaned_files.append(fpath)

    # 4. Enforce uniform extension without raising:
    #    Determine the majority / first extension in cleaned_files, then drop mismatches.
    if not cleaned_files:
        raise ValueError("No valid input files remain after filtering, de-dup, and quarantine.")

    canonical_ext = Path(cleaned_files[0]).suffix
    really_cleaned: list[str] = []

    for fpath in cleaned_files:
        this_ext = Path(fpath).suffix
        if this_ext != canonical_ext:
            logging.warning(
                "File with mismatched extension skipped: %s (expected %s, got %s)",
                fpath, canonical_ext, this_ext
            )
            continue
        really_cleaned.append(fpath)

    if not really_cleaned:
        raise ValueError("All files were dropped due to extension mismatch; nothing to process.")

    # Update options.in_files to only the survivors
    options.in_files = really_cleaned
    options.ext      = canonical_ext

    logging.info(f"Loading {len(options.in_files)} files (filtered cohort).")
    for fpath in options.in_files:
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(f"  {Path(fpath).name}")

    bad_list = validate_netcdf_integrity(options.in_files, quarantine_dir=quarantine, strict=False)
    if bad_list:
        # bad_list is a list of (Path, reason)
        bad_paths = {str(p) for (p, _) in bad_list}  # ignore the "why" by setting it to "_"
        # Remove any quarantined/invalid files from our working set
        surviving = [f for f in options.in_files if f not in bad_paths]

        if len(surviving) != len(options.in_files):
            logging.warning("Skipping %d corrupt/invalid NetCDF files that were quarantined.",
                            len(options.in_files) - len(surviving))

        if not surviving:
            raise ValueError("All candidate NetCDF files were invalid/corrupt after quarantine; nothing left to process.")

        options.in_files = surviving


def infer_model(options: Options) -> None:
    """
    Infer the model name from the basenames of the options.in_files.

    Args:
        options: An Options instance with parsed arguments. Contains:
           - in_files: List of input file paths.

    Returns:
        None. Updates options.model with inferred model name.

    Raises:
        None.
    """
    # Look for the longest string that is common to all filenames
    options.model = os.path.commonprefix([Path(f).name for f in options.in_files])
    # If there is only one filename, its extension is still there. Remove it:
    options.model = Path(options.model).stem
    # Remove the date from the model name
    date_pattern = re.compile(r"(\d{4})(\d{2})(\d{2})?(\d{2})?(\d{2})?(\d{2})?")
    matches = []
    for fpath in options.in_files:
        match = date_pattern.search(Path(fpath).name)
        if match:
            matches.append(match.group(0))
    # Look for the longest common prefix of the matches
    if matches:
        common_date = os.path.commonprefix(matches)
        if common_date:
            # Remove the common date from the model name
            options.model = options.model.replace(common_date, "")
    logging.info("Model: %s", options.model)


def check_variable_consistency(options: Options, thetol: float = 1e-8) -> None:
    """
    Ensure all files share the same data variables, dimensions, and coordinate values.

    Args:
        options: An Options instance with parsed arguments. Contains:
           - in_files: List of input file paths.
           - out_dir: Directory where output files will be written.
        thetol:  Tolerance for comparing lat/lon values (default: 1e-8).

    Returns:
        None.

    Raises:
        ValueError: If any inconsistencies are found among the files.
    """
    first = options.in_files[0]
    with xr.open_dataset(first, decode_times=False) as ds0:
        vars0 = set(ds0.data_vars.keys())
        dims0 = set(ds0.sizes.keys())
        # Record canonical data vars and compute drop list (if any)
        options.all_data_vars = set(vars0)
        if getattr(options, "keep_these_soil_moisture_vars", None):
            requested = set(options.keep_these_soil_moisture_vars)
            missing = requested - options.all_data_vars
            if missing:
                raise ValueError(f"Requested vars not found in first file: {sorted(missing)}")
            options.vars_to_drop = sorted(options.all_data_vars - requested)
            logging.info(f"Keeping variables: {sorted(requested)}")
            logging.info(f"Dropping variables: {options.vars_to_drop}")
        else:
            options.vars_to_drop = None
        # Record the "canonical" lat/lon arrays from the first file
        ref_lats = ds0["lat"].values
        ref_lons = ds0["lon"].values

        # Store initial attributes from the first file
        for key in options.attrs_to_collect:
            val = ds0.attrs.get(key)
            if val is not None:
                if isinstance(val, (list, tuple, np.ndarray)):
                    options.attr_values[key].update(str(v) for v in val)
                else:
                    options.attr_values[key].add(str(val))

    for fpath in tqdm.tqdm(options.in_files[1:], desc="Checking files"):
        with xr.open_dataset(fpath, decode_times=False) as ds:
            # 1) Check variable names and dims as before:
            if set(ds.data_vars.keys()) != vars0:
                raise ValueError(f"Variable mismatch in {fpath}; does not match first file.")
            if set(ds.sizes.keys()) != dims0:
                raise ValueError(f"Dimension mismatch in {fpath}; does not match first file.")

            # 2) Check that lat/lon shapes match:
            lats = ds["lat"].values
            lons = ds["lon"].values
            if lats.shape != ref_lats.shape:
                raise ValueError(f"Latitude dimension length differs in {fpath} "
                                 f"({lats.shape} vs {ref_lats.shape})")
            if lons.shape != ref_lons.shape:
                raise ValueError(f"Longitude dimension length differs in {fpath} "
                                 f"({lons.shape} vs {ref_lons.shape})")

            # 3) Check that lat/lon values are identical OR detect reversed ordering:
            if np.allclose(lats, ref_lats, atol=thetol):
                pass  # same ordering as reference
            elif np.allclose(lats[::-1], ref_lats, atol=thetol):
                # lat is reversed relative to reference
                raise ValueError(f"Latitude in {fpath} runs descending relative to reference. "
                                 "You will need to flip or sort by 'lat'.")
            else:
                raise ValueError(f"Latitude values in {fpath} do not match the reference grid.")

            # 4) Collect global attributes:
            for key in options.attrs_to_collect:
                val = ds.attrs.get(key)
                if val is not None:
                    if isinstance(val, (list, tuple, np.ndarray)):
                        options.attr_values[key].update(str(v) for v in val)
                    else:
                        options.attr_values[key].add(str(val))

            if np.allclose(lons, ref_lons, atol=thetol):
                pass
            elif np.allclose(lons[::-1], ref_lons, atol=thetol):
                raise ValueError(f"Longitude in {fpath} runs reversed relative to reference. "
                                 "You may need to re‐index or shift longitudes.")
            else:
                raise ValueError(f"Longitude values in {fpath} do not match the reference grid.")
    
    #Finalize to sorted lists (only keep keys that have at least one value)
    options.attr_lists = {k: sorted(options.attr_values[k])
                          for k in options.attrs_to_collect
                          if options.attr_values[k]}


def check_time_continuity(options: Options) -> None:
    """
    Verify that files' time axes do not overlap (last of i < first of i+1). Raises if any overlap is detected.

    Args:
        options: An Options instance with parsed arguments. Contains:
           - in_files: List of input file paths.
           - out_dir: Directory where output files will be written.

    Returns:
        None.

    Raises:
        ValueError: If any time overlaps are detected among the files.
    """
    prev_end = None
    for fpath in tqdm.tqdm(options.in_files, desc="Checking time continuity"):
        with xr.open_dataset(fpath, decode_times=False) as ds:
            times = ds["time"].values
            start, end = times[0], times[-1]
        if prev_end is not None and prev_end >= start:
            raise ValueError(f"Time overlap detected: previous end {prev_end} >= start of {fpath} ({start})")
        prev_end = end


def get_datespan(options: Options, ds: xr.Dataset) -> None:
    """
    Build a YYYYMMDD_to_YYYYMMDD string from ds.time coordinate, store in options.datespan_string.

    Args:
        options: An Options instance to store the datespan string.
        ds:      An xarray Dataset with a time coordinate.

    Returns:
        None. Updates options.datespan_string.

    Raises:
        None.
    """
    times = ds.time.data

    def to_ym(dt64: np.datetime64) -> tuple[int, int, int]:
        """Convert a numpy datetime64 to (year, month, day) tuple."""
        y = int(dt64.astype("datetime64[Y]").astype(int)) + 1970
        m = int(dt64.astype("datetime64[M]").astype(int) % 12) + 1
        d = int(dt64.astype("datetime64[D]").astype(int) % 31) + 1
        return y, m, d

    y0, m0, d0 = to_ym(times[0])
    y1, m1, d1 = to_ym(times[-1])
    options.datespan_string = f"{y0}{m0:02d}{d0:02d}_to_{y1}{m1:02d}{d1:02d}"
    logging.info(f"Datespan: {options.datespan_string}")


def create_out_filepath(options: Options) -> None:
    """
    Create an output filename based on the model and datespan, store in options.out_filepath.

    Args:
        options: An Options instance with parsed arguments. Contains:
           - out_dir: Directory where output files will be written.
           - model:   Inferred model name.
           - datespan_string: String representing the date span.
           - ext:     File extension (e.g., .nc or .nc4).

    Returns:
        None. Updates options.out_filepath.

    Raises:
        None.
    """
    options.out_filepath = Path(options.out_dir) / f"{options.model}_{options.datespan_string}_created_on_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}{options.ext}"
    logging.info("Output file: %s", options.out_filepath)


def concatenate_and_save(options: Options) -> None:
    """
    Open, concatenate, and save the dataset. Cleans up a partial output file on failure.

    Args:
        options: An Options instance with parsed arguments. Contains:
           - in_files: List of input file paths.
           - out_dir: Directory where output files will be written.
           - model:   Inferred model name.
           - ext:     File extension (e.g., .nc or .nc4).

    Returns:
        None.

    Raises:
        FileNotFoundError, PermissionError, OSError, ValueError: If concatenation or saving fails.
    """
    logging.info("Opening and concatenating %d files...", len(options.in_files))
    open_kwargs = {}
    if getattr(options, "vars_to_drop", None):
        open_kwargs["drop_variables"] = options.vars_to_drop
    try:
        with xr.open_mfdataset(options.in_files, combine="by_coords", **open_kwargs) as ds:
            get_datespan(options, ds)
            # Write merged global attrs back to the concatenated dataset.
            # Always store as a list of strings (even if length==1).
            for key, values in getattr(options, "attr_lists", {}).items():
                ds.attrs[key] = list(values)
            ds.attrs["source_global_attrs_merge"] = "union across input files"
            out_path = Path(getattr(options, "out_filepath", create_out_filepath(options)))
            tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            ds.to_netcdf(tmp_path, engine="netcdf4")  # netCDF-4 handles list-of-strings attributes best.
        tmp_path.replace(out_path)
        logging.info("All files from %s combined into %s", options.model, out_path)
    except (FileNotFoundError, PermissionError, OSError, ValueError) as e:
        logging.exception("Failed to concatenate or save")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            logging.exception("Could not remove temporary file %s", tmp_path)
        raise  # Let caller decide whether to sys.exit


if __name__ == "__main__":
    main()
