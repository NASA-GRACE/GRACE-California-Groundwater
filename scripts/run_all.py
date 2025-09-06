#!/usr/bin/env python3
# Written by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), and GitHub Copilot (it/its).
from __future__ import annotations  # For Python 3.7+ compatibility with type annotations
import os
from pathlib import Path
import argparse
import sys
import subprocess
import shlex
import logging
from typing import TypeAlias
import re  # Used to precompile regexes for performance

# This is the version of python which should be used in scripts that import this module.
PY_VERSION = 3.12


class Options:
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with default values."""
        self.script_dir:              Path = Path(__file__).resolve().parent  # Figure out where this file lives on disk
        self.project_root:            Path = self.script_dir.parent           # Project root is one level above script_dir
        self.soil_moisture_model:      str = "NLDAS"
        self.swe_model:                str = "SNODAS"
        self.reservoirs_model:         str = "CDEC"
        self.datatypes:          list[str] = ["GRACE",
                                              self.soil_moisture_model,
                                              self.swe_model,
                                              self.reservoirs_model,
                                              "Groundwater"]

        self.valid_basins:                  list[str] = ["California", "Sacramento", "San Joaquin", "Tulare-Buena Vista Lakes"]
        self.default_basin:                       str = self.valid_basins[1]

        self.keep_these_soil_moisture_vars: list[str] = ['SoilM_0_100cm']  # leave [] to keep everything

        self.swe_dir:           Path = self.project_root / "input_data" / "snow_water_equivalent" / self.swe_model
        self.soil_moisture_dir: Path = self.project_root / "input_data" / "soil_moisture"         / self.soil_moisture_model
        self.reservoirs_dir:    Path = self.project_root / "input_data" / "reservoirs"            / self.reservoirs_model
        self.grace_dir:         Path = self.project_root / "input_data" / "grace_tws"
        self.timeseries_dir:    Path = self.project_root / "input_data" / "masked_timeseries"
        self.output_dir:        Path = self.project_root / "output"
        self.graphics_dir:      Path = self.project_root / "graphics"
        self.swe_dir.mkdir(          parents=True, exist_ok=True)
        self.soil_moisture_dir.mkdir(parents=True, exist_ok=True)
        self.reservoirs_dir.mkdir(   parents=True, exist_ok=True)
        self.grace_dir.mkdir(        parents=True, exist_ok=True)
        self.timeseries_dir.mkdir(   parents=True, exist_ok=True)
        self.output_dir.mkdir(       parents=True, exist_ok=True)
        self.graphics_dir.mkdir(     parents=True, exist_ok=True)

        self.log_mode:           int = logging.INFO  # Use the -debug command line argument to change to DEBUG.
        self.separator_line:     str = "-" * 60  # A line of dashes for logging separation

        # Generate safe names for basins (no spaces or special characters) and dictionaries for mapping between them.
        self.basin_safenames:           list[str] = [safestring(title) for title in self.valid_basins]
        # key = basin name,      value = safe basin name
        self.basin_safename_map:   dict[str, str] = dict(zip(self.valid_basins, self.basin_safenames))
        # key = safe basin name, value = basin name
        self.reverse_safename_map: dict[str, str] = {v: k for k, v in self.basin_safename_map.items()}

        if self.default_basin not in self.valid_basins:
            raise ValueError(f"In run_all.py, default basin '{self.default_basin}' specified in Options.__init__() is not in the list of valid basins: {self.valid_basins}")

        self.default_basin_safename = self.basin_safename_map[self.default_basin]


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Run all processing scripts in order.")
    parser.add_argument("--dry_run", action="store_true",
                        help="If set, print commands without executing them")
    parser.add_argument('-debug', action='store_true',
                        help="Run all programs in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = logging.DEBUG


def main() -> None:
    """Run all the processing scripts in order."""
    options = Options()
    logging.basicConfig(level=options.log_mode, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
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

    logging.info("Call raster mask generator for GRACE TWS data...")
    run_script(options, "call_raster_mask_generator.py")

    logging.info("Generating GRACE TWS anomaly time series...")
    run_script(options, "grace_tws_anomaly.py")

    logging.info("Interpolating GRACE TWS data to daily time steps...")
    run_script(options, "interpolate_grace.py")

    logging.info("Generate a time series plot of the masked GRACE data.")
    run_script(options, "plot_timeseries.py")

    section_header(options, "Processing SNODAS snow water equivalent data")

    logging.info("Downloading snow water equivalent (SWE) data...")
    run_script(options, "swe_daily_downloader.py")

    logging.info("Processing snow water equivalent (SWE) data into monthly means...")
    run_script(options, "swe_monthly_mean.py")

    logging.info("Call raster mask generator for snow water equivalent (SWE) data...")
    run_script(options, "call_raster_mask_generator.py", flags=["--target_dataset", "swe"])

    logging.info("Processing snow water equivalent (SWE) data into monthly means and anomalies...")
    run_script(options, "swe_repair_mask_generator.py")

    logging.info("Processing snow water equivalent (SWE) data into monthly anomalies...")
    run_script(options, "swe_monthly_anomaly.py")

    logging.info("Generate a time series plot of the masked snow water equivalent (SWE) data.")
    run_script(options, "plot_timeseries.py")

    section_header(options, "Computing groundwater anomaly and plotting results")

    logging.info("Computing groundwater anomaly time series...")
    run_script(options, "compute_groundwater.py")

    logging.info("Generating comparison plots of all water storage components...")
    run_script(options, "plot_timeseries.py", flags=["--groundwater"])


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
    if getattr(options.args, 'debug', False):
        flags.append('-debug')
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
        # keep immutable “base” palettes so we can recompute safely
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
            # recompute “view” palettes from the bases
            self.colors      = [ ('darkgrey' if  c == 'black' else c) for c in self._base_colors ]
            self.lightcolors = [ ('lightgrey' if c == 'grey'  else c) for c in self._base_lightcolors ]
        else:
            self.background_color = '#FFFFFF'
            self.text_color       = '#000000'
            self.colors      = list(self._base_colors)
            self.lightcolors = list(self._base_lightcolors)


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
    might remove the dot which separates the filename from the extension.
    It attempts to recognize and remove extensions listed in all_known_extensions
    but this list is not exhaustive.

    Steps:
      1. Unicode → ASCII
      2. Recognize & remove common extensions (e.g. .txt, .fits, .tar.gz)
      3. Treat dots, underscores & whitespace as word separators
      4. Remove any character that isn't A-z, a–z, 0–9, dashes, or the separator
      5. Collapse runs of separators into a single one
      6. Trim separators from ends
      7. Optionally truncate to max_length (preserving word boundaries)
      8. If an extension was removed, append it back as the last step.

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
        logging.warning("unidecode package not found, falling back to ASCII encoding.")
        # Fallback: encode to ASCII, ignore errors
        text = text.encode('ascii', 'ignore').decode('ascii')

    # List of common extensions to recognize and (temporarily) remove
    removed_ext = ""
    for ext in all_known_extensions:
        if text.casefold().endswith(ext):
            text = text[:-len(ext)]
            removed_ext = ext
            break

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

    # If an extension was removed, append it back
    text += removed_ext

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


# Mapping of unit aliases (all in lowercase) to their equivalent in seconds
_UNIT_SECONDS = {
    **dict.fromkeys(['year', 'years', 'yr', 'yrs', 'calendar year', 'calendar years'],    31_556_952),  # Average calender year = 365.2425 days (accounting for leap years)
    **dict.fromkeys(['solar year', 'solar years', 'tropical year', 'tropical years'],     31_556_925.216),  # Average solar/tropical year = 365.24219 solar days = time for Earth to orbit the Sun once relative to the Sun/equinoxes
    **dict.fromkeys(['sidereal year', 'sidereal years'],                                  31_558_149.54),  # Sidereal year = 365.25636 days = time for Earth to orbit the Sun once relative to the "fixed" stars
    **dict.fromkeys(['month', 'months', 'mo', 'mos', 'calendar month', 'calendar months'], 2_629_746.0),  # Average calendar month = 30.436875 solar days
    **dict.fromkeys(['lunar month', 'lunar months', 'synodic month', 'synodic months'],    2_551_442.9),  # Average lunar month (synodic month) = 29.53 solar days
    **dict.fromkeys(['week', 'weeks', 'wk', 'wks'],                                          604_800.0),  # 7 solar days
    **dict.fromkeys(['day', 'days', 'd', 'solar day', 'solar days', 'ephemeris day', 'ephemeris days'], 86_400),  # 24 hours = time for Earth to rotate once relative to the Sun
    **dict.fromkeys(['sidereal day', 'sidereal days'],                                                  86_164.0905),  # 23 hours, 56 minutes, 4.1 seconds = time for Earth to rotate once relative to the "fixed" stars
    **dict.fromkeys(['hour',         'hours',   'hr',  'hrs'],          3600),
    **dict.fromkeys(['minute',       'minutes', 'min', 'mins'],           60),
    **dict.fromkeys(['second',       'seconds', 'sec', 'secs', 's'],    1.00),
    **dict.fromkeys(['decisecond',   'deciseconds',  'ds'],            1E-01),
    **dict.fromkeys(['centisecond',  'centiseconds', 'cs'],            1E-02),
    **dict.fromkeys(['millisecond',  'milliseconds', 'ms'],            1E-03),
    **dict.fromkeys(['microsecond',  'microseconds', 'us', 'μs'],      1E-06),
    **dict.fromkeys(['nanosecond',   'nanoseconds',  'ns'],            1E-09),
    **dict.fromkeys(['picosecond',   'picoseconds',  'ps'],            1E-12),
    **dict.fromkeys(['femtosecond',  'femtoseconds', 'fs'],            1E-15),
    **dict.fromkeys(['attosecond',   'attoseconds',  'as'],            1E-18),
    **dict.fromkeys(['zeptosecond',  'zeptoseconds', 'zs'],            1E-21),
    **dict.fromkeys(['yoctosecond',  'yoctoseconds', 'ys'],            1E-24),
    **dict.fromkeys(['planck time',  'planck times', 'planck', 'plancks', 'pt'], 5.391_247E-44),  # Planck time
    **dict.fromkeys(['decade',       'decades'],                                315_569_252.16),  #   10 solar years
    **dict.fromkeys(['century',      'centuries'],                            3_155_692_521.60),  #  100 solar years
    **dict.fromkeys(['millennium',   'millennia'],                           31_556_925_216.00),  # 1000 solar years
    **dict.fromkeys(['megayear',     'megayears', 'mya', 'myr'],         31_556_925_216_000.00),  # 1E06 solar years
    **dict.fromkeys(['gigayear',     'gigayears', 'gya', 'gyr'],     31_556_925_216_000_000.00),  # 1E09 solar years
    **dict.fromkeys(['terayear',     'terayears', 'tya', 'tyr'], 31_556_925_216_000_000_000.00),  # 1E12 solar years
    **dict.fromkeys(['fortnight',    'fortnights'],                               1_209_600.00),  # 2 weeks = 604_800 * 2 seconds
    **dict.fromkeys(['decasecond',   'decaseconds',   'das'], 1E01),
    **dict.fromkeys(['hectosecond',  'hectoseconds',  'hs'],  1E02),
    **dict.fromkeys(['kilosecond',   'kiloseconds',   'ks'],  1E03),
    **dict.fromkeys(['megasecond',   'megaseconds'],          1E06),  # no Ms because .lower() would convert it to ms
    **dict.fromkeys(['gigasecond',   'gigaseconds',   'gs'],  1E09),
    **dict.fromkeys(['terasecond',   'teraseconds',   'ts'],  1E12),
    **dict.fromkeys(['petasecond',   'petaseconds'],          1E15),  # no Ps because .lower() would convert it to ps
    **dict.fromkeys(['exasecond',    'exaseconds',    'es'],  1E18),
    **dict.fromkeys(['zettasecond',  'zettaseconds'],         1E21),  # no Zs because .lower() would convert it to zs
    **dict.fromkeys(['yottasecond',  'yottaseconds'],         1E24),  # no Ys because .lower() would convert it to ys
    **dict.fromkeys(['ronnasecond',  'ronnaseconds',  'rs'],  1E27),
    **dict.fromkeys(['quettasecond', 'quettaseconds', 'qs'],  1E30),
}


def seconds_in_unit(unit: str) -> float:
    """Return the number of seconds in a given time unit."""
    try:
        return _UNIT_SECONDS[unit.lower()]
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
    # …add any others you need
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

    import datetime as dt

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
        if up in ('Z', 'UTC', 'GMT') and len(s) <= 3:
            return dt.timezone.utc

        # Strip leading "UTC" or "GMT" prefix
        if up.startswith(('UTC', 'GMT')):
            rest = s[3:].strip()
            if rest == '':
                return dt.timezone.utc
            s = rest  # now s begins with + or -

        # Try fixed-offset patterns
        m = _TZ_OFFSET_RE.fullmatch(s)
        if m:
            sign = 1 if m.group('sign') == '+' else -1

            if m.group('hours1') is not None:
                hours = int(m.group('hours1'))
                minutes = int(m.group('mins1'))
            elif m.group('hours1_only') is not None:
                hours = int(m.group('hours1_only'))
                minutes = 0
            elif m.group('hours2') is not None:
                hours = int(m.group('hours2'))
                minutes = int(m.group('mins2'))
            elif m.group('hours3') is not None:
                hours = int(m.group('hours3'))
                minutes = int(m.group('mins3'))
            else:
                hours = int(m.group('hours4'))
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
    import datetime as dt
    if use_astropy:
        try:
            from astropy.time import Time
        except ImportError as e:
            raise ValueError(f"'use_astropy=True' requires the astropy package: {e}") from e
        t = Time(dec, format='jyear', scale='utc')
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
        raise ValueError(f"Invalid ISO8601 date '{given_date}': {e}") from e


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

# Enclose the type alias annotation in quotes because not all of these types have been imported yet.
AnyDateTimeType: TypeAlias = "str | float | int | np.datetime64 | pd.Timestamp | dt.datetime"


def _should_convert(given_date: AnyDateTimeType, format_str: str | None = None) -> bool:
    """Determine if the given date should be converted to a timezone (i.e. if the wall clock should be shifted) or if the timezone should just be attached without shifting the clock."""
    import datetime as dt

    # 1) Numbers, JD/MJD, decimal years, special keywords
    if isinstance(given_date, (int, float)) and not isinstance(given_date, bool):
        logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Given date is a number: {given_date}, so it will be converted by shifting the clock")
        return True
    if isinstance(given_date, str):
        u = given_date.strip().upper()
        if u in ('J2000', 'UNIX', 'NOW'):
            logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Given date is a special keyword: {u}, so it will be converted by shifting the clock")
            return True
        if format_str and format_str.upper() in ('JD', 'MJD'):
            logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Given date has a format_str: {format_str}, so it will be converted by shifting the clock")
            return True
        if _JD_MJD_SIMPLE_RE.fullmatch(given_date):
            logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Given date is a JD/MJD: {given_date}, so it will be converted by shifting the clock")
            return True
        # explicit offset or Z
        if _OFFSET_IN_STR_RE.search(given_date):
            logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Given date has an explicit offset or Z: {given_date}, so it will be converted by shifting the clock")
            return True
    # 2) Any datetime/timestamp already aware
    if isinstance(given_date, dt.datetime) and given_date.tzinfo is not None:
        logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Given date is an aware datetime: {given_date}, so it will be converted by shifting the clock")
        return True

    # Otherwise treat it as local‐time → attach only
    logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Given date is not a number, JD/MJD, or aware datetime: {given_date}, so the timezone will be attached without shifting the clock")
    return False


def _finalize_datetime(parsed_dt: dt.datetime, original_input: AnyDateTimeType,
                       format_str: str | None, tz_arg: str | dt.tzinfo | None,
                       should_convert: bool | None = None) -> dt.datetime:
    """Finalize the datetime object by either converting it to the target timezone or just attaching the timezone without shifting the clock. The boolean argument 'should_convert' can override the default behavior, which is determined by the function _should_convert()."""
    if isinstance(tz_arg, str) and tz_arg.strip().upper() == 'NAIVE':
        logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Naive timezone requested, returning datetime {parsed_dt} without any timezone info")
        return parsed_dt.replace(tzinfo=None)
    target_tz = parse_timezone(tz_arg)
    if should_convert is not False and (_should_convert(original_input, format_str) or should_convert is True):
        logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Converting datetime {parsed_dt} to timezone {target_tz} by shifting the clock")
        return parsed_dt.astimezone(target_tz)
    else:
        logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Attaching timezone {target_tz} to datetime {parsed_dt} without shifting the clock")
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
        given_date:     The date to parse, which can be a string, float, int, numpy.datetime64, pandas.Timestamp, or datetime.datetime object.
        timezone:       A string or datetime.tzinfo object representing the timezone to convert the datetime to. If None, defaults to UTC.
        format_str:     A string indicating the format of the date. If None, the function will try to infer the format from the given_date.
        should_convert: A boolean indicating whether to convert the datetime to the specified timezone by shifting the clock (True) or
                        just attaching the timezone without shifting (False). If None, the function will determine this based on the type of
                        given_date and format_str.
    
    Returns:
        datetime.datetime object in the specified timezone.
        Note that datetime.datetime objects cannot represent dates before 1 January 1, 0001 or after 31 December 9999.
        So dates outside this range will raise a ValueError. Future versions of this code may support a wider range of dates (like 44 BC, 44 BCE, etc.) using libraries like 'astropy.time': https://chatgpt.com/share/685c5157-5cac-8006-b68c-4a0731927a50
        However, this will require the function to return an 'astropy.time.Time' object instead of a 'datetime.datetime' object.

    Raises:
        ValueError:  If the given_date cannot be parsed into a datetime object, or if the timezone is invalid.
        TypeError:   If the given_date is not a string, float, int, numpy.datetime64, pandas.Timestamp, or datetime.datetime object.
        ImportError: If the 'jdcal' library is not installed and the given_date is a Julian Date or Modified Julian Date.
    """
    import datetime as dt
    fallback_logging_config()  # Ensure logging is configured

    parsed_tz = parse_timezone(timezone)  # Ensure timezone is a valid tzinfo object or string

    parsed_dt = None

    # Handle special cases:
    if isinstance(given_date, str):
        if given_date.strip().upper() == 'J2000':
            # J2000 is January 1, 2000, 11:58:55.816 UTC
            parsed_dt = dt.datetime(2000, 1, 1, 11, 58, 55, 816_000, tzinfo=dt.timezone.utc)
        if given_date.strip().upper() == 'UNIX':
            # UNIX epoch is January 1, 1970, 00:00:00 UTC
            parsed_dt = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        if given_date.strip().upper() == "NOW":
            parsed_dt = dt.datetime.now(tz=dt.timezone.utc)

    # Handle forced or explicit Julian Date (JD) or Modified Julian Date (MJD)
    m = None
    prefix = None
    if parsed_dt is None and isinstance(given_date, str):
        m = _JD_MJD_CAPTURE_RE.fullmatch(given_date)
        if m:
            prefix = m.group('prefix')

    # Trigger JD/MJD branch only if format_str equals "JD" or "MJD", or prefix was provided
    if parsed_dt is None and (prefix is not None or (format_str and (format_str.upper() == 'JD' or format_str.upper() == 'MJD'))):

        try:
            import jdcal
        except ImportError:
            raise ImportError("The jdcal python library is required to parse Julian/MJD dates")

        # Determine raw value
        if isinstance(given_date, (int, float)):
            value = float(given_date)
        else:
            value = float(m.group('value'))

        # Determine if MJD conversion needed
        use_mjd = bool((format_str and format_str.upper() == 'MJD') or (prefix and prefix.upper() == 'MJD'))

        # Convert MJD to JD if necessary
        jd_val = value + (2_400_000.5 if use_mjd else 0.0)

        # Split into integer day and fraction
        int_part = int(jd_val)
        frac_part = jd_val - int_part
        year, month, day, day_frac = jdcal.jd2gcal(int_part, frac_part)

        # Convert day fraction to hours, minutes, seconds, microseconds
        day_int = int(day)
        frac_of_day = (day + day_frac) - day_int
        hours = int(frac_of_day * 24)
        mins = int((frac_of_day * 24 - hours) * 60)
        secs_frac = (frac_of_day * 24 - hours) * 60 - mins
        secs = int(secs_frac * 60)
        micros = int((secs_frac * 60 - secs) * 1e6)
        parsed_dt = dt.datetime(year, month, day_int, hours, mins, secs, micros, tzinfo=dt.timezone.utc)

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
            logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Parsing date with format string: '{format_str}' split into parts: {format_parts}")
            if len(format_parts) > 3:
                raise ValueError(f"Invalid format string: '{format_str}'. Expected at most three parts: 'units', 'since/after', and 'epoch'.")
            # The first part should be acceptable by seconds_in_unit():
            try:
                units = format_parts[0].strip()
                multiplier = seconds_in_unit(units)  # This will raise ValueError if the unit is unknown
            except ValueError as e:
                raise ValueError(f"Invalid time unit '{units}' in format string '{format_str}': {e}") from e
            # If the format_parts list has only one part, it means the epoch defaults to the Unix epoch (1970-01-01T00:00:00Z).
            if len(format_parts) == 1:
                # If the format_parts list has only one part, it means the format is just "units" (e.g. "days", "weeks", etc.)
                # In this case, we assume the epoch is the Unix epoch (1970-01-01T00:00:00Z).
                epoch_str = '1970-01-01T00:00:00Z'
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
            ts_ns = given_date.astype('datetime64[ns]').astype('int64')
            parsed_dt = dt.datetime.fromtimestamp(ts_ns/1e9, tz=parsed_tz)

    if parsed_dt is None:
        try:
            import pandas as pd
        except ImportError:
            pd = None
        if pd is not None and isinstance(given_date, pd.Timestamp):
            parsed_dt = given_date.to_pydatetime()

    error_message = f"The date '{given_date}' is type {type(given_date).__name__!r} in an unknown format. Please use NOW, YYYY, YYYY-MM, YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, other ISO8601 strings, or a decimal year like 2002.291. Datetimes in pandas.Timestamp, numpy.datetime64, or datetime.datetime formats are also accepted and will be converted to datetime.datetime objects in the specified timezone ({parsed_tz})."

    if parsed_dt is None and not isinstance(given_date, str):
        raise TypeError(error_message)

    if parsed_dt is None and format_str is not None:
        try:
            parsed_dt = dt.datetime.strptime(given_date, format_str)
        except ValueError as e:
            raise ValueError(f"Invalid date format '{given_date}' with specified format '{format_str}': {e}") from e

    # Try parsing the date string in various formats
    # Start with RFC 2822 format, then ISO8601, then free-form strings
    # Store any errors encountered in a list to provide feedback if all parsing attempts fail.
    errors = []

    if parsed_dt is None:
        import email.utils
        try:
            # parses "Tue, 25 Jun 2025 14:00:00 GMT"
            parsed_dt = email.utils.parsedate_to_datetime(given_date)
        except (TypeError, ValueError) as e:
            errors.append(f"Failed to parse '{given_date}' as an RFC 2822 date: {e}")

    if parsed_dt is None:
        try:
            parsed_dt = _parse_iso(given_date)
        except ValueError as e:
            errors.append(f"Failed to parse '{given_date}' as an ISO8601 date: {e}")

    if parsed_dt is None:
        try:
            from dateutil.parser import parse as parse_fuzzy
            parsed_dt = parse_fuzzy(given_date, default=dt.datetime(1900, 1, 1))
        except ValueError as e:
            errors.append(f"Failed to parse '{given_date}' as a free-form date string: {e}")

    if parsed_dt is None:
        if np is None:
            errors.append("The numpy package is not installed, so numpy.datetime64 objects cannot be parsed.")
        if pd is None:
            errors.append("The pandas package is not installed, so pandas.Timestamp objects cannot be parsed.")
    else:
        # Finalize the datetime object by converting it to the target timezone or just attaching the timezone without shifting the clock
        return _finalize_datetime(parsed_dt, given_date, format_str, parsed_tz, should_convert)

    raise ValueError(error_message + "\n".join(errors) + "\nPlease check the input format and try again.")


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
        text:        Original filename or title
        sep:         Single-character separator (default: "_")
        max_length:  If set, strongest‐effort truncate to this many chars

    Returns:
        A clean, filename-safe string.
    """
    fallback_logging_config()  # Ensure logging is configured
    # 1. Normalize to ASCII
    try:
        import unidecode
        text = unidecode.unidecode(text)
    except ImportError:
        logging.warning("unidecode package not found, falling back to ASCII encoding.")
        # Fallback: encode to ASCII, ignore errors
        text = text.encode('ascii', 'ignore').decode('ascii')

    # 2. Replace common "word boundaries" with sep
    #    (dots, underscores, whitespace) but keep dashes
    #    e.g. "hello.world--foo_bar" → "hello world--foo bar"
    text = re.sub(r"[._\s]+", sep, text)

    # 3. Remove anything but dashes, a–z, 0–9, or our sep
    allowed = f"-A-Za-z0-9{re.escape(sep)}"
    text = re.sub(fr"[^{allowed}]+", "", text)

    # 4. Collapse runs of sep (e.g. "__" → "_")
    text = re.sub(fr"{re.escape(sep)}{{2,}}", sep, text)

    # 5. Strip leading/trailing seps
    text = text.strip(sep)

    # 6. Optionally truncate (try not to cut in middle of a word)
    if max_length is not None and len(text) > max_length:
        # cut at max_length, then drop a partial trailing token if any
        truncated = text[:max_length]
        # if the next char in original isn't sep and our chop landed mid-token, trim back to last sep
        if (len(text) > max_length and not truncated.endswith(sep) and sep in truncated):
            truncated = truncated.rsplit(sep, 1)[0]
        text = truncated

    return text

# A comprehensive list of python extensions.
python_extensions: list[str] = ['.py', '.pyw']
python_extensions = [e.casefold() for e in python_extensions]  # Just in... case.

# A comprehensive list of text file extensions.
text_extensions: list[str] = [
    '.txt',  '.html',     '.htm',      '.csv',        '.json', '.xml'
    '.adoc', '.asciidoc', '.bib',      '.cfg',        '.conf', '.ini',
    '.log',  '.md',       '.markdown', '.properties', '.rtf',  '.rst',
    '.sgm',  '.sgml',     '.tex',      '.toml',       '.tsv',  '.xhtml',
    '.yaml', '.yml',
]
text_extensions = [e.casefold() for e in text_extensions]  # Just in... case.

# A comprehensive list of video file extensions.
video_extensions: list[str] = [
    '.mp4',   '.mkv',   '.mov',   '.avi',  '.mpg',  '.mpeg',
    '.wmv',   '.m4v',   '.flv',   '.divx', '.vob',  '.iso',
    '.3gp',   '.webm',  '.mts',   '.m2ts', '.ts',   '.ogv',
    '.rm',    '.rmvb',  '.asf',   '.f4v',  '.mxf',  '.dv',
    '.swf',   '.m2v',   '.svi',   '.mpe',  '.ogm',  '.bik',
    '.xvid',  '.yuv',   '.qt',    '.gvi',  '.viv',  '.fli',
    '.mjpg',  '.mjpeg', '.amv',   '.drc',  '.flc',  '.wve',
    '.avchd', '.vp6',   '.ivf',   '.mps',  '.vro',  '.ssf',
    '.hevc',  '.h265',  '.264',   '.str',  '.evo',  '.3g2',
    '.h264',  '.av1',   '.ogx',   '.mlv',  '.ps',   '.tsx',
    '.mp2v',  '.dvs',   '.gxf',   '.m4p',  '.webp', '.vp8',
    '.trp',   '.f4p',   '.f4b',   '.f4m',  '.mk3d', '.3mm',
    '.3gpp',  '.mod',   '.tod',   '.cine', '.arf',  '.wrf',
    '.braw',  '.jmf',   '.r3d',   '.dpx',  '.mpv',  '.tsv',
    '.rmx',   '.smk',   '.mkd',   '.mj2',  '.scm',  '.ivr',
    '.xesc',  '.wtv',   '.dcr',   '.mpl',  '.pds',  '.ismv',
    '.vc1',   '.vcd',   '.mpcpl', '.bin',  '.sfd',  '.qtz',
    '.vdat',  '.vft',
]
video_extensions = [e.casefold() for e in video_extensions]  # Just in... case.

# A comprehensive list of audio file extensions.
audio_extensions: list[str] = [
    '.mp3',   '.wav',   '.flac',  '.aac',   '.ogg',   '.wma',
    '.m4a',   '.alac',  '.aiff',  '.opus',  '.amr',   '.pcm',
    '.au',    '.raw',   '.dts',   '.ac3',   '.mka',   '.mpc',
    '.vqf',   '.ape',   '.shn',   '.ra',    '.rm',    '.oga',
    '.spx',   '.caf',   '.snd',   '.mid',   '.midi',  '.kar',
    '.rmi',   '.m3u',   '.pls',   '.xspf',  '.asf',   '.wv',
    '.aa',    '.aax',   '.dsf',   '.dff',   '.sf2',   '.g721',
    '.voc',   '.swa',   '.bwf',   '.ivs',   '.smp',   '.htk',
    '.sds',   '.brstm', '.adx',   '.hca',   '.ast',   '.psf',
    '.psf2',  '.qsf',   '.ssf',   '.usf',   '.gsf',   '.flp',
    '.dsm',   '.dmf',   '.mod',   '.s3m',   '.it',    '.xm',
    '.mt2',   '.mo3',   '.umx',   '.tt',    '.tak',   '.trk',
    '.669',   '.abc',   '.ts',    '.ym',    '.hsq',   '.mpa',
]
audio_extensions = [e.casefold() for e in audio_extensions]  # Just in... case.

# A comprehensive list of subtitle file extensions.
subtitle_extensions: list[str] = [
    '.srt',   '.sub',    '.idx',   '.ass',   '.ssa',   '.vtt',
    '.ttml',  '.dfxp',   '.smi',   '.smil',  '.usf',   '.psb',
    '.mks',   '.lrc',    '.stl',   '.pjs',   '.rt',    '.aqt',
    '.gsub',  '.jss',    '.dks',   '.mpl2',  '.tmp',   '.vsf',
    '.zeg',   '.webvtt', '.scc',   '.cap',   '.asc',   '.qt.txt',  # match .qt.txt before .txt
    '.sbv',   '.ebu',    '.sami',  '.xml',   '.itt',   '.txt',
]
subtitle_extensions = [e.casefold() for e in subtitle_extensions]  # Just in... case.

# A comprehensive list of image file extensions.
image_extensions: list[str] = [
    '.bmp',   '.dib',   '.gif',   '.jpeg',  '.jpg',   '.jpe',
    '.jfif',  '.pjpeg', '.pjp',   '.png',   '.pbm',   '.pgm',
    '.ppm',   '.pnm',   '.pam',   '.tif',   '.tiff',  '.sgi',
    '.rgb',   '.tga',   '.hdr',   '.exr',   '.webp',  '.apng',
    '.heic',  '.heif',  '.avif',  '.jp2',   '.j2k',   '.j2c',
    '.jxr',   '.svg',   '.svgz',  '.eps',   '.ai',    '.pdf',
    '.cdr',   '.emf',   '.wmf',   '.dxf',   '.dwg',   '.mng',
    '.raw',   '.arw',   '.cr2',   '.cr3',   '.dng',   '.erf',
    '.raf',   '.orf',   '.pef',   '.rw2',   '.rwl',   '.sr2',
    '.srw',   '.3fr',   '.kdc',   '.mrw',   '.mos',   '.nrw',
    '.pcx',   '.pcd',   '.pic',   '.pct',   '.xcf',   '.psd',
    '.psb',   '.kra',   '.fit',   '.fits',  '.fpx',   '.djvu',
    '.djv',   '.lbm',   '.iff',
]
image_extensions = [e.casefold() for e in image_extensions]  # Just in... case.

# A comprehensive list of archive file extensions.
archive_extensions: list[str] = [
    '.zip',     '.rar',    '.7z',    '.tar.gz', '.tar.bz2', '.tar.xz',  # match .tar.(gz,bz2,xz) before (.gz,.bz2,.xz)
    '.tar.zst', '.tar',    '.gz',    '.tgz',    '.bz2',     '.xz',
    '.tbz2',    '.tz2',    '.lzma',  '.lz',     '.xpi',     '.crx',
    '.zst',     '.cab',    '.arj',   '.ace',    '.uue',     '.zoo',
    '.jar',     '.war',    '.ear',   '.iso',    '.img',     '.dmg',
    '.lzh',     '.lha',    '.cpio',  '.deb',    '.rpm',     '.apk',
    '.pak',     '.arc',    '.a',     '.mar',    '.b1',      '.wim',
    '.shar',    '.run',    '.shk',   '.sit',    '.sitx',    '.zpaq',
    '.br', 
]
archive_extensions = [e.casefold() for e in archive_extensions]  # Just in... case.

# Put subtitle_ext before text_ext so .qt.txt matches before .txt
all_known_extensions: list[str] = python_extensions + subtitle_extensions + \
                                  text_extensions   + video_extensions    + \
                                  audio_extensions  + image_extensions    + \
                                  archive_extensions


if __name__ == "__main__":
    main()
