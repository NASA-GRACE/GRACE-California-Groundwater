#!/usr/bin/env python3
"""
Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), and GitHub Copilot (it/its).
This program computes water storage anomalies within a polygon’s footprint from a
concatenated soil moisture (e.g. NLDAS) netCDF file. It outputs both a CSV file containing the region’s
mean anomaly time series and a NetCDF file with the corresponding subset anomalies.
Adapted from the original shbaam_ldas_anoms.py script.
"""

import os
from pathlib import Path
import sys
import argparse
import logging
import datetime as dt
import numpy as np
import csv
from netCDF4 import Dataset
import xarray as xr
from pyproj import Geod

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:          Path = Path(__file__).stem  # The name of this script without the .py extension
        self.newvar:            str = "SMTa"  # New variable name for soil moisture
        self.masks_dir:        Path = self.project_root     / "input_data" / "masks"
        self.gridded_data_dir: Path = self.project_root     / "input_data" / "soil_moisture" / self.soil_moisture_model / "data_concatenated"
        self.default_input_nc: Path = self.gridded_data_dir / "LATEST.nc"
        self.default_csv:      Path = self.timeseries_dir   / "anomaly_timeseries_MASK_FILE_CURRENT_DATE.csv"
        self.default_nc:       Path = self.timeseries_dir   / "anomaly_timeseries_MASK_FILE_CURRENT_DATE.nc"
        self.default_mask:     Path = self.masks_dir        / f"{self.soil_moisture_model}_{self.default_basin_safename}_mask.nc"
        self.unit_factors:     dict = {"mm H2O": 1000, "kg/m2": 1000, "kg/m^2": 1000, "cm": 100, "dm": 10, "m": 1, "km": 0.001}  # Conversions from meters to other units.
        self.masks_dir.mkdir(       parents=True, exist_ok=True)


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(
        description="Compute water storage anomalies using a concatenated data netCDF file and a polygon shapefile.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-input_nc", type=Path, default=options.default_input_nc,
                        help=f"Input concatenated data netCDF file (default: {os.fspath(options.default_input_nc)})")
    parser.add_argument("-out_dir", type=Path, default=options.timeseries_dir,
                        help=f"Output directory for CSV and NetCDF files (default: {os.fspath(options.timeseries_dir)})")
    parser.add_argument("-output_csv", type=Path, default=options.default_csv,
                        help=f"Output CSV file for the region mean anomaly time series (default: {os.fspath(options.default_csv)})")
    parser.add_argument("-output_nc", type=Path, default=options.default_nc,
                        help=f"Output netCDF file for gridded and masked data anomalies (default: {os.fspath(options.default_nc)})")
    parser.add_argument("-mask_nc", type=Path, default=options.default_mask,
                        help=f"Input netCDF mask file in {os.fspath(options.masks_dir)} (0/1 values, rows=lat, cols=lon) (default: {os.fspath(options.default_mask)})")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = logging.DEBUG
    options.args.out_dir.mkdir(          parents=True, exist_ok=True)
    options.args.mask_nc.parent.mkdir(   parents=True, exist_ok=True)
    options.args.output_nc.parent.mkdir( parents=True, exist_ok=True)
    options.args.output_csv.parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Main function to compute a water storage anomalies using a river basin mask."""
    options = Options()
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')
    parse_arguments(options)

    if options.soil_moisture_model == "NLDAS":
        mask_timeseries_for_NLDAS(options)
    else:
        raise ValueError(f"Unsupported soil moisture model: {options.soil_moisture_model}")


def mask_timeseries_for_NLDAS(options: Options) -> None:
    """
    Compute water storage anomalies using a river basin mask for NLDAS data.

    Args:
        options: An Options instance with parsed arguments. Contains:
            - args:                Command-line arguments
            - soil_moisture_model: The soil moisture model being used
            - masks_dir:           Directory containing mask files
            - gridded_data_dir:    Directory containing gridded data files
            - default_input_nc:    Default input NetCDF file path
            - default_output_csv:  Default output CSV file path
            - default_output_nc:   Default output NetCDF file path

    Returns:
        None. Creates CSV and NetCDF files as specified in options.
    
    Raises:
        None.
    """
    t_var = "time"  # time variable name
    y_var = "lat"   # latitude variable name
    x_var = "lon"   # longitude variable name

    if options.args.input_nc == options.default_input_nc:
        # Look for the latest concatenated netCDF file
        input_nc_files = list(options.gridded_data_dir.glob("*.nc"))
        if not input_nc_files:
            logging.error(f"No concatenated netCDF files found in {os.fspath(options.gridded_data_dir)}")
            sys.exit(22)
        input_nc_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        options.args.input_nc = options.gridded_data_dir / input_nc_files[0]
    logging.info(f"Input netCDF file: {os.fspath(options.args.input_nc)}")

    # Make sure options.args.mask_nc is a file inside the masks directory with nonzero size.
    options.args.mask_nc = ra.ensure_path_is_a_file(options.args.mask_nc, raise_on_empty=True)

    # Remove extension from mask file name
    mask_file_base = options.args.mask_nc.stem

    if options.args.output_csv == options.default_csv:
        # Create a unique output CSV file name
        options.args.output_csv = options.args.out_dir / f"anomaly_timeseries_{mask_file_base}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    options.args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    logging.info(f"Output CSV file: {os.fspath(options.args.output_csv)}")

    if options.args.output_nc == options.default_nc:
        # Create a unique output NetCDF file name
        options.args.output_nc = options.args.out_dir / f"anomaly_timeseries_{mask_file_base}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.nc"
    options.args.output_nc.parent.mkdir(parents=True, exist_ok=True)
    logging.info(f"Output NetCDF file: {os.fspath(options.args.output_nc)}")

    # Open the netCDF file with xarray
    ds         = xr.open_dataset(options.args.input_nc)
    num_lon    = ds.lon.shape[0]
    num_lat    = ds.lat.shape[0]
    time_steps = ds.time.shape[0]
    lons       = ds.lon.data
    lats       = ds.lat.data

    # Determine grid resolution
    lon_step = abs(float(lons[1]) - float(lons[0]))
    lat_step = abs(float(lats[1]) - float(lats[0]))

    # Process soil moisture data if available
    sum_soil_moisture_by_depth(options,ds)

    var_list = [options.newvar]  # Initialize with new soil moisture variable ONLY
    # Only keep variables that have dims (t_var,y_var,x_var)
    # var_list = [
    #     var for var in ds.data_vars
    #     if set(ds[var].dims) >= {t_var, y_var, x_var}
    # ]

    # Read pre-computed mask (1 = in-region, 0 = out)
    # Read pre-computed mask from NetCDF (1 = in‐region, 0 = out)
    mask_ds   = xr.open_dataset(options.args.mask_nc)
    mask_var  = mask_ds['mask'].data  # should be a 2D array with dims (lat, lon)
    mask_lats = mask_ds[y_var].data
    mask_lons = mask_ds[x_var].data

    # Verify that the mask grid exactly matches the input_nc grid
    if mask_lats.shape != ds.lat.shape or not np.allclose(mask_lats, ds.lat.data):
        raise ValueError("Mask latitude grid does not match input data")
    if mask_lons.shape != ds.lon.shape or not np.allclose(mask_lons, ds.lon.data):
        raise ValueError("Mask longitude grid does not match input data")

    logging.info(f"mask.shape: {mask_var.shape}")
    # Find all (row, col) indices where mask == 1
    coords = np.argwhere(mask_var == 1)
    total_interest = int(coords.shape[0])
    # Build lists of (index, coordinate value) exactly as before
    interest_lon = [(int(col), float(lons[col])) for (row, col) in coords]
    interest_lat = [(int(row), float(lats[row])) for (row, col) in coords]

    # Calculate surface areas for each grid cell of interest
    areas = calculate_surface_area(total_interest, lon_step, lat_step, interest_lat)

    avg_dict = {}
    anomalies_dict = {}

    # Compute anomalies and errors for each variable in the dataset
    for var in var_list:
        logging.info(f"Processing variable: {var}")
        var_data = ds[var].data
        var_units = ds[var].attrs.get('units', 'm')
        var_factor = options.unit_factors.get(var_units, 1)
        # compute both anomalies and errors
        avg = calculate_long_term_avg(var_data, total_interest, interest_lon, interest_lat, time_steps)
        anomalies, errors = compute_anomaly_timeseries(var_data, var_factor, avg, time_steps,
                                                       total_interest,
                                                       interest_lon, interest_lat, areas)
        # store long-term mean (unchanged)
        avg_dict[var] = avg
        # store anomaly series under the original var name
        anomalies_dict[var] = anomalies
        # store error‐bar series under "<var>_error"
        anomalies_dict[f"{var}_error"] = errors

    # Output the computed anomalies to CSV and NetCDF files
    fieldnames = ['date']
    for var in var_list:
        fieldnames.append(var)
        fieldnames.append(f"{var}_error")
    output_csv(options.args.output_csv, fieldnames, ds.time.data, anomalies_dict)

    output_nc(options.args.output_nc, ds, total_interest, interest_lon, interest_lat,
              time_steps, var_list, avg_dict, t_var=t_var, x_var=x_var, y_var=y_var)

    logging.info("Script complete.")


def calculate_long_term_avg(var: np.ndarray, total: int, interest_lon: list[tuple[int, float]],
                            interest_lat: list[tuple[int, float]], time_steps: int) -> list[float]:
    """
    Compute the long-term average value for each grid cell.

    Args:
        var:          3D array (time, lat, lon) for a variable.
        total:        Total number of grid cells of interest.
        interest_lon: List of tuples (lon_index, longitude).
        interest_lat: List of tuples (lat_index, latitude).
        time_steps:   Number of time steps.

    Returns:
        A list of the long-term average for each grid cell.
    
    Raises:
        None.
    """
    avg = [0.0] * total
    for cell in range(total):
        lon_index = interest_lon[cell][0]
        lat_index = interest_lat[cell][0]
        cell_sum = 0.0
        for t in range(time_steps):
            cell_sum += var[t, lat_index, lon_index]
        avg[cell] = cell_sum / time_steps
    logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Long-term averages: {avg}")
    return avg


def calculate_surface_area(total: int, lon_step: float, lat_step: float,
                           interest_lat: list[tuple[int, float]]) -> list[float]:
    """
    Calculate the surface area for each grid cell using the WGS84 ellipsoid.
    Reuses (caches) results for any repeated latitudes.

    Args:
        total:         Total number of grid cells of interest.
        lon_step:      Longitude step size (degrees).
        lat_step:      Latitude step size (degrees).
        interest_lat:  List of tuples (lat_index, latitude).
    
    Returns:
        A list of the surface area for each grid cell.
    
    Raises:
        None.
    """
    geod = Geod(ellps="WGS84")
    half_lon = lon_step / 2.0
    half_lat = lat_step / 2.0

    areas: list[float] = [0.0] * total
    cache: dict[float, float] = {}

    for i in range(total):
        _, lat_center = interest_lat[i]

        # Use rounded latitude as key to avoid float‐precision mismatches:
        key = round(lat_center, 6)
        if key in cache:
            areas[i] = cache[key]
        else:
            # build the four corner coords in lon/lat:
            lons = np.array([-half_lon, half_lon, half_lon, -half_lon])
            lats = np.array([
                lat_center - half_lat,
                lat_center - half_lat,
                lat_center + half_lat,
                lat_center + half_lat,
            ])
            signed_area, _ = geod.polygon_area_perimeter(lons, lats)
            area = abs(signed_area)
            cache[key] = area
            areas[i] = area

    total_km2 = sum(areas) / 1e6
    logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Ellipsoidal surface areas: {areas}")
    logging.info(f"Calculated total surface area of {total_km2:.2f} km² for {total} grid cells.")
    return areas


def sum_soil_moisture_by_depth(options: Options, ds: xr.Dataset) -> None:
    """
    Sum soil moisture over all depths and adjust the dataset.

    Args:
        ds: Input dataset which is modified with soil moisture summed.

    Returns:
        None. The dataset ds is modified in place.

    Raises:
        ValueError: If no soil moisture variable is found or if multiple are found.
    """
    # list all the candidate soil-moisture variables you might have
    soil_moisture_names = ['SoilM_0_100cm']

    # find which of those are actually in ds
    found = [name for name in soil_moisture_names if name in ds.data_vars]

    if len(found) == 1:
        var = found[0]
        if 'depth' in ds[var].dims:
            # sum over the depth dimension and call it options.newvar
            ds[options.newvar] = ds[var].sum(dim='depth')
            ds[options.newvar].attrs['units'] = 'mm H2O'
            # drop the original var and any depth bounds
            ds = ds.drop_vars([var, 'depth_bnds'], errors='ignore')
            logging.info(f"Summed '{var}' by depth into '{options.newvar}'.")
        else:
            ds[options.newvar] = ds[var]
            ds[options.newvar].attrs['units'] = 'mm H2O'
            logging.info(f"'{var}' has no 'depth' dimension; skipping soil-moisture summation.")
    elif len(found) == 0:
        raise ValueError(f"No soil moisture variable found.\nTried: {soil_moisture_names!r};\nAvailable: {list(ds.data_vars)}")
    else:
        # more than one match → ambiguous
        raise ValueError(f"Multiple soil moisture variables found: {found!r}. "
                         f"Please leave only one of {soil_moisture_names!r} in the dataset.")


def compute_anomaly_timeseries(var: np.ndarray, var_factor: float, avg: list[float],
                               time_steps: int, total: int,
                               interest_lon: list[tuple[int, float]],
                               interest_lat: list[tuple[int, float]],
                               areas: list[float]) -> tuple[list[float], list[float]]:
    """
    Compute the water storage anomaly timeseries plus a 10%-error bar for each time step.

    Args:
        var:          3D array (time, lat, lon) for a variable.
        var_factor:   Unit conversion factor (e.g. 1000 to go from mm→m).
        avg:          Long-term average (in same units as var) for each grid cell.
        time_steps:   Number of time steps.
        total:        Total number of grid cells of interest.
        interest_lon: List of (lon_index, longitude).
        interest_lat: List of (lat_index, latitude).
        areas:        Surface area (m²) of each grid cell.

    Returns:
        A tuple of two lists of floats:
            - anomalies: area-weighted anomaly series (in km^3),
            - errors: 10%-of-total-storage error bars (in km^3).
    
    Raises:
        None.
    """
    anomalies = []
    errors = []
    # total_area = sum(areas) # Only used if computing in mm H₂O

    for t in range(time_steps):
        anomaly_sum = 0.0
        storage_sum = 0.0  # total volume (m³) before subtracting mean

        for cell in range(total):
            lon_index = interest_lon[cell][0]
            lat_index = interest_lat[cell][0]
            long_term_mean = avg[cell]
            cell_area = areas[cell]
            cell_value = var[t, lat_index, lon_index]

            # skip if the data is missing
            if np.isnan(cell_value):
                continue

            # accumulate total storage (convert var to meters, multiply by area → m³)
            storage_sum += (cell_value / var_factor) * cell_area

            # compute anomaly‐volume (var − mean), convert to m, then multiply area
            delta = (cell_value - long_term_mean) / var_factor * cell_area
            if np.isnan(delta):
                delta = 0.0
            anomaly_sum += delta

        # USE THIS SECTION FOR TIME SERIES IN mm H₂O
        # anomaly_sum is total volume anomaly (m³); convert back to mm: (m³ / total_area) *1000
        # anomalies.append(1000 * anomaly_sum / total_area)
        # error is 10% of the raw storage_sum (m³) → m, then to mm: (0.1*storage_sum / total_area)*1000
        # error_mm = 1000 * (0.1 * storage_sum) / total_area
        # errors.append(error_mm)

        # USE THIS SECTION FOR TIME SERIES IN KM^3
        # anomaly_sum is total volume anomaly (m³); convert to km³: m³ / 1e9
        anomalies.append(anomaly_sum / 1e9)
        # error is 10% of the raw storage_sum (m³) → km³: (0.1*storage_sum) / 1e9
        error_km3 = (0.1 * storage_sum) / 1e9
        errors.append(error_km3)

    logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Anomaly timeseries: {anomalies}")
    logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"Error bars (10%% of storage): {errors}")
    return anomalies, errors


def output_csv(output_file: str | os.PathLike[str], fieldnames: list[str],
               times: np.ndarray, anomalies_dict: dict[str, list[float]]) -> None:
    """
    Write the anomaly timeseries to a CSV file.

    Args:
        output_file:    Path for the output CSV file.
        fieldnames:     List of column names (e.g., date plus variables).
        times:          Array of time values.
        anomalies_dict: Dictionary mapping each variable to its anomaly timeseries.
    
    Returns:
        None. The CSV file is created.
    
    Raises:
        None.
    """
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, dialect='excel')
        writer.writeheader()
        for i, date in enumerate(times):
            row = {fieldnames[0]: date}
            for var in fieldnames[1:]:
                row[var] = anomalies_dict[var][i]
            writer.writerow(row)
    logging.info(f"Created CSV file: {os.fspath(output_file)}")


def output_nc(output_file: str | os.PathLike[str], ds: xr.Dataset, total: int, interest_lon: list[tuple[int, float]],
              interest_lat: list[tuple[int, float]], time_steps: int, var_list: list[str],
              avg_dict: dict[str, list[float]],
              t_var: str = "time", x_var: str = "lon", y_var: str = "lat") -> None:
    """
    Write the anomaly data to a new NetCDF file, masking non-interest grid cells as NaN.

    Args:
        output_file:  Path for the output NetCDF file.
        ds:           Input dataset.
        total:        Total number of grid cells of interest.
        interest_lon: List of tuples (lon_index, longitude).
        interest_lat: List of tuples (lat_index, latitude).
        time_steps:   Number of time steps.
        var_list:     List of variable names.
        avg_dict:     Dictionary of long-term averages for each variable.
        t_var:        Name of the time variable.
        x_var:        Name of the longitude variable.
        y_var:        Name of the latitude variable.
    
    Returns:
        None. The NetCDF file is created.
    
    Raises:
        None.
    """
    nc_out = Dataset(output_file, 'w', format='NETCDF4')
    nc_out.createDimension(t_var, None)
    nc_out.createDimension(y_var, len(ds.lat.data))
    nc_out.createDimension(x_var, len(ds.lon.data))

    # Create coordinate variables
    time_var = nc_out.createVariable(t_var, "i4", (t_var,))
    lat_var  = nc_out.createVariable( y_var, "f4", (y_var,))
    lon_var  = nc_out.createVariable( x_var, "f4", (x_var,))
    time_data = []
    base_date = dt.datetime(2002, 1, 1)
    for t in ds.time.data:
        dt_obj = dt.datetime.strptime(str(t).split("T")[0], "%Y-%m-%d")
        time_data.append((dt_obj - base_date).days)
    time_var[:] = time_data
    lat_var[:] = ds.lat.data
    lon_var[:] = ds.lon.data
    nc_out.createVariable("crs", "i4")

    # Set attributes for coordinate variables
    if t_var in ds.variables:
        var_time = ds[t_var]
        time_var.standard_name = var_time.attrs.get('standard_name', t_var)
        time_var.long_name = t_var
        time_var.units = var_time.attrs.get('units', "days since 2002-01-01 00:00:00 UTC")
        time_var.calendar = var_time.attrs.get('calendar', "gregorian")
    if y_var in ds.variables:
        var_lat = ds[y_var]
        lat_var.standard_name = var_lat.attrs.get('standard_name', "latitude")
        lat_var.long_name = var_lat.attrs.get('long_name', "latitude")
        lat_var.units = var_lat.attrs.get('units', "degrees_north")
    if x_var in ds.variables:
        var_lon = ds[x_var]
        lon_var.standard_name = var_lon.attrs.get('standard_name', "longitude")
        lon_var.long_name = var_lon.attrs.get('long_name', "longitude")
        lon_var.units = var_lon.attrs.get('units', "degrees_east")

    # Write anomaly data for each variable
    for var in var_list:
        out_var = nc_out.createVariable(var, ds[var].dtype, ds[var].dims)
        out_var.setncatts(ds[var].attrs)
        out_var.units = "km^3"
        logging.info(f"Setting units for {var} to {out_var.units}")
        data_array = np.full(ds[var].shape, np.nan)
        for i in range(total):
            lon_idx = interest_lon[i][0]
            lat_idx = interest_lat[i][0]
            long_term_mean = avg_dict[var][i]
            for t in range(time_steps):
                data_array[t, lat_idx, lon_idx] = ds[var].data[t, lat_idx, lon_idx] - long_term_mean
        out_var[:] = data_array

    # Global attributes
    nc_out.Conventions = 'CF-1.6'
    nc_out.history = f"Created on {dt.datetime.now(dt.timezone.utc).isoformat()}+00:00"
    nc_out.featureType = "timeSeries"
    nc_out.close()
    logging.info(f"Created NetCDF file: {os.fspath(output_file)}")


if __name__ == "__main__":
    main()
