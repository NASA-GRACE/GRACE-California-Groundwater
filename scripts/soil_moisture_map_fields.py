#!/usr/bin/env python3
# Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), and GitHub Copilot (it/its).

import os
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import subprocess
from pathlib import Path
import logging
import datetime as dt
import argparse

import run_all as ra

# Suppress this warning: ~/repo/GRACE-California-Groundwater/scripts/.pixi/envs/default/lib/python3.12/site-packages/shapely/creation.py:730: RuntimeWarning: invalid value encountered in create_collection
import warnings
warnings.filterwarnings(
    "ignore",
    category=RuntimeWarning,
    message="invalid value encountered in create_collection",
    module=r"shapely(\..*)?",
)


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                  str = Path(__file__).stem  # The name of this script without the .py extension
        self.thevar:                   str = "SMTa"  # variable name in the netCDF file
        self.default_masked_dir:      Path = self.project_root / "input_data" / "masked_timeseries"
        self.default_masked_filepath: Path = self.default_masked_dir / f"LATEST_{self.thevar}.nc"

        self.default_cmap:             str = "RdBu"
        self.default_map_border:     float =  -1.0  # degrees to pad around data; negative disables auto-zoom
        self.default_central_lon:    float = 180.0  # central longitude for PlateCarree projection


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description=f"Make maps of soil moisture anomaly ({options.thevar}) from netCDF")
    parser.add_argument("-masked_dir", type=Path, default=options.default_masked_dir,
                        help=f"Path to the input masked timeseries directory (default: {options.default_masked_dir})")
    parser.add_argument("-nc_path", type=Path, default=options.default_masked_filepath,
                        help=f"Name of the input netCDF file")
    parser.add_argument("-out_dir", type=Path, default=options.graphics_dir,
                        help=f"Output directory for PNG files (default: {options.graphics_dir})")
    parser.add_argument("-cmap", type=str, default=options.default_cmap,
                        help=f"Matplotlib colormap (default: {options.default_cmap})")
    parser.add_argument("-map_border", type=float, default=options.default_map_border,
                        help=f"Degrees to pad around data for auto-zoom; negative disables (default: {options.default_map_border})")
    parser.add_argument("-central_lon", type=float, default=options.default_central_lon,
                        help=f"Central longitude for PlateCarree projection (default: {options.default_central_lon})")
    parser.add_argument("--full", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    options.args.masked_dir.mkdir(    parents=True, exist_ok=True)
    options.args.out_dir.mkdir(       parents=True, exist_ok=True)
    options.args.nc_path.parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Main function to parse arguments and call plotting functions."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    if options.soil_moisture_model == "NLDAS":
        map_fields_for_NLDAS(options)
    else:
        raise ValueError(f"Unsupported soil moisture model: {options.soil_moisture_model}")


def map_fields_for_NLDAS(options: Options) -> None:
    """
    Make soil moisture anomaly maps from NLDAS masked timeseries netCDF.

    Args:
        options: An Options instance with all necessary parameters.

    Returns:
        None. Generates PNG maps and a movie.

    Raises:
        None.
    """
    if logging.getLogger().isEnabledFor(logging.DEBUG): logging.debug(f"cmap={options.args.cmap}, map_border={options.args.map_border}, central_lon={options.args.central_lon}")

    if options.args.nc_path == options.default_masked_filepath:
        # Look for the latest netCDF file in the masked timeseries directory
        matches = list(options.args.masked_dir.glob("*.nc*"))
        if not matches:
            raise FileNotFoundError(f"No .nc files found in {options.args.masked_dir}")
        options.args.nc_path = max(matches, key=os.path.getctime)
        logging.info(f"Using latest netCDF file: {options.args.nc_path}")

    # Extract the part of the filename between "soil moisture model_" (e.g. "NLDAS_") and the date:
    themask = options.args.nc_path.name.split(f"{options.soil_moisture_model}_")[1].split("_mask_")[0] \
                  if f"{options.soil_moisture_model}_" in options.args.nc_path.name \
                  else ""

    # Set up output path if it doesn't exist already.
    options.args.out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_png   = options.args.out_dir / f"{options.thevar}_map_{timestamp}.png"
    suffix = f"_{themask}" if themask else ""
    out_movie = options.args.out_dir / f"{options.thevar}_movie{suffix}_{timestamp}.mp4"

    # Create a frames directory if it doesn't exist already.
    frames_dir = options.args.out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    plot_kwargs = {
        "vmin": None,
        "vmax": None,
        # you can also pass "extent": [lon_min, lon_max, lat_min, lat_max]
    }

    # Plot mean of thevar (now supports an optional extent if you want to zoom)
    plot_mean_nc_var(options, options.args.nc_path, options.thevar, out_png, **plot_kwargs)

    # Plot thevar at a specific time (uncomment and adjust time_index if needed)
    # plot_nc_var_at_time(options, options.args.nc_path, thevar, out_png, time_index=0, **plot_kwargs)

    # Make a movie of all time slices of thevar
    make_nc_var_movie(options, options.args.nc_path, options.thevar, out_movie, frames_dir, fps=10, **plot_kwargs)

    # If you want to remove frames afterward, uncomment:
    # for png in os.listdir(frames_dir):
    #     Path(frames_dir / png).unlink(missing_ok=True)


def plot_nc_var(options: Options, data2d: np.ndarray, thevar: str, lons: np.ndarray, lats: np.ndarray, out_png: str | os.PathLike[str],
                ds_units: str, title: str, vmin: float = None, vmax: float = None, extent: list = None) -> None:
    """
    Generic 2D plotting routine.

    Args:
        options:     Options object containing configuration settings
        data2d:      2‐D array of shape (lat, lon)
        thevar:      name of the variable (for labeling purposes)
        lons, lats:  1‐D arrays of longitudes and latitudes (in degrees)
        out_png:     output filename (for the PNG)
        ds_units:    units string for thevar (to label the colorbar)
        title: title string for the map
        vmin, vmax:  optional color‐scale bounds (if None, will use symmetric ±max(|data|))
        extent:      [lon_min, lon_max, lat_min, lat_max] (in degrees). If provided, zooms to that box.

    Returns:
        None. The PNG file is created.

    Raises:
        None.
    """
    # Determine symmetric color limits if not given
    if vmin is None or vmax is None:
        maxabs = np.nanmax(np.abs(data2d))
        if not np.isfinite(maxabs) or maxabs == 0:
            # Fallback to a benign range and warn
            logging.warning("Data are all-NaN or zero; using default color scale [-1, 1].")
            vmin, vmax = -1.0, 1.0
        else:
            vmin, vmax = -maxabs, maxabs

    # Set up the figure + map
    fig, ax = plt.subplots(
        figsize=(12, 6),
        subplot_kw={"projection": ccrs.PlateCarree(central_longitude=options.args.central_lon)}
    )
    ax.coastlines("110m", linewidth=0.5)
    ax.add_feature(cfeature.LAND,    facecolor="lightgray")
    ax.add_feature(cfeature.OCEAN,   facecolor="white")
    ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.5)
    ax.add_feature(cfeature.STATES,  linestyle=":", linewidth=0.5)

    if extent is not None:
        ax.set_extent(extent, crs=ccrs.PlateCarree())

    pcm = ax.pcolormesh(lons, lats, data2d, transform=ccrs.PlateCarree(),
                        cmap=options.args.cmap, vmin=vmin, vmax=vmax)
    cbar = fig.colorbar(pcm, ax=ax, orientation="vertical", pad=0.02)
    cbar.set_label(f"{thevar} ({ds_units})")

    ax.set_title(title)
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_mean_nc_var(options: Options, nc_path: str | os.PathLike[str], thevar: str, out_png: str | os.PathLike[str], *,
                     vmin: float = None, vmax: float = None, extent: list = None) -> None:
    """
    Compute the time‐mean of thevar and plot it with plot_nc_var().

    Args:
        options:                       Options object containing configuration settings
        nc_path:                       Path to input netCDF file
        thevar:                        Variable name in the netCDF file
        out_png:                       Output PNG filename
        vmin, vmax:                    Passed through to plot_nc_var()
        extent:                        Optional [lon_min, lon_max, lat_min, lat_max] to zoom in

    Returns:
        None. The PNG file is created.

    Raises:
        None.
    """
    ds = xr.open_dataset(nc_path, decode_times=True)
    mean_var = ds[thevar].mean(dim="time").values  # 2D array (lat, lon)
    lons = ds['lon'].values
    lats = ds['lat'].values
    units = ds[thevar].attrs.get('units', '')

    title = f"Time‐mean Soil Moisture Anomaly ({thevar})"
    plot_nc_var(options, data2d=mean_var, thevar=thevar, lons=lons, lats=lats, out_png=out_png,
                ds_units=units, title=title, vmin=vmin, vmax=vmax, extent=extent)


def plot_nc_var_at_time(options: Options, nc_path: str | os.PathLike[str], thevar: str, out_png: str | os.PathLike[str],
                        time_index: int, vmin: float = None, vmax: float = None, extent: list = None) -> None:
    """
    Plot thevar at a single time slice by index.

    Args:
        options:                       Options object containing configuration settings
        nc_path:                       Path to input netCDF file
        thevar:                        Variable name in the netCDF file
        out_png:                       Output PNG filename
        time_index:                    Integer index along the "time" dimension
        vmin, vmax:                    Passed through to plot_nc_var()
        extent:                        Optional [lon_min, lon_max, lat_min, lat_max] to zoom in

    Returns:
        None. The PNG file is created.

    Raises:
        None.
    """
    ds     = xr.open_dataset(nc_path, decode_times=True)
    var_da = ds[thevar].isel(time=time_index)
    data2d = var_da.values  # 2D array (lat, lon)
    lons   = ds['lon'].values
    lats   = ds['lat'].values
    units  = ds[thevar].attrs.get('units', '')

    # Derive date string for the title
    date_val = var_da['time'].values
    date_str = np.datetime_as_string(date_val, unit="D")
    title    = f"Soil Moisture Anomaly on {date_str}"

    plot_nc_var(options, data2d=data2d, thevar=thevar, lons=lons, lats=lats, out_png=out_png,
                ds_units=units, title=title, vmin=vmin, vmax=vmax, extent=extent)

    # Ensure even dimensions if required by downstream tools
    ra.ensure_even_dimensions(out_png)


def make_nc_var_movie(options: Options, nc_path: str | os.PathLike[str], thevar: str,
                      movie_path: str | os.PathLike[str], frames_dir: str | os.PathLike[str], *,
                      fps: int = 10, vmin: float = None, vmax: float = None) -> None:
    """
    Loop over all time slices, save PNGs into frames_dir, then call ffmpeg.

    Args:
        options:                       Options object containing configuration settings
        nc_path:                       Path to input netCDF file
        thevar:                        Variable name in the netCDF file
        movie_path:                    Output movie file path
        frames_dir:                    Directory to save individual frame PNGs
        fps:                           Frames per second for the movie
        vmin, vmax:                    Passed through to plot_nc_var()

    Returns:
        None. The movie file is created.

    Raises:
        None.
    """
    os.makedirs(frames_dir, exist_ok=True)
    # Remove any existing frames
    for png in os.listdir(frames_dir):
        Path(frames_dir / png).unlink(missing_ok=True)

    ds = xr.open_dataset(nc_path, decode_times=True)
    nt = ds.sizes['time']

    # ------------------------------------------------------------
    # Compute geographic extent from the first frame
    first_var = ds[thevar].isel(time=0).values
    lons = ds['lon'].values
    lats = ds['lat'].values

    idx = np.where(~np.isnan(first_var))
    if idx[0].size > 0 and options.args.map_border > 0:  # map_border < 0 means no zoom
        lat_idxs = idx[0]
        lon_idxs = idx[1]
        lat_min = float(lats[lat_idxs.min()] - options.args.map_border)
        lat_max = float(lats[lat_idxs.max()] + options.args.map_border)
        lon_min = float(lons[lon_idxs.min()] - options.args.map_border)
        lon_max = float(lons[lon_idxs.max()] + options.args.map_border)
        extent = [lon_min, lon_max, lat_min, lat_max]
    else:
        extent = None
    # ------------------------------------------------------------

    # Find a common color scale across all times unless vmin/vmax given
    if vmin is None or vmax is None:
        all_data = ds[thevar].values.reshape((nt, -1))
        maxabs = np.nanmax(np.abs(all_data))
        vmin_all, vmax_all = -maxabs, maxabs
    else:
        vmin_all, vmax_all = vmin, vmax

    for tidx in range(nt):
        png = frames_dir / f"frame_{tidx:03d}.png"
        plot_nc_var_at_time(options, nc_path, thevar, png, time_index=tidx, vmin=vmin_all, vmax=vmax_all, extent=extent)
        logging.info(f"Saved frame {tidx+1}/{nt} to {png}")

    # Assemble movie (only if ffmpeg is available)
    ffmpeg_path_str = ra.find_ffmpeg()
    if not ffmpeg_path_str:
        logging.warning("ffmpeg not found (PATH/env/common locations). Skipping movie creation. "
                        f"Frames are in {frames_dir}")
        return
    cmd = [
        ffmpeg_path_str,
        "-y",
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", os.fspath(frames_dir / "frame_%03d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        os.fspath(movie_path),
    ]
    subprocess.run(cmd, check=True)
    logging.info(f"Movie saved to {movie_path}")


if __name__ == "__main__":
    main()
