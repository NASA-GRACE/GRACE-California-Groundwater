#!/usr/bin/env python3
# Written in 2025/2026 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), GitHub Copilot (it/its), and Claude Opus 4.6 extended (it/its).
from __future__ import annotations  # For Python 3.7+ compatibility with type annotations

import os
import sys
from pathlib import Path
import argparse
import subprocess
import shlex
import logging
from typing import TypeAlias
import re  # Used to precompile regexes for performance
import datetime as dt

# This is the version of python which should be used in scripts that import this module.
PY_VERSION = 3.11


class Options:
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with default values."""
        self.script_dir:              Path = Path(__file__).resolve().parent  # Figure out where this file lives on disk
        self.project_root:            Path = self.script_dir.parent           # Project root is one level above script_dir
        self.test_start:               str = "2005-01-01"                     # Quick test timespan start
        self.test_end:                 str = "2005-03-31T23:59:59"            # Quick test timespan end
        self.baseline_start:           str = "2004-01-01"                     # Start of baseline calibration period
        self.baseline_end:             str = "2009-12-31"                     # End   of baseline calibration period
        self.full_start:               str = "2004-01-01"                     # Start of full timeseries
        self.full_end:                 str = "NOW"                            # End   of full timeseries is current date/time
        self.soil_moisture_model:      str = "NLDAS"
        self.swe_model:                str = "SNODAS"
        self.reservoirs_model:         str = "CDEC"
        self.datatypes:          list[str] = ["GRACE",
                                              self.soil_moisture_model,
                                              self.swe_model,
                                              self.reservoirs_model,
                                              "Groundwater"]

        self.valid_basins:                  list[str] = ["California", "Sacramento", "San Joaquin", "Tulare-Buena Vista Lakes"]
        self.default_basin:                       str = self.valid_basins[0]

        self.keep_these_soil_moisture_vars: list[str] = ["SoilM_0_100cm"]  # if you want to keep all soil moisture vars, this should be []

        self.digits_after_decimal:                int = 3  # Number of digits after decimal point in output CSV files

        self.volume_units_text:     str = "km^3"                                               # Units for volume in output CSV files
        self.volume_units_pretty:   str = "km³"                                                # Units for volume in plots
        self.volume_description:    str = f"water volume ({self.volume_units_text})"           # Description for volume in output CSV files
        self.thickness_units:       str = "mm"                                                 # Units for thickness in output CSV files and plots
        self.thickness_description: str = f"water equivalent height ({self.thickness_units})"  # Description for thickness in output CSV files and plots
        self.area_units_text:       str = "km^2"                                               # Units for area in output CSV files
        self.area_units_pretty:     str = "km²"                                                # Units for area in plots
        self.area_description:      str = f"area ({self.area_units_text})"                     # Description for area in output CSV files
        self.area_m2_scale:       float = 1.0e-6                                               # Use 1.0 for m^2, 1e-6 for km^2, etc.

        self.swe_dir:           Path = self.project_root / "input_data"    / "snow_water_equivalent" / self.swe_model
        self.soil_moisture_dir: Path = self.project_root / "input_data"    / "soil_moisture"         / self.soil_moisture_model
        self.reservoirs_dir:    Path = self.project_root / "input_data"    / "reservoirs"            / self.reservoirs_model
        self.grace_dir:         Path = self.project_root / "input_data"    / "grace_tws"
        self.timeseries_dir:    Path = self.project_root / "input_data"    / "masked_timeseries"
        self.output_dir:        Path = self.project_root / "output"
        self.output_dir_gw_tws: Path = self.project_root / "output_combined"
        self.graphics_dir:      Path = self.project_root / "graphics"
        self.swe_dir.mkdir(          parents=True, exist_ok=True)
        self.soil_moisture_dir.mkdir(parents=True, exist_ok=True)
        self.reservoirs_dir.mkdir(   parents=True, exist_ok=True)
        self.grace_dir.mkdir(        parents=True, exist_ok=True)
        self.timeseries_dir.mkdir(   parents=True, exist_ok=True)
        self.output_dir.mkdir(       parents=True, exist_ok=True)
        self.output_dir_gw_tws.mkdir(parents=True, exist_ok=True)        
        self.graphics_dir.mkdir(     parents=True, exist_ok=True)
        self.swe_url_prefix:        str = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked"
        self.reservoirs_base_url:   str = "https://cdec.water.ca.gov/dynamicapp/req/CSVDataServlet"  # CDEC base URL for CSV data
        # Reservoirs sensor ID for storage in Acre-Feet (specific to CDEC dataset)
        self.storage_sensor_af:     str = "15"  # Primary sensor for storage
        self.alt_storage_sensor_af: str = "69"  # Alternative sensor, often for more current daily
        self.reservoirs_url_prefix: str = f"{self.reservoirs_base_url}?Stations=<station_id>&SensorNums=<storage or alt storage sensor>&dur_code=M&Start=YYYY-MM-DD&End=YYYY-MM-DD"

        self.log_mode:              int = logging.INFO  # Use the --debug command line argument to change to DEBUG.
        self.separator_line:        str = "-" * 60      # A line of dashes for logging separation

        # Generate safe names for basins (no spaces or special characters) and dictionaries for mapping between them.
        self.basin_safenames:           list[str] = [safestring(title) for title in self.valid_basins]
        # key = basin name,      value = safe basin name
        self.basin_safename_map:   dict[str, str] = dict(zip(self.valid_basins, self.basin_safenames))
        # key = safe basin name, value = basin name
        self.reverse_safename_map: dict[str, str] = {v: k for k, v in self.basin_safename_map.items()}

        if self.default_basin not in self.valid_basins:
            raise ValueError(f"In {Path(__file__).name}, default basin '{self.default_basin}' specified in Options.__init__() is not in the list of valid basins: {self.valid_basins}")

        self.default_basin_safename = self.basin_safename_map[self.default_basin]

    def format_area(self, value: float) -> str:
            """Format an area value with precision appropriate to the current units."""
            return f"{value:.0f}" if self.area_units_text == "m^2" else f"{value:.3f}"


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Run all processing scripts in order.")
    parser.add_argument("--dry_run", action="store_true",
                        help="If set, print commands without executing them")
    parser.add_argument("--full", action="store_true",
                        help=f"If set, download the full timespan ({options.full_start} - {options.full_end}).")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run all programs in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG


def main() -> None:
    """Run all the processing scripts in order."""
    options = Options()
    logging.basicConfig(level=options.log_mode, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    run_all_start_time = dt.datetime.now()
    logging.info(f"Starting {Path(__file__).name} at {run_all_start_time.isoformat()}")

    parse_arguments(options)

    section_header(options, "Processing soil moisture data")

    logging.info("Download soil moisture data files.")
    run_script(options, "soil_moisture_download.py")

    logging.info("If necessary, process the downloaded soil moisture files into a single NetCDF file.")
    run_script(options, "soil_moisture_process.py")

    logging.info("Create and save a soil moisture mask for the basin of interest.")
    run_script(options, "soil_moisture_create_mask.py")

    logging.info("Apply the mask to the processed soil moisture data, extract time series "
                 "for the basin, then save as CSV and NetCDF files.")
    run_script(options, "soil_moisture_mask_timeseries.py")

    logging.info("Generate a time series plot of the CSV file (and optionally, a movie of "
                 "the masked NetCDF file)")
    run_script(options, "soil_moisture_map_fields.py")

    logging.info("Generate a time series plot of the masked soil moisture data.")
    run_script(options, "plot_timeseries.py")

    section_header(options, "Processing reservoirs storage data")

    logging.info(f"Downloading reservoirs data...")
    run_script(options, "reservoirs_download.py")

    logging.info("Processing reservoirs data into monthly sums...")
    run_script(options, "reservoirs_monthly_sums.py")

    logging.info("Generating reservoirs anomaly and error value time series...")
    run_script(options, "reservoirs_regional_anomaly_mean_err_vals.py")

    logging.info("Generate a time series plot of the masked reservoirs data.")
    run_script(options, "plot_timeseries.py")

    section_header(options, "Processing GRACE TWS data")

    logging.info("Downloading GRACE/GRACE-FO Mascon TWS data from PO.DAAC...")
    run_script(options, "grace_download.py")

    logging.info("Call raster mask generator for GRACE TWS data...")
    run_script(options, "call_raster_mask_generator.py")

    logging.info("Generating GRACE TWS anomaly time series...")
    run_script(options, "grace_tws_anomaly.py")

    logging.info("Interpolating GRACE TWS data to mid-month timestamps...")
    run_script(options, "interpolate_grace.py")

    logging.info("Generate a time series plot of the masked GRACE data.")
    run_script(options, "plot_timeseries.py")

    section_header(options, "Processing SNODAS snow water equivalent data")

    logging.info("Downloading snow water equivalent (SWE) data...")
    run_script(options, "swe_daily_downloader_and_monthly_mean.py")

    logging.info("Call raster mask generator for snow water equivalent (SWE) data...")
    run_script(options, "call_raster_mask_generator.py", flags=["--target_dataset", "swe"])

    logging.info("Processing snow water equivalent (SWE) data into monthly anomalies...")
    run_script(options, "swe_monthly_anomaly.py")

    logging.info("Generate a time series plot of the masked snow water equivalent (SWE) data.")
    run_script(options, "plot_timeseries.py")

    section_header(options, "Computing groundwater anomaly and plotting results")
    
    logging.info("Computing groundwater anomaly time series...")
    run_script(options, "compute_groundwater.py")

    logging.info("Generating comparison plots of all water storage components...")
    run_script(options, "plot_timeseries.py", flags=["--groundwater"])

    run_all_end_time = dt.datetime.now()
    logging.info(f"Finished {Path(__file__).name} at {run_all_end_time.isoformat()}.")
    total_duration = run_all_end_time - run_all_start_time
    logging.info(f"Total duration: {total_duration}.")


def run_script(options: Options, the_script: str, flags: list[str] | None = None) -> None:
    """
    Run a script with the given options.

    Args:
        options:    An Options instance with global options.
        the_script: The script filename to run (e.g., 'soil_moisture_download.py').
        flags:      Optional flags to pass to the script.

    Returns:
        None. The specified script is executed as a subprocess.

    Raises:
        subprocess.CalledProcessError: If the called script returns a non-zero exit status.
    """
    logging.info(options.separator_line)
    if flags is None:
        flags = []
    if getattr(options.args, "debug", False):
        flags.append("--debug")
    if getattr(options.args, "full", False):
        flags.append("--full")
    script_path = os.fspath(options.script_dir / the_script)
    # If venv is not available, use sys.executable
    venv_python = options.project_root / "scripts" / ".venv" / "bin" / "python"
    if venv_python.is_file():
        logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Using virtual environment python at {venv_python}")
        chosen_python = str(venv_python)
    else:
        logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Virtual environment python not found at {venv_python}, using system python at {sys.executable}")
        chosen_python = sys.executable
    the_command = [chosen_python, script_path] + flags
    command_str = ' '.join(shlex.quote(arg) for arg in the_command)
    if options.args.dry_run:
        logging.info(f"Dry run mode: would run: {command_str}")
        return
    else:
        logging.info(f"Running: {command_str}")
        subprocess.run(the_command, check=True)


def section_header(options: Options, title: str) -> None:
    """Print a section header for logging."""
    logging.info(options.separator_line)
    logging.info(title)
    logging.info(options.separator_line)


# The following are utility functions and classes that can be imported into other scripts.

DT: TypeAlias = dt.date | dt.datetime | str  # date, datetime, or date string (ISO-format, YYYY-MM-DD, anything that parse_datetime() accepts)


def compute_baseline(actual_start: DT,
                     actual_end:   DT,
                     base_start:   DT,
                     base_end:     DT) -> tuple[dt.datetime, dt.datetime]:
    """
    Return a baseline interval that:
      1) If there is an intersection between [base_start, base_end] and
         [actual_start, actual_end], returns that intersection.
      2) Otherwise, starts at actual_start and has duration no longer than
         the requested baseline's duration, but never extends past actual_end.

    Assumes all inputs are either 'date' or 'datetime' (and of the same type).
    Uses closed intervals (start <= t <= end) when checking overlap and length
    defined by simple subtraction (end - start).

    Args:
        actual_start: The start of the actual   time series.
        actual_end:   The end   of the actual   time series.
        base_start:   The start of the baseline time series.
        base_end:     The end   of the baseline time series.

    Returns:
        A tuple (start, end) representing the computed baseline interval.

    Raises:
        ValueError: If actual_start is greater than actual_end or base_start is greater than base_end.
        TypeError:  If the types of actual_start, actual_end, base_start, and base_end are not consistent.
    """
    actual_start = parse_datetime(actual_start, timezone="Naive")
    actual_end   = parse_datetime(actual_end,   timezone="Naive")
    base_start   = parse_datetime(base_start,   timezone="Naive")
    base_end     = parse_datetime(base_end,     timezone="Naive")

    if actual_start > actual_end:
        raise ValueError("actual_start must be <= actual_end")
    if base_start > base_end:
        raise ValueError("base_start must be <= base_end")

    # Intersection
    inter_start = max(base_start, actual_start)
    inter_end   = min(base_end,   actual_end)
    if inter_start <= inter_end:
        return inter_start, inter_end

    # No intersection: size capped to baseline duration, clipped to actual window
    baseline_span: dt.timedelta = base_end - base_start  # timedelta (>= 0 by earlier check)
    # Start at the beginning of the actual series
    start = actual_start
    # End is at most start + baseline_span, but never after actual_end
    end = min(start + baseline_span, actual_end)
    return start, end


def rasterize_shapefile_to_mask(shapefile:   str | os.PathLike[str],
                                region_name: str,
                                gt:     tuple[float, float, float, float, float, float],
                                n_lon:  int,
                                n_lat:  int,
                                select: dict[str, object] | None = None) -> tuple[np.ndarray, list[float]]:
    """
    Open a shapefile, select a single polygon feature for 'region_name', and rasterize it
    to a byte mask on the provided geotransform/grid.
    Based on code written by Munish Sikka and ChatGPT, which was based on an
    original function provided by Jack McNelis.

    Args:
        shapefile:    Path to the ESRI Shapefile (.shp).
        region_name:  Region/basin name to select (case-insensitive compare).
        gt:           GDAL geotransform tuple for the *target* grid (origin at NW corner).
        n_lon, n_lat: Output raster width/height (x,y).
        select:       Optional selection hints:
            {
              "filter_sort": int,        # used for California in HYBAS (field SORT)
              "layer_name": str,         # used for Colorado river basin (field WMOBB_NAME)
              "field_name": str          # default field to match region_name (default: "name")
            }

    Returns:
        (mask_array, bbox) where:
            mask_array is (n_lat, n_lon) with values {0,1}
            bbox is [minx, miny, maxx, maxy] of the chosen feature.

    Raises:
        FileNotFoundError if the shapefile cannot be opened.
        RuntimeError if a matching feature cannot be found.
    """
    import numpy as np
    from osgeo import ogr, gdal

    gdal.UseExceptions()

    shapefile = ensure_path_is_a_file(shapefile, raise_on_empty=True)
    region_name_casefolded = region_name.casefold()

    driver = ogr.GetDriverByName("ESRI Shapefile")
    shp    = driver.Open(os.fspath(shapefile), 0)
    if shp is None:
        raise FileNotFoundError(f"Could not open {os.fspath(shapefile)}")

    lyr  = shp.GetLayer()
    ssrs = lyr.GetSpatialRef()
    wkt  = ssrs.ExportToPrettyWkt() if ssrs is not None else ""

    # Selection strategy
    sel           = select or {}
    filter_sort   = sel.get("filter_sort")
    layer_name    = sel.get("layer_name")
    default_field = (sel.get("field_name") or "name").strip()

    chosen_index  = None
    for i, feat in enumerate(lyr):
        # Special-case: California by SORT
        if region_name_casefolded in ("ca", "california"):
            if filter_sort is not None and feat.GetField("SORT") == filter_sort:
                chosen_index = i
                break
        # Special-case: "Colorado river basin" by WMOBB_NAME
        elif region_name_casefolded == "colorado river basin":
            if layer_name is not None and feat.GetField("WMOBB_NAME") == layer_name:
                chosen_index = i
                break
        else:
            # Default: match by named field (usually "name"), case-insensitive
            fld_val = feat.GetField(default_field)
            if isinstance(fld_val, str) and fld_val.casefold() == region_name_casefolded:
                chosen_index = i
                break

    if chosen_index is None:
        raise RuntimeError(
            f"No feature matched region '{region_name}' in {os.fspath(shapefile)} "
            f"(select hints: filter_sort={filter_sort}, layer_name={layer_name}, field={default_field})."
        )

    feat    = lyr.GetFeature(chosen_index)
    geom    = feat.GetGeometryRef()
    geojson = geom.ExportToJson()

    # Build an in-memory single-feature layer
    mem_drv = ogr.GetDriverByName("MEM")
    featds  = mem_drv.CreateDataSource("MemoryDataset")
    newlyr  = featds.CreateLayer("selected", ssrs, geom_type=ogr.wkbPolygon)
    lyrid   = ogr.FieldDefn("ID", ogr.OFTInteger)
    newlyr.CreateField(lyrid)

    lyrdefn = newlyr.GetLayerDefn()
    newfeat = ogr.Feature(lyrdefn)
    newgeom = ogr.CreateGeometryFromJson(geojson)
    newfeat.SetGeometry(newgeom)
    newfeat.SetField("ID", 1)
    newlyr.CreateFeature(newfeat)
    newfeat = None

    # Create output raster mask in memory
    mask = gdal.GetDriverByName("MEM").Create("", n_lon, n_lat, 1, gdal.GDT_Byte)
    mask.SetGeoTransform(gt)
    if wkt:
        mask.SetProjection(wkt)
    band = mask.GetRasterBand(1)
    band.Fill(0)
    band.SetNoDataValue(0)

    gdal.RasterizeLayer(mask, [1], newlyr, burn_values=[1])
    mask.FlushCache()

    marr = mask.GetRasterBand(1).ReadAsArray()
    env  = geom.GetEnvelope()
    bbox = [env[0], env[2], env[1], env[3]]

    logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug("Rasterized mask created: shape=(%d, %d)", n_lat, n_lon)
    return marr, bbox


def ensure_path_is_a_file(path: str | os.PathLike[str], raise_on_empty: bool = False) -> Path:
    """
    Ensure that the given path is an existing file and return it as a Path object.

    Args:
        path:           The path to check.
        raise_on_empty: If True, raise an exception if the file is empty.

    Returns:
        A Path object representing the file.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    p = Path(path).resolve(strict=True)
    if not p.is_file():
        raise IsADirectoryError(f"Expected a file, got directory: {p}")
    if p.stat().st_size == 0:
        if raise_on_empty:
            raise ValueError(f"File is empty: {p}")
        else:
            logging.warning("File is empty: %s", p)
    return p


class PlotOptions(Options):
    """Global figure options."""

    def __init__(self) -> None:
        """Initialize PlotOptions class with values from the Options class, and default plotting values."""
        super().__init__()
        self.myfigsize   = (16, 9)
        self.fsize       = 24
        self.dpi_choice  = 300
        # keep immutable "base" palettes so we can recompute safely
        self._base_colors      = ['black', 'red',    'blue',      'green',      'purple']
        self._base_lightcolors = ['grey',  'pink',   'lightblue', 'lightgreen', 'lightpurple']
        self.markers           = ['o',     's',      '^',         'v',          '<',          '>']
        self.linestyles        = ['solid', 'dashed', 'dashdot',   'dotted']

        self._dark_mode = False   # backing store
        self._apply_theme()       # derive palettes/background/text from _dark_mode

    @property
    def dark_mode(self) -> bool:
        """This is a property, so setting it will also update the theme."""
        return self._dark_mode

    @dark_mode.setter
    def dark_mode(self, value: int | bool) -> None:
        """This is a property with a setter, so any child class that changes self.dark_mode will also update the theme."""
        self._dark_mode = bool(value)
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Apply the current theme (light or dark) to the plot options."""
        if self._dark_mode:
            self.background_color = '#000000'
            self.text_color       = '#FFFFFF'
            # recompute "view" palettes from the bases
            self.colors      = [ ('darkgrey' if  c == 'black' else c) for c in self._base_colors ]
            self.lightcolors = [ ('lightgrey' if c == 'grey'  else c) for c in self._base_lightcolors ]
        else:
            self.background_color = '#FFFFFF'
            self.text_color       = '#000000'
            self.colors      = list(self._base_colors)
            self.lightcolors = list(self._base_lightcolors)


def read_total_areas_from_csv(path: str | os.PathLike[str]) -> dict[str, float]:
    """
    Read total_area_* values from commented CSV header.

    Matches lines like:
      # total_area_GRACE: 152682342836.82553

    Returns dict of {key: float_value}.
    """
    import os
    import re
    import json

    areas: dict[str, float] = {}
    with open(os.fspath(path), "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            # capture: key and JSON array/value, but exclude keys that end with "_units" to avoid confusion with total_area_units
            m = re.match(r"^\s*#\s*(total_area(?!_units)[^:]*?)\s*:\s*(\[[^\]]*\]|\"[^\"]*\"|[0-9eE+\-\.]+)\s*$", line)
            if not m:
                continue
            key = m.group(1).strip()
            raw = m.group(2).strip()
            try:
                val = json.loads(raw)
            except Exception:
                val = raw

            # normalize to float
            if isinstance(val, list) and val:
                areas[key] = float(val[0])
            else:
                areas[key] = float(val)
    return areas


def read_area_units_from_csv(path: str | os.PathLike[str]) -> str | None:
    """
    Read the total_area_units value from a commented CSV header.

    Returns the units string, or None if not found.
    """
    import json
    with open(os.fspath(path), "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            m = re.match(r"^\s*#\s*total_area_units\s*:\s*(.+?)\s*$", line)
            if m:
                raw = m.group(1)
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list) and len(parsed) == 1:
                        return str(parsed[0])
                    if isinstance(parsed, str):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
                return raw
    return None


def mean_total_area_and_warn(options: "Options",
                             areas: dict[str, float],
                             *,
                             area_diff_max: float | None = 0.05,
                             context:                str = "") -> float | None:
    """
    Compute mean area and warn if area_diff_max is not None and any abs((Ai-mean)/mean) > area_diff_max.
    Returns mean, or None if areas is empty.
    """
    import logging

    if not areas:
        logging.warning(f"{context}: no total_area* entries found in CSV header.")
        return None

    vals = list(areas.values())
    mean = float(sum(vals) / len(vals))

    if len(vals) < 3:
        logging.warning(
            f"{context}: expected 3 total_area* values (SWE/soil_moisture/GRACE) "
            f"but found {len(vals)}: {sorted(areas.keys())}"
        )

    if area_diff_max is not None:
        for k, v in areas.items():
            rel = (float(v) - mean) / mean
            if abs(rel) > float(area_diff_max):
                logging.warning(f"{context}: {k}={v:.6g} {options.area_units_text} differs from mean="
                                f"{mean:.6g} {options.area_units_text} by {rel:+.3%} (limit={area_diff_max:.3%})")
    return mean


def volume_to_thickness_factor(options: "Options", mean_area: float) -> float:
    """
    Convert volume to equivalent water height using area.

    *mean_area* is in whatever units options.area_units_text specifies.
    We convert back to m² via options.area_m2_scale before applying the formula:

    mm = km^3 * (1e9 m^3/km^3) / area_m2 * (1000 mm/m) = km^3 * 1e12 / area_m2
    """
    area_m2 = float(mean_area) / options.area_m2_scale
    return 1.0e12 / area_m2


def resolve_unit_factor(options: "Options",
                        *paths: str | os.PathLike[str],
                        area_diff_max: float | None = 0.05,
                        context: str = "") -> tuple[float | None, float]:
    """
    Read basin area from one or more CSV headers and compute the
    volume → thickness conversion factor.

    Returns:
        (mean_area, unit_factor) — mean_area is None when no
        total_area entries are found in any of the given files.
    """
    # Validate that all CSV files record the same area units, and that they match options.
    file_units: dict[str, str | None] = {}
    for p in paths:
        file_units[str(p)] = read_area_units_from_csv(p)
    found_units = {u for u in file_units.values() if u is not None}
    if len(found_units) > 1:
        detail = ", ".join(f"{p}: {u}" for p, u in file_units.items())
        raise ValueError(f"Inconsistent area units across CSV files: {detail}")
    if found_units and (sole := found_units.pop()) != options.area_units_text:
        raise ValueError(f"Area units in CSV files ({sole!r}) do not match "
                         f"options.area_units_text ({options.area_units_text!r}). "
                         f"Combining these would produce incorrect results.")

    all_areas: dict[str, float] = {}
    for p in paths:
        all_areas.update(read_total_areas_from_csv(p))
    mean_area = mean_total_area_and_warn(
        options, all_areas, area_diff_max=area_diff_max, context=context
    )
    if mean_area is not None:
        return mean_area, volume_to_thickness_factor(options, mean_area)
    return None, 1.0


def load_plot_timeseries(path: str | os.PathLike[str],
                         *,
                         date_col:           str | int = 0,
                         align_monthly_day: int | None = None,
                         comment:                  str = "#") -> pd.DataFrame:
    """
    Load a time-series CSV for plotting.

    - Parses dates
    - Ignores commented header lines
    - Keeps extra columns (e.g., n_months_used)
    - If align_monthly_day is set, resamples to monthly-start and shifts to that day
      (for notebook component inputs like GRACE/SWE/soil/reservoirs)
    """
    import pandas as pd
    df = pd.read_csv(path, comment=comment, skip_blank_lines=True)

    # Resolve date column
    if isinstance(date_col, int):
        date_name = df.columns[date_col]
    else:
        date_name = date_col

    df[date_name] = pd.to_datetime(df[date_name])
    df = df.set_index(date_name).sort_index()

    if align_monthly_day is not None:
        df = df.resample("MS").first()
        df.index = df.index + pd.DateOffset(days=align_monthly_day - 1)

    return df


def segment_timeseries(df: pd.DataFrame,
                       *,
                       discontinuities: list[pd.Timestamp] | None = None,
                       gap_threshold:         pd.Timedelta | None = None) -> list[pd.DataFrame]:
    """
    Split a DataFrame (DatetimeIndex) into contiguous plotting segments.

    Splits on:
    - explicit discontinuity dates
    - gaps larger than gap_threshold
    """
    import pandas as pd
    import numpy as np
    if df.empty:
        return []

    out = [df.sort_index()]

    # Split on explicit discontinuities
    if discontinuities:
        discs = sorted(pd.to_datetime(discontinuities))
        tmp = []
        for part in out:
            start = part.index.min()
            for d in discs:
                seg = part[(part.index >= start) & (part.index < d)]
                if not seg.empty:
                    tmp.append(seg)
                start = d
            seg = part[part.index >= start]
            if not seg.empty:
                tmp.append(seg)
        out = tmp

    # Split on large gaps
    if gap_threshold is not None:
        tmp = []
        for part in out:
            idx = part.index.sort_values()
            diffs = idx.to_series().diff()
            break_idx = np.where(diffs > gap_threshold)[0]
            boundaries = list(break_idx) + [len(idx)]
            start = 0
            for stop in boundaries:
                seg_idx = idx[start:stop]
                if len(seg_idx):
                    tmp.append(part.loc[seg_idx])
                start = stop
        out = tmp

    return out


def _rolling_sigma(series: pd.Series) -> float:
    """Helper function to compute rolling sigma for the error band."""
    import math
    s = series.dropna()
    n = len(s)
    if n == 0:
        return float("nan")
    return math.sqrt(float((s * s).sum())) / n


def smooth_value_error(df: pd.DataFrame,
                       value_col: str,
                       error_col: str,
                       *,
                       window: int = 3) -> pd.DataFrame:
    """Apply a rolling mean to the value column and a custom rolling sigma to the error column."""
    import pandas as pd
    out = df.copy()
    out[value_col] = out[value_col].rolling(window=window, center=True, min_periods=1).mean()
    out[error_col] = out[error_col].rolling(window=window, center=True, min_periods=1).apply(_rolling_sigma, raw=False)
    return out


def average_timeseries(df: pd.DataFrame,
                       *,
                       year_type: str = "calendar",
                       value_col: str = "groundwater",
                       error_col: str = "error") -> pd.DataFrame:
    """
    Aggregate a monthly series into yearly averages with propagated uncertainty.

    Propagate monthly 1σ via:
        σ_year = sqrt(Σ σ_i^2) / n
    Returns columns:
        [value_col, error_col, "n_months_used"]

    year_type:
      - "calendar": Jan–Dec, labeled at ~mid-year (Dec 31 - 6 months)
      - "water":    Oct–Sep, labeled at ~Apr (Sep 30 - 6 months), using WY where Oct..Dec count toward next year
    """
    import pandas as pd
    import numpy as np
    if year_type not in ("calendar", "water"):
        raise ValueError(f"year_type must be 'calendar' or 'water', got '{year_type}'")

    if value_col not in df.columns or error_col not in df.columns:
        raise ValueError(f"Expected columns '{value_col}' and '{error_col}' in df; got {list(df.columns)}")

    records: list[tuple[pd.Timestamp, float, float, int]] = []

    if year_type == "calendar":
        grouped = df.groupby(df.index.year)
        for year, df_y in grouped:
            d = df_y[[value_col, error_col]].dropna()
            n = len(d)
            if n == 0:
                continue
            mean_val = float(d[value_col].mean())
            sigma_year = float(np.sqrt((d[error_col] ** 2).sum()) / n)
            date_label = pd.Timestamp(year=year, month=12, day=31) - pd.DateOffset(months=6)
            records.append((date_label, mean_val, sigma_year, n))
    else:
        tmp = df[[value_col, error_col]].copy()
        tmp["water_year"] = tmp.index.to_series().apply(lambda d: d.year + 1 if d.month >= 10 else d.year)

        grouped = tmp.groupby("water_year")
        for wy, df_y in grouped:
            d = df_y[[value_col, error_col]].dropna()
            n = len(d)
            if n == 0:
                continue
            mean_val = float(d[value_col].mean())
            sigma_year = float(np.sqrt((d[error_col] ** 2).sum()) / n)
            date_label = pd.to_datetime(f"{wy}-09-30") - pd.DateOffset(months=6)
            records.append((date_label, mean_val, sigma_year, n))

    yearly = (
        pd.DataFrame(records, columns=["date", value_col, error_col, "n_months_used"])
        .set_index("date")
        .sort_index()
    )
    yearly.index.name = "date"
    return yearly


def plot_with_uncertainty(ax: plt.Axes,
                          df: pd.DataFrame,
                          value_col: str,
                          error_col: str,
                          label:                          str | None = None,
                          color:                          str | None = None,
                          marker:                         str | None = None,
                          linestyle:                             str = "-",
                          gap_threshold:         pd.Timedelta | None = None,
                          discontinuities: list[pd.Timestamp] | None = None,
                          shift_to_zero:                        bool = False,
                          smooth_window:                  int | None = None,
                          alpha_band:                          float = 0.2) -> None:
    """
    Generic line + ±1σ band plotter.
    Handles optional smoothing, rebasing, and line splitting.
    """
    import pandas as pd
    import matplotlib.pyplot as plt

    if df is None or df.empty:
        return None

    cols = [c for c in [value_col, error_col] if c in df.columns]
    if len(cols) < 2:
        return None

    d = df[[value_col, error_col]].dropna().copy()
    if d.empty:
        return None

    if shift_to_zero:
        d[value_col] = d[value_col] - float(d[value_col].min())

    if smooth_window is not None:
        d = smooth_value_error(d, value_col=value_col, error_col=error_col, window=smooth_window)

    segments = segment_timeseries(d, discontinuities=discontinuities, gap_threshold=gap_threshold)

    first = True
    chosen_color = color
    line_obj = None
    for seg in segments:
        line_obj = ax.plot(
            seg.index,
            seg[value_col],
            label=label if first else None,
            color=chosen_color,
            marker=marker,
            linestyle=linestyle,
        )[0]
        c = chosen_color if chosen_color is not None else line_obj.get_color()
        if chosen_color is None:
            chosen_color = c

        ax.fill_between(
            seg.index,
            seg[value_col] - seg[error_col],
            seg[value_col] + seg[error_col],
            color=c,
            alpha=alpha_band,
            label=None,
        )
        first = False

    return line_obj


def plot_prepped_with_uncertainty(ax: plt.Axes,
                                  df: pd.DataFrame,
                                  *,
                                  label:                          str | None = None,
                                  value_col:                      str | None = None,
                                  error_col:                             str = "error",
                                  color:                          str | None = None,
                                  marker:                         str | None = None,
                                  linestyle:                             str = "-",
                                  gap_threshold:         pd.Timedelta | None = None,
                                  discontinuities: list[pd.Timestamp] | None = None,
                                  shift_to_zero:                        bool = False,
                                  smooth_window:                  int | None = None,
                                  rebase_to_first_point:                bool = False,
                                  alpha_band:                          float = 0.2,
                                  unit_factor:                         float = 1.0) -> None:
    """
    DRY helper for plots like the notebook's component plots.

    Order of operations matches notebook intent:
      1) optional shift_to_zero (subtract min)
      2) optional smoothing (value rolling mean, error via sigma propagation)
      3) optional rebasing to first point (AFTER smoothing)
      4) plot line + ±1σ band, splitting at discontinuities/gaps

    Args:
      - label: the label for the line plot.
      - value_col: if None, choose "groundwater" (if present) else "value" (if present)
                  else first numeric column.
      - error_col: the name of the column containing the error values for the uncertainty band.
      - color: the color of the line plot.
      - marker: the marker style for the line plot.
      - linestyle: the style of the line plot.
      - smooth_window: if not None, smoothing is applied BEFORE rebasing.
      - rebase_to_first_point: subtract first value after smoothing if True.
      - gap_threshold and discontinuities are passed to plot_with_uncertainty to split lines.
      - unit_factor is applied to the value and error columns before plotting.
    """
    import pandas as pd

    if df is None or df.empty:
        return None

    # Choose value_col if not provided
    cols = list(df.columns)
    if value_col is None:
        if "groundwater" in cols:
            value_col = "groundwater"
        elif "value" in cols:
            value_col = "value"
        else:
            num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
            if not num_cols:
                return None
            value_col = num_cols[0]

    if error_col not in df.columns:
        # can't plot uncertainty band without error
        return None

    d = df[[value_col, error_col]].dropna().copy()
    if d.empty:
        return None
    # Unit scaling from volume to thickness (e.g., km^3 -> mm water equivalent height). Error scales identically.
    if unit_factor != 1.0:
        d[value_col] = d[value_col] * float(unit_factor)
        d[error_col] = d[error_col] * float(unit_factor)

    # 1) shift-to-zero (min -> 0), used for SWE in notebook
    if shift_to_zero:
        d[value_col] = d[value_col] - float(d[value_col].min())

    # 2) smoothing (if requested)
    if smooth_window is not None:
        d = smooth_value_error(d, value_col=value_col, error_col=error_col, window=int(smooth_window))

    # 3) rebase AFTER smoothing (notebook behavior) but only if we're not shifting to zero
    if rebase_to_first_point and not shift_to_zero and not d.empty:
        d[value_col] = d[value_col] - d[value_col].iloc[0]

    # 4) plot — call plot_with_uncertainty with NO additional smoothing/shift
    plot_with_uncertainty(
        ax,
        d,
        value_col=value_col,
        error_col=error_col,
        label=label,
        color=color,
        marker=marker,
        linestyle=linestyle,
        gap_threshold=gap_threshold,
        discontinuities=discontinuities,
        shift_to_zero=False,     # already applied if requested
        smooth_window=None,      # already applied if requested
        alpha_band=alpha_band,
    )


def load_component_series(options, component: str, basin_name: str) -> pd.DataFrame | None:
    """Load the time series for a given component and basin, if it exists."""
    basin_safe = options.basin_safename_map.get(basin_name)
    if basin_safe is None:
        return None

    if component == "swe":
        path = options.timeseries_dir / f"anomaly_timeseries_{options.swe_model}_{basin_safe}_mask.csv"
    elif component == "reservoirs":
        path = options.timeseries_dir / f"anomaly_timeseries_{options.reservoirs_model}_{basin_safe}_mask.csv"
    elif component == "groundwater":
        pattern = f"anomaly_timeseries_groundwater_{basin_safe}_*_monthly_unsmoothed*.csv"
        candidates = list(options.output_dir.glob(pattern))
        if not candidates:
            return None
        path = max(candidates, key=os.path.getmtime)
    else:
        raise ValueError(f"Unknown component: {component}")

    if not path.is_file():
        return None

    df = load_plot_timeseries(path, date_col="date", align_monthly_day=15)
    df.attrs["source_path"] = os.fspath(path)

    # Normalize column names: rename <component>/<component>_error → value/error
    # so downstream plotting code can use consistent names.
    cols = list(df.columns)
    # Find the value column (e.g., "swe", "groundwater", or just "value")
    val_candidates = [c for c in cols if c == component or c == "value"]
    err_candidates = [c for c in cols if c == f"{component}_error" or c == "error"]
    if val_candidates and val_candidates[0] != "value":
        df = df.rename(columns={val_candidates[0]: "value"})
    if err_candidates and err_candidates[0] != "error":
        df = df.rename(columns={err_candidates[0]: "error"})

    return df


def fallback_logging_config(log_level: int | str = 'INFO', rawlog: bool = False) -> None:
    """
    Configure the root logger with a basic configuration if no handlers are set.
    Run this at the start of functions which might be run without first configuring logging.

    Args:
        level  : The logging level to set. Defaults to 'INFO'.
        rawlog : If True, use a simple log format without timestamps or levels.
    """
    if not logging.getLogger().handlers:
        if not rawlog:  # Use a full logging format with timestamps and levels.
            logging.basicConfig(level=log_level,
                                format="%(asctime)s %(name)s %(levelname)s: %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        else:  # rawlog is True, so use a simple format without timestamps or levels.
            logging.basicConfig(level=log_level, format="%(message)s")


def filename_format(text: str, sep: str = "_", max_length: int = None) -> str:
    """
    Turn arbitrary text into an ASCII-only, filesystem‐safe base filename.
    WARNING: Do not include an extension in the text, because this function
    will remove the dot which separates the filename from the extension.

    Steps:
      1. Unicode → ASCII
      2. Treat dots, underscores & whitespace as word separators
      3. Remove any character that isn't A-z, a–z, 0–9, dashes, or the separator
      4. Collapse runs of separators into a single one
      5. Trim separators from ends
      6. Optionally truncate to max_length (preserving word boundaries)

    Args:
        text:       Original filename or title
        sep:        Single-character separator (default: "_")
        max_length: If set, strongest‐effort truncate to this many chars

    Returns:
        A clean, filename-safe string.

    Raises:
        None: If the input text is None, it will return an empty string.
    """
    fallback_logging_config()  # Ensure logging is configured
    if not text:
        return ""
    # Normalize to ASCII
    try:
        import unidecode
        text = unidecode.unidecode(text)
    except ImportError:
        logging.debug("unidecode package not found, falling back to ASCII encoding.")
        # Fallback: encode to ASCII, ignore errors
        text = text.encode('ascii', 'ignore').decode('ascii')

    # Replace common "word boundaries" with sep
    #    (dots, underscores, whitespace) but keep dashes
    #    e.g. "hello.world--foo_bar" → "hello world--foo bar"
    text = re.sub(r"[._\s]+", sep, text)

    # Remove anything but dashes, A-Z, a–z, 0–9, or our sep
    allowed = f"-A-Za-z0-9{re.escape(sep)}"
    text = re.sub(fr"[^{allowed}]+", "", text)

    # Collapse runs of sep (e.g. "__" → "_")
    text = re.sub(fr"{re.escape(sep)}{{2,}}", sep, text)

    # Strip leading/trailing seps
    text = text.strip(sep)

    # Optionally truncate (try not to cut in middle of a word)
    if max_length is not None and len(text) > max_length:
        # cut at max_length, then drop a partial trailing token if any
        truncated = text[:max_length]
        # if the next char in original isn't sep and our chop landed mid-token, trim back to last sep
        if (len(text) > max_length and not truncated.endswith(sep) and sep in truncated):
            truncated = truncated.rsplit(sep, 1)[0]
        text = truncated

    return text


def safestring(s: str) -> str:
    """
    Convert a string to a "safe" version by converting to lowercase,
    replacing spaces and special characters with underscores.

    Args:
        s: The input string.

    Returns:
        A "safe" lowercase version of the string with only alphanumeric
        characters and underscores.
    """
    return filename_format(s.casefold())


def ensure_even_dimensions(image_path: str | os.PathLike[str]) -> None:
    """Ensure the image at 'image_path' has dimensions divisible by 2, by resizing if necessary."""
    from PIL import Image
    fallback_logging_config()
    image_path = Path(image_path).expanduser().resolve(strict=True)
    if not image_path.is_file():
        raise IsADirectoryError(f"File does not exist: {image_path}")
    with Image.open(image_path) as img:
        width, height = img.size
        new_width = width if width % 2 == 0 else width - 1
        new_height = height if height % 2 == 0 else height - 1

        if new_width != width or new_height != height:
            try:
                img = img.resize((new_width, new_height), Image.LANCZOS)
                img.save(image_path)
                logging.info(f"Resized image to even dimensions: width = {new_width}, height = {new_height}")
            except OSError as e:
                raise ValueError(f"Could not resize image {image_path} to even dimensions: {e}") from e
        else:
            logging.info(f"Image already has even dimensions: width = {width}, height = {height}")


def find_ffmpeg() -> str | None:
    """
    Return a full path to an ffmpeg executable if found, else None.
    Tries: env vars, PATH, common Conda and Windows/Cygwin/MSYS installs,
    and (optionally) imageio-ffmpeg if available.

    Args:
        None

    Returns:
        The path to the ffmpeg executable or None if not found.

    Raises:
        None
    """
    import shutil
    # 1) Explicit env vars (user can set one of these)
    for env_key in ("FFMPEG", "FFMPEG_PATH", "IMAGEIO_FFMPEG_EXE"):
        p = os.environ.get(env_key)
        if p and Path(p).exists():
            return str(Path(p))

    # 2) On PATH (handles .exe on Windows automatically)
    for name in ("ffmpeg", "ffmpeg.exe"):
        p = shutil.which(name)
        if p:
            return p

    # 3) Typical Conda/Miniconda/Mambaforge locations
    sp = Path(sys.prefix)  # current Python env prefix
    candidates = [
        sp / "bin" / "ffmpeg",                  # Unix-like
        sp / "Library" / "bin" / "ffmpeg.exe",  # Windows (Conda)
        sp / "Scripts" / "ffmpeg.exe",          # Windows (alt)
    ]

    # 4) Common Windows installs (adjust or extend as you like)
    candidates += [
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\cygwin64\bin\ffmpeg.exe"),
        Path(r"C:\msys64\usr\bin\ffmpeg.exe"),
    ]

    # 5) Optional: imageio-ffmpeg packaged binary if user has it
    try:
        import imageio_ffmpeg  # type: ignore
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and Path(p).exists():
            return str(Path(p))
    except Exception:
        pass

    for c in candidates:
        if c.exists():
            return str(c)

    return None


# Mapping of unit aliases (all in lowercase) to their equivalent in seconds
_UNIT_SECONDS = {
    **dict.fromkeys(["year", "years", "yr", "yrs", "calendar year", "calendar years"],    31_556_952),  # Average calender year = 365.2425 days (accounting for leap years)
    **dict.fromkeys(["solar year", "solar years", "tropical year", "tropical years"],     31_556_925.216),  # Average solar/tropical year = 365.24219 solar days = time for Earth to orbit the Sun once relative to the Sun/equinoxes
    **dict.fromkeys(["sidereal year", "sidereal years"],                                  31_558_149.54),  # Sidereal year = 365.25636 days = time for Earth to orbit the Sun once relative to the "fixed" stars
    **dict.fromkeys(["month", "months", "mo", "mos", "calendar month", "calendar months"], 2_629_746.0),  # Average calendar month = 30.436875 solar days
    **dict.fromkeys(["lunar month", "lunar months", "synodic month", "synodic months"],    2_551_442.9),  # Average lunar month (synodic month) = 29.53 solar days
    **dict.fromkeys(["week", "weeks", "wk", "wks"],                                          604_800.0),  # 7 solar days
    **dict.fromkeys(["day", "days", "d", "solar day", "solar days", "ephemeris day", "ephemeris days"], 86_400),  # 24 hours = time for Earth to rotate once relative to the Sun
    **dict.fromkeys(["sidereal day", "sidereal days"],                                                  86_164.0905),  # 23 hours, 56 minutes, 4.1 seconds = time for Earth to rotate once relative to the "fixed" stars
    **dict.fromkeys(["hour",         "hours",   "hr",  "hrs"],          3600),
    **dict.fromkeys(["minute",       "minutes", "min", "mins"],           60),
    **dict.fromkeys(["second",       "seconds", "sec", "secs", "s"],    1.00),
    **dict.fromkeys(["decisecond",   "deciseconds",  "ds"],            1E-01),
    **dict.fromkeys(["centisecond",  "centiseconds", "cs"],            1E-02),
    **dict.fromkeys(["millisecond",  "milliseconds", "ms"],            1E-03),
    **dict.fromkeys(["microsecond",  "microseconds", "us", "μs"],      1E-06),
    **dict.fromkeys(["nanosecond",   "nanoseconds",  "ns"],            1E-09),
    **dict.fromkeys(["picosecond",   "picoseconds",  "ps"],            1E-12),
    **dict.fromkeys(["femtosecond",  "femtoseconds", "fs"],            1E-15),
    **dict.fromkeys(["attosecond",   "attoseconds",  "as"],            1E-18),
    **dict.fromkeys(["zeptosecond",  "zeptoseconds", "zs"],            1E-21),
    **dict.fromkeys(["yoctosecond",  "yoctoseconds", "ys"],            1E-24),
    **dict.fromkeys(["planck time",  "planck times", "planck", "plancks", "pt"], 5.391_247E-44),  # Planck time
    **dict.fromkeys(["decade",       "decades"],                                315_569_252.16),  #   10 solar years
    **dict.fromkeys(["century",      "centuries"],                            3_155_692_521.60),  #  100 solar years
    **dict.fromkeys(["millennium",   "millennia"],                           31_556_925_216.00),  # 1000 solar years
    **dict.fromkeys(["megayear",     "megayears", "mya", "myr"],         31_556_925_216_000.00),  # 1E06 solar years
    **dict.fromkeys(["gigayear",     "gigayears", "gya", "gyr"],     31_556_925_216_000_000.00),  # 1E09 solar years
    **dict.fromkeys(["terayear",     "terayears", "tya", "tyr"], 31_556_925_216_000_000_000.00),  # 1E12 solar years
    **dict.fromkeys(["fortnight",    "fortnights"],                               1_209_600.00),  # 2 weeks = 604_800 * 2 seconds
    **dict.fromkeys(["decasecond",   "decaseconds",   "das"], 1E01),
    **dict.fromkeys(["hectosecond",  "hectoseconds",  "hs"],  1E02),
    **dict.fromkeys(["kilosecond",   "kiloseconds",   "ks"],  1E03),
    **dict.fromkeys(["megasecond",   "megaseconds"],          1E06),  # no Ms because .casefold() would convert it to ms
    **dict.fromkeys(["gigasecond",   "gigaseconds",   "gs"],  1E09),
    **dict.fromkeys(["terasecond",   "teraseconds",   "ts"],  1E12),
    **dict.fromkeys(["petasecond",   "petaseconds"],          1E15),  # no Ps because .casefold() would convert it to ps
    **dict.fromkeys(["exasecond",    "exaseconds",    "es"],  1E18),
    **dict.fromkeys(["zettasecond",  "zettaseconds"],         1E21),  # no Zs because .casefold() would convert it to zs
    **dict.fromkeys(["yottasecond",  "yottaseconds"],         1E24),  # no Ys because .casefold() would convert it to ys
    **dict.fromkeys(["ronnasecond",  "ronnaseconds",  "rs"],  1E27),
    **dict.fromkeys(["quettasecond", "quettaseconds", "qs"],  1E30),
}


def seconds_in_unit(unit: str) -> float:
    """Return the number of seconds in a given time unit."""
    try:
        return _UNIT_SECONDS[unit.casefold()]
    except KeyError:
        raise ValueError(f"Unknown time unit: {unit!r}")


# Common US & UTC/GMT abbreviations → IANA zone names
_TZ_ABBREV_TO_ZONE: dict[str, str] = {
    "UTC"  : "UTC",
    "GMT"  : "Etc/GMT",
    "EST"  : "America/New_York",
    "EDT"  : "America/New_York",
    "CST"  : "America/Chicago",  # WARNING! "CST" can also mean China Standard Time (Asia/Shanghai, UTC+8), so use with caution!
    "CDT"  : "America/Chicago",
    "MST"  : "America/Denver",
    "MDT"  : "America/Denver",
    "PST"  : "America/Los_Angeles",
    "PDT"  : "America/Los_Angeles",
    "HST"  : "Pacific/Honolulu",
    "AKST" : "America/Anchorage",
    "AKDT" : "America/Anchorage",
    "AST"  : "America/Puerto_Rico",  # Atlantic Standard Time
    "ADT"  : "America/Puerto_Rico",  # Atlantic Daylight Time
    "NST"  : "America/St_Johns",     # Newfoundland Standard Time
    "NDT"  : "America/St_Johns",     # Newfoundland Daylight Time
    "BST"  : "Europe/London",        # British Summer Time
    "CET"  : "Europe/Berlin",        # Central European Time
    "CEST" : "Europe/Berlin",        # Central European Summer Time
    "EET"  : "Europe/Athens",        # Eastern European Time
    "EEST" : "Europe/Athens",        # Eastern European Summer Time
    "IST"  : "Asia/Kolkata",         # Indian Standard Time - WARNING! "IST" can also mean Irish Standard Time (Europe/Dublin, UTC+1), so use with caution!
    "JST"  : "Asia/Tokyo",           # Japan Standard Time
    "KST"  : "Asia/Seoul",           # Korea Standard Time
    "HKT"  : "Asia/Hong_Kong",       # Hong Kong Time
    "SGT"  : "Asia/Singapore",       # Singapore Time
    "AEST" : "Australia/Sydney",     # Australian Eastern Standard Time
    "AEDT" : "Australia/Sydney",     # Australian Eastern Daylight Time
    "ACST" : "Australia/Adelaide",   # Australian Central Standard Time
    "ACDT" : "Australia/Adelaide",   # Australian Central Daylight Time
    "AWST" : "Australia/Perth",      # Australian Western Standard Time
    "AWDT" : "Australia/Perth",      # Australian Western Daylight Time
    "NZT"  : "Pacific/Auckland",     # New Zealand Time
    "NZST" : "Pacific/Auckland",     # New Zealand Standard Time
    "NZDT" : "Pacific/Auckland",     # New Zealand Daylight Time
    "WET"  : "Europe/Lisbon",        # Western European Time
    "WEST" : "Europe/Lisbon",        # Western European Summer Time
    # ...add any others you need
}

# Pre‐compile once for all calls.
_TZ_OFFSET_RE: re.Pattern = re.compile(r'''
    ^(?P<sign>[+-])
    (?:
        (?P<hours1>\d{1,2})[hH](?P<mins1>\d{1,2})(?:[mM])?  # +5h30m
      | (?P<hours1_only>\d{1,2})[hH]                        # +5h
      | (?P<hours2>\d{1,2}):(?P<mins2>\d{2})                # +5:30
      | (?P<hours3>\d{1,2})(?P<mins3>\d{2})                 # +0530
      | (?P<hours4>\d{1,2})                                 # +5
    )
    $
''', re.VERBOSE)


def parse_timezone(tz_arg: str | dt.tzinfo | None = None) -> dt.tzinfo | str:
    """
    Parse the given timezone string or tzinfo object into a datetime.tzinfo object.
    If tz_arg is None, return UTC timezone.
    If tz_arg is a string, it can be in one of the following formats:
      - A fixed‐offset like: "+HH:MM", "+HHMM", "+H", "+Hh", "+HhMMm" (or minus variants).
         Examples: "+05:30", "-0530", "+5h", "-5h30m".
      - A string that can be converted to a ZoneInfo object (e.g. 'America/New_York').
      - A timezone abbreviation that maps to a known IANA zone name (e.g. 'EST', 'CET').
      - "Z", "UTC", or "GMT" (case‐insensitive) to represent UTC.
      - A string "Naive" to represent a naive datetime (no timezone).
    If tz_arg is already a tzinfo object, return it as is.

    Args:
        tz_arg : A timezone string, a datetime.tzinfo object, or None.

    Returns:
        A datetime.tzinfo object representing the parsed timezone, or a string "Naive"
        if the input was "Naive".

    Raises:
        ValueError if the string cannot be converted to a valid timezone.
    """

    # If tz_arg is None, return UTC timezone
    if tz_arg is None:
        return dt.timezone.utc

    # If tz_arg is already a tzinfo object, return it unchanged
    if isinstance(tz_arg, dt.tzinfo):
        return tz_arg

    # If tz_arg is a string, try to parse it
    if isinstance(tz_arg, str):
        s = tz_arg.strip()
        up = s.upper()

        # Handle "Naive" case
        if up == "NAIVE":
            return tz_arg

        # Bare UTC/GMT/Z
        if up in ("Z", "UTC", "GMT") and len(s) <= 3:
            return dt.timezone.utc

        # Strip leading "UTC" or "GMT" prefix
        if up.startswith(("UTC", "GMT")):
            rest = s[3:].strip()
            if rest == "":
                return dt.timezone.utc
            s = rest  # now s begins with + or -

        # Try fixed-offset patterns
        m = _TZ_OFFSET_RE.fullmatch(s)
        if m:
            sign = 1 if m.group("sign") == "+" else -1

            if m.group("hours1") is not None:
                hours   = int(m.group("hours1"))
                minutes = int(m.group("mins1"))
            elif m.group("hours1_only") is not None:
                hours   = int(m.group("hours1_only"))
                minutes = 0
            elif m.group("hours2") is not None:
                hours   = int(m.group("hours2"))
                minutes = int(m.group("mins2"))
            elif m.group("hours3") is not None:
                hours   = int(m.group("hours3"))
                minutes = int(m.group("mins3"))
            else:
                hours   = int(m.group("hours4"))
                minutes = 0

            offset = dt.timedelta(hours=hours, minutes=minutes) * sign
            return dt.timezone(offset)

        # Otherwise, fall back to ZoneInfo
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        except ImportError:  # for Python < 3.9, fall back to backports.zoneinfo
            from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        # Try to interpret the string as a timezone abbreviation
        if up in _TZ_ABBREV_TO_ZONE:
            zone_name = _TZ_ABBREV_TO_ZONE[up]
            return ZoneInfo(zone_name)

        # Try to interpret the string as a ZoneInfo name
        try:
            return ZoneInfo(tz_arg)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"Unknown timezone {tz_arg!r}: {e}") from e

    raise TypeError(f"Expected None, str, or tzinfo; got {type(tz_arg).__name__!r}")


def decimal_year_to_datetime(dec: float, use_astropy: bool = False) -> dt.datetime:
    """
    Convert a decimal year to a datetime object.
    If use_astropy is True, astropy.time is used for sub-second and leap-second–aware conversion.
    Usage: new_datetime_datetime_object = decimal_year_to_datetime(2002.291)
    """
    if use_astropy:
        try:
            from astropy.time import Time
        except ImportError as e:
            raise ValueError(f"'use_astropy=True' requires the astropy package: {e}") from e
        t = Time(dec, format="jyear", scale="utc")
        return t.to_datetime().replace(tzinfo=dt.timezone.utc)

    try:
        year = int(dec)
        rem = dec - year
        start_dt = dt.datetime(year,     1, 1, tzinfo=dt.timezone.utc)
        end_dt   = dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc)
        year_secs = (end_dt - start_dt).total_seconds()
        return start_dt + dt.timedelta(seconds=rem * year_secs)
    except ValueError as e:
        raise ValueError(f"Failed to convert decimal year {dec} to datetime: {e}") from e


def _parse_iso(given_date: str) -> dt.datetime:
    """Parse an ISO8601 date string and return a datetime object. Raises ValueError if the date string is invalid."""
    from dateutil.parser import isoparse, ParserError

    try:
        return isoparse(given_date)
    except ParserError as e:
        raise ValueError(f"Invalid ISO8601 date '{given_date}'") from e


def is_float(s: str) -> bool:
    """Check if a string can be parsed as a float."""
    try:
        float(s)
        return True
    except ValueError:
        return False


# Precompile Julian/MJD regex
# This regex is just used to check if a string looks like a JD or MJD:
_JD_MJD_SIMPLE_RE: re.Pattern  = re.compile(r"\s*(JD|MJD)?\s*[+-]?\d+(\.\d+)?\s*", re.IGNORECASE)
# This regex is used to capture the prefix (JD or MJD) and the value from a string that looks like a JD or MJD:
_JD_MJD_CAPTURE_RE: re.Pattern = re.compile(r"\s*(?P<prefix>JD|MJD)?\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*", re.IGNORECASE)
# This regex is used to check if a string has an explicit offset or Z at the end (indicating that the date should be converted by shifting the clock):
_OFFSET_IN_STR_RE: re.Pattern  = re.compile(r"(Z|[+-]\d{2}:\d{2}|[+-]\d{4})$")

# Julian Date at 1970-01-01T00:00:00 UTC
_JD_UNIX_EPOCH: float = 2_440_587.5

# Enclose the type alias annotation in quotes because not all of these types have been imported yet.
AnyDateTimeType: TypeAlias = "str | float | int | np.datetime64 | pd.Timestamp | dt.datetime"


def _should_convert(given_date: AnyDateTimeType, format_str: str | None = None) -> bool:
    """Determine if the given date should be converted to a timezone (i.e. if the wall clock should be shifted) or if the timezone should just be attached without shifting the clock."""

    # 1) Numbers, JD/MJD, decimal years, special keywords
    if isinstance(given_date, (int, float)) and not isinstance(given_date, bool):
        if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Given date is a number: %s, so it will be converted by shifting the clock", given_date)
        return True
    if isinstance(given_date, str):
        u = given_date.strip().upper()
        if u in ("J2000", "UNIX", "NOW"):
            if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Given date is a special keyword: %s, so it will be converted by shifting the clock", u)
            return True
        if format_str and format_str.upper() in ("JD", "MJD"):
            if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Given date has a format_str: %s, so it will be converted by shifting the clock", format_str)
            return True
        if _JD_MJD_SIMPLE_RE.fullmatch(given_date):
            if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Given date is a JD/MJD: %s, so it will be converted by shifting the clock", given_date)
            return True
        # explicit offset or Z
        if _OFFSET_IN_STR_RE.search(given_date):
            if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Given date has an explicit offset or Z: %s, so it will be converted by shifting the clock", given_date)
            return True
    # 2) Any datetime/timestamp already aware
    if isinstance(given_date, dt.datetime) and given_date.tzinfo is not None:
        if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Given date is an aware datetime: %s, so it will be converted by shifting the clock", given_date)
        return True

    # Otherwise treat it as local‐time → attach only
    if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Given date is not a number, JD/MJD, or aware datetime: %s, so the timezone will be attached without shifting the clock", given_date)
    return False


def _finalize_datetime(parsed_dt: dt.datetime, original_input: AnyDateTimeType,
                       format_str: str | None, tz_arg: str | dt.tzinfo | None,
                       should_convert: bool | None = None) -> dt.datetime:
    """
    Finalize the datetime object by either converting it to the target timezone or just attaching the timezone without shifting the clock. The boolean argument 'should_convert' can override the default behavior, which is determined by the function _should_convert().

    Args:
        parsed_dt:      The datetime object that has been parsed from the original input.
        original_input: The original input that was used to parse the datetime.
        format_str:     The format string used to parse the datetime, if any.
        tz_arg:         The timezone argument, which can be a string or a datetime.tzinfo object.
        should_convert: A boolean indicating whether to convert the datetime to the specified timezone by shifting the clock (True) or just attaching the timezone without shifting (False). If None, the function will determine this based on the type of original_input and format_str.

    Returns:
        A datetime.datetime object in the specified timezone.
        If tz_arg is "Naive", the datetime will be returned without any timezone info.
        If should_convert is True, the datetime will be converted to the specified timezone by shifting the clock.
        If should_convert is False, the timezone will be attached to the datetime without shifting the clock.
        If should_convert is None, the function will determine whether to convert or not based on the type of original_input and format_str.

    Raises:
        ValueError: If the tz_arg is not a valid timezone string or tzinfo object.
        TypeError:  If the parsed_dt is not a datetime.datetime object.
    """
    if isinstance(tz_arg, str) and tz_arg.strip().upper() == "NAIVE":
        if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Naive timezone requested, returning datetime %s without any timezone info", parsed_dt)
        return parsed_dt.replace(tzinfo=None)
    target_tz = parse_timezone(tz_arg)
    if should_convert is not False and (_should_convert(original_input, format_str) or should_convert is True):
        if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Converting datetime %s to timezone %s by shifting the clock", parsed_dt, target_tz)
        return parsed_dt.astimezone(target_tz)
    else:
        if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Attaching timezone %s to datetime %s without shifting the clock", target_tz, parsed_dt)
        return parsed_dt.replace(tzinfo=target_tz)


def parse_datetime(given_date: AnyDateTimeType, timezone: str | dt.tzinfo | None = None,
                   format_str: str | None = None,
                   should_convert: bool | None = None) -> dt.datetime:
    """
    Try parsing the given_date string or number into a datetime.datetime object in the specified timezone.

    If "format_str" is provided, it will be used to parse the date string. These format types are accepted:
     - "seconds" or "milliseconds" indicating the number of seconds or milliseconds since an epoch (Unix epoch by default).
     - "YYYY-MM-DD" or similar ISO8601 formats such as "YYYY-MM-DDTHH:MM:SS", "MM/DD/YYYY", etc.
     - A custom string following this pattern: "units (optional: since/after epoch)", where "units" can be anything that the function seconds_in_unit() accepts (e.g. "days", "weeks", "months", etc.). The optional epoch time can be a string, float, int, numpy.datetime64, pandas.Timestamp, or datetime.datetime object. Example: "days since 1990", "milliseconds after J2000", "sidereal days since 2000-01-01", etc. If the epoch is not specified, it defaults to the Unix epoch (1970-01-01T00:00:00Z)

    If a boolean "should_convert" is provided, it will override the default behavior of whether to convert the datetime to the specified timezone by shifting the clock or just attaching the timezone without shifting. If None, the function will determine this based on the type of given_date and format_str.

    If a given_date starts with "JD" or "MJD", it will be treated as a Julian Date or Modified Julian Date, respectively.

    Otherwise, if given_date is a float or int, treat it as a decimal year by default if format_str is not provided.

    Any call that doesn't provide a timezone argument will default to UTC.
    The timezone can be a datetime.tzinfo object or a string that can be converted to a ZoneInfo object (e.g. 'America/New_York').
    If the given_date is an "aware" datetime.datetime object which already has a timezone attached, it will be converted to the specified timezone (which may involve changing its date and time if the specified timezone is different).
    The timezone can also be a fixed‐offset like "+05:30" or "-04:00", or the string "Naive" to indicate that the datetime should be treated as a naive datetime (i.e. without any timezone information).

    Accepts:
        'NOW' (case-insensitive) → current datetime
        strings in YYYY, YYYY-MM, YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, or other ISO8601 formats (e.g. '2002-10-18T07:00:00Z', '2002-10-18 07:00:00+00:00').
        If YYYY is provided, it will default to January 1st of that year at midnight.
        If YYYY-MM is provided, it will default to the first day of that month at midnight.
        If YYYY-MM-DD is provided, it will default to midnight on that day.
        fallback to dateutil.parser.parse for free-form strings ("18 Oct 2002", "March 5th, 2020", etc.)
        floats (e.g. 2002.29178082191777) or integer (e.g. 2002) → decimal year
        numpy.datetime64 objects (e.g. np.datetime64('2002-10-18T07:00:00'))
        pandas.Timestamp objects (e.g. pd.Timestamp('2002-10-18 07:00:00'))
        datetime.datetime objects (e.g. datetime.datetime(2002, 10, 18, 7, 0, 0))

    Args:
        given_date:     The date to parse, which can be a string, float, int, numpy.datetime64,
                        pandas.Timestamp, or datetime.datetime object.
        timezone:       A string or datetime.tzinfo object representing the timezone to convert
                        the datetime to. If None, defaults to UTC.
        format_str:     A string indicating the format of the date. If None, the function will
                        try to infer the format from the given_date.
        should_convert: A boolean indicating whether to convert the datetime to the specified
                        timezone by shifting the clock (True) or just attaching the timezone
                        without shifting (False). If None, the function will determine this
                        based on the type of given_date and format_str.

    Returns:
        datetime.datetime object in the specified timezone.
        Note that datetime.datetime objects cannot represent dates before 1 January 1, 0001 or after 31 December 9999.
        So dates outside this range will raise a ValueError. Future versions of this code may support a wider range of dates (like 44 BC, 44 BCE, etc.) using libraries like 'astropy.time': https://chatgpt.com/share/685c5157-5cac-8006-b68c-4a0731927a50
        However, this will require the function to return an 'astropy.time.Time' object instead of a 'datetime.datetime' object.

    Raises:
        ValueError:  If the given_date cannot be parsed into a datetime object, or if the timezone is invalid.
        TypeError:   If the given_date is not a string, float, int, numpy.datetime64, pandas.Timestamp, or datetime.datetime object.
    """
    fallback_logging_config()  # Ensure logging is configured

    parsed_tz = parse_timezone(timezone)  # Ensure timezone is a valid tzinfo object or string

    parsed_dt = None

    # Handle special cases:
    if isinstance(given_date, str):
        if given_date.strip().upper() == "J2000":
            # J2000 is January 1, 2000, 11:58:55.816 UTC
            parsed_dt = dt.datetime(2000, 1, 1, 11, 58, 55, 816_000, tzinfo=dt.timezone.utc)
        if given_date.strip().upper() == "UNIX":
            # UNIX epoch is January 1, 1970, 00:00:00 UTC
            parsed_dt = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        if given_date.strip().upper() == "NOW":
            parsed_dt = dt.datetime.now(tz=dt.timezone.utc)

    # Handle forced or explicit Julian Date (JD) or Modified Julian Date (MJD)
    m: re.Match | None = None
    prefix: str | None = None
    if parsed_dt is None and isinstance(given_date, str):
        m = _JD_MJD_CAPTURE_RE.fullmatch(given_date)
        if m:
            prefix = m.group("prefix")

    # Trigger JD/MJD branch only if format_str equals "JD" or "MJD", or prefix was provided
    if parsed_dt is None and (prefix is not None or (format_str and (format_str.upper() == "JD" or format_str.upper() == "MJD"))):
        # Determine raw value
        if isinstance(given_date, (int, float)):
            value = float(given_date)
        else:
            if m is not None:
                value = float(m.group("value"))
            else:
                try:
                    value = float(given_date.strip())
                except ValueError as e:
                    raise ValueError(f"Expected a JD/MJD numeric value, got {given_date!r}") from e

        # Determine if MJD conversion needed
        use_mjd = bool((format_str and format_str.upper() == "MJD") or (prefix and prefix.upper() == "MJD"))

        # Convert MJD to JD if necessary, then to datetime via timedelta from Unix epoch
        jd_val    = value + (2_400_000.5 if use_mjd else 0.0)
        unix_secs = (jd_val - _JD_UNIX_EPOCH) * 86_400
        parsed_dt = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=unix_secs)

    # Check if the given_date is a string that can be parsed as a float
    if parsed_dt is None and isinstance(given_date, str) and is_float(given_date):
        given_date = float(given_date)  # Convert string to float if it represents a number
    # Check if the given_date is a float or int but NOT a boolean
    if parsed_dt is None and isinstance(given_date, (int, float)) and not isinstance(given_date, bool):
        if format_str is None:
            # If the given_date is a decimal year, convert it to datetime in the specified timezone
            # Note: This will not shift the clock, just attach the tzinfo.
            parsed_dt = decimal_year_to_datetime(float(given_date))
        else:  # If format is provided, parse the date using the specified format.
            if not isinstance(format_str, str):
                raise TypeError(f"Expected 'format' to be a string, got {type(format_str).__name__!r}")
            # Make sure the format string is a valid example of "units (optionally: since/after epoch)"
            # Try to split by since or after, whichever works:
            format_parts = re.split(r'\s+(since|after)\s+', format_str, maxsplit=1)
            if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug("Parsing date with format string: '%s' split into parts: %s", format_str, format_parts)
            if len(format_parts) > 3:
                raise ValueError(f"Invalid format string: '{format_str}'. Expected at most three parts: 'units', 'since/after', and 'epoch'.")
            # The first part should be acceptable by seconds_in_unit():
            try:
                units      = format_parts[0].strip()
                multiplier = seconds_in_unit(units)  # This will raise ValueError if the unit is unknown
            except ValueError as e:
                raise ValueError(f"Invalid time unit '{units}' in format string '{format_str}': {e}") from e
            # If the format_parts list has only one part, it means the epoch defaults to the Unix epoch (1970-01-01T00:00:00Z).
            if len(format_parts) == 1:
                # If the format_parts list has only one part, it means the format is just "units" (e.g. "days", "weeks", etc.)
                # In this case, we assume the epoch is the Unix epoch (1970-01-01T00:00:00Z).
                epoch_str = "1970-01-01T00:00:00Z"
            else:
                # If the format_parts list has three parts, the third part is the epoch.
                epoch_str = format_parts[2].strip()
            try:
                epoch = parse_datetime(epoch_str, timezone=parsed_tz)
            except ValueError as e:
                raise ValueError(f"Invalid epoch '{epoch}' in format string '{format_str}': {e}") from e
            # Now we can calculate the datetime based on the given_date (and the multiplier from 'units') and the epoch
            parsed_dt = epoch + dt.timedelta(seconds=float(given_date) * multiplier)

    if parsed_dt is None and type(given_date) is dt.datetime:  # Don't use isinstance() here, because it will also match subclasses like Pandas Timestamp
        parsed_dt = given_date
    elif isinstance(given_date, dt.date):  # Handle date objects (without time) as midnight
        parsed_dt = dt.datetime.combine(given_date, dt.time.min)

    if parsed_dt is None:
        try:
            import numpy as np
        except ImportError:
            np = None
        if np is not None and isinstance(given_date, np.datetime64):
            ts_ns     = given_date.astype("datetime64[ns]").astype("int64")
            parsed_dt = dt.datetime.fromtimestamp(
                ts_ns / 1e9,
                tz=parsed_tz if isinstance(parsed_tz, dt.tzinfo) else None,
            )

    if parsed_dt is None:
        try:
            import pandas as pd
        except ImportError:
            pd = None
        if pd is not None and isinstance(given_date, pd.Timestamp):
            parsed_dt = given_date.to_pydatetime()

    error_message: str = f"The date '{given_date}' is type {type(given_date).__name__!r} in an unknown format. Please use NOW, YYYY, YYYY-MM, YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, other ISO8601 strings, or a decimal year like 2002.291. Datetimes in pandas.Timestamp, numpy.datetime64, or datetime.datetime formats are also accepted and will be converted to datetime.datetime objects in the specified timezone ({parsed_tz})."

    if parsed_dt is None and not isinstance(given_date, str):
        raise TypeError(error_message)

    if parsed_dt is not None:
        # Finalize the datetime object by converting it to the target timezone or just attaching the timezone without shifting the clock
        return _finalize_datetime(parsed_dt, given_date, format_str, parsed_tz, should_convert)

    # From here on, we know it's a str (we raised or otherwise handled non-str types above)
    assert isinstance(given_date, str)
    given_string = given_date

    if parsed_dt is None and format_str is not None:
        try:
            parsed_dt = dt.datetime.strptime(given_string, format_str)
        except ValueError as e:
            raise ValueError(f"Invalid date format '{given_string}' with specified format '{format_str}': {e}") from e

    # Try parsing the date string in various formats
    # Start with RFC 2822 format, then ISO8601, then free-form strings
    # Store any errors encountered in a list to provide feedback if all parsing attempts fail.
    errors: list[str] = []

    if parsed_dt is None:
        import email.utils
        try:
            # parses "Tue, 25 Jun 2025 14:00:00 GMT"
            parsed_dt = email.utils.parsedate_to_datetime(given_string)
        except (TypeError, ValueError) as e:
            errors.append(f"Failed to parse '{given_string}' as an RFC 2822 date: {e}")

    if parsed_dt is None:
        try:
            parsed_dt = _parse_iso(given_string)
        except ValueError as e:
            errors.append(f"Failed to parse '{given_string}' as an ISO8601 date: {e}")

    if parsed_dt is None:
        try:
            from dateutil.parser import parse as parse_fuzzy
            parsed_dt = parse_fuzzy(given_string, default=dt.datetime(1900, 1, 1))
        except ValueError as e:
            errors.append(f"Failed to parse '{given_string}' as a free-form date string: {e}")

    if parsed_dt is None:
        if np is None:
            errors.append("The numpy package is not installed, so numpy.datetime64 objects cannot be parsed.")
        if pd is None:
            errors.append("The pandas package is not installed, so pandas.Timestamp objects cannot be parsed.")
    else:
        # Finalize the datetime object by converting it to the target timezone or just attaching the timezone without shifting the clock
        return _finalize_datetime(parsed_dt, given_string, format_str, parsed_tz, should_convert)

    raise ValueError(error_message + "\n".join(map(str, errors)) + "\nPlease check the input format and try again.")


if __name__ == "__main__":
    main()
