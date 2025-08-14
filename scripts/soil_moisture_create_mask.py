#!/usr/bin/env python3
"""
Written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), ChatGPT 5 (it/its), and GitHub Copilot (it/its).
Based on code provided by Munish Sikka (he/him) and Jack McNelis (he/him).
"""

import os
import numpy as np
import xarray as xr
from osgeo import ogr, gdal
import json
import pandas as pd
import logging
import argparse
from pathlib import Path
import glob

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:          Path = Path(__file__).stem  # The name of this script without the .py extension
        self.shape_dir:        Path = self.project_root / "input_data" / "shapefiles"
        self.masks_dir:        Path = self.project_root / "input_data" / "masks"
        self.gridded_data_dir: Path = self.project_root / "input_data" / "soil_moisture" / self.soil_moisture_model / "data_concatenated"


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(
        description=("Create a river basin mask from a shapefile and save it as a netCDF file.\n"
                     "This script uses GDAL/OGR to rasterize a specified basin from a shapefile onto the lat/lon grid of a provided netCDF file.\n"),
        epilog=("Usage example:\n mypy create_mask_01.py -basin Sacramento\n"
                f"This will create a mask for the Sacramento basin and save it as '{options.soil_moisture_model}_sacramento_mask.nc'.\n"),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-b", "--basin", type=str, help=f"Basin identifier ({', '.join(options.valid_basins)}).", default=options.default_basin)
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = "DEBUG"


def main() -> None:
    """Main function to create a river basin mask for soil moisture data."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    if options.soil_moisture_model == "NLDAS":
        create_mask_for_NLDAS(options)
    else:
        raise ValueError(f"Unsupported soil moisture model: {options.soil_moisture_model}")


def create_mask_for_NLDAS(options: Options) -> None:
    """
    Create a river basin mask for NLDAS data.
    
    Args:
        options: An Options instance with parsed command line arguments in options.args. Contains:
           - basin: Basin identifier (e.g., 'California', 'Sacramento', etc.).
           - shape_dir: Directory containing shapefiles.
           - masks_dir: Directory to save generated masks.
           - gridded_data_dir: Directory containing gridded soil moisture data (netCDF files).
    
    Returns:
        None. Saves the generated mask as a netCDF file in masks_dir.
    
    Raises:
        ValueError: If the specified basin is unknown.    
    """

    gdal.UseExceptions()  # Enable GDAL exceptions for error handling
    logging.info(f"Creating mask for basin: {options.args.basin}")

    if options.args.basin.casefold() == "california":
        shapefile = options.shape_dir / "hybas_na_lev04_v1c.shp"
        filter_sort = 22  # only used for the California basin
    elif options.args.basin.casefold() == "sacramento":
        shapefile = options.shape_dir / "HUC2" / "WBDHU4.shp"
    elif options.args.basin.casefold() == "san joaquin":
        shapefile = options.shape_dir / "HUC2" / "WBDHU4.shp"
    elif options.args.basin.casefold() == "tulare-buena vista lakes":
        shapefile = options.shape_dir / "HUC2" / "WBDHU4.shp"
    else:
        raise ValueError(f"Unknown basin '{options.args.basin}'. Supported basins are: {', '.join(ra.valid_basins)}")
    basin_title = options.args.basin.replace(' ', '_').replace('-', '_').casefold()
    output_mask_filename = f"NLDAS_{basin_title}_mask.nc"
    output_mask_filepath = options.masks_dir / output_mask_filename

    # Open the netCDF (so that we know the exact lat/lon grid)
    nc_path = max(glob.glob(str(options.gridded_data_dir / "*.nc")), key=os.path.getctime)
    logging.info(f"Opening netCDF file: {nc_path}")
    ds_water = xr.open_dataset(nc_path)
    lons = ds_water.lon.values
    lats = ds_water.lat.values
    # If lats happen to be descending, flip them so our raster has the correct orientation
    if lats[0] > lats[-1]:
        logging.info("Latitudes are in descending order; flipping to ascending.")
        lats = lats[::-1]
    logging.info(f"Northwestern corner is at ({lons[ 0]:.6f}, {lats[-1]:.6f})")
    logging.info(f"Southwestern corner is at ({lons[ 0]:.6f}, {lats[ 0]:.6f})")
    logging.info(f"Northeastern corner is at ({lons[-1]:.6f}, {lats[-1]:.6f})")
    logging.info(f"Southwestern corner is at ({lons[-1]:.6f}, {lats[ 0]:.6f})")
    n_lat = lats.size
    n_lon = lons.size
    logging.info(f"Dataset has {n_lon} longitudes (spanning {lons[-1] - lons[0]} degrees) and {n_lat} latitudes (spanning {lats[-1] - lats[0]} degrees).")
    # Compute the resolution in degrees:
    res_lon = float(np.abs(lons[1] - lons[0]))
    res_lat = float(np.abs(lats[1] - lats[0]))
    logging.info(f"Resolution is {res_lon:.6f} lon x {res_lat:.6f} lat.")

    # 1. Open Shapefile
    driver = ogr.GetDriverByName("ESRI Shapefile")
    ds_shape = driver.Open(shapefile, 0)  # Read-only mode
    if ds_shape is None:
        raise FileNotFoundError(f"Could not open {shapefile}")

    # 2. Get the Requested Layer
    # layer = ds_shape.GetLayerByName(layer_name)
    lyr = ds_shape.GetLayer()
    ssrs = lyr.GetSpatialRef()
    wkt = ssrs.ExportToPrettyWkt()
    logging.debug(lyr)

    for i, feat in enumerate(lyr):
        # log all fields in the feature
        logging.debug(f"Feature {i} fields: {feat.items()}")
        for field in feat.items():
            logging.debug(f"Field: {field}")
        if options.args.basin.casefold() == "california":
            if feat.GetField("SORT") == filter_sort:
                break
        else:
            if feat.GetField("name").casefold() == options.args.basin.casefold():
                break
    feat = lyr.GetFeature(i)
    logging.debug(f"Chose feature #{i}: {feat}")

    geom = feat.GetGeometryRef()
    geojson = geom.ExportToJson()

    list(json.loads(geojson).keys())
    driver = ogr.GetDriverByName("MEM")
    featds = driver.CreateDataSource("MemoryDataset")
    newlyr = featds.CreateLayer("california basin", ssrs, geom_type=ogr.wkbPolygon)
    lyrid = ogr.FieldDefn("ID", ogr.OFTInteger)
    newlyr.CreateField(lyrid)
    lyrdefn = newlyr.GetLayerDefn()
    newfeat = ogr.Feature(lyrdefn)
    newgeom = ogr.CreateGeometryFromJson(geojson)
    newfeat.SetGeometry(newgeom)
    newfeat.SetField("ID", 1)
    newlyr.CreateFeature(newfeat)

    newfeat = None
    gt = (
        lons[0],       # 0  X minimum (upper-left corner, the origin),
        res_lon,       # 1  X resolution,
        0.0,           # 2  X rotation,
        lats[-1],      # 3  Y maximum (upper-left corner, the origin),
        0.0,           # 4  Y rotation,
        -1*(res_lat),  # 5  Y resolution
    )

    mask = gdal.GetDriverByName('MEM').Create(
        '',             # No filename required for in-memory dataset.
        n_lon, n_lat,   # Dimensions of the output mask (x,y)
        1,              # Output mask should contain only one band.
        gdal.GDT_Byte,  # Output type should be byte [0,1].
    )

    mask.SetGeoTransform(gt)      # Set the affine transform defined above as the mask's geotransform.
    mask.SetProjection(wkt)       # Set the wkt defn extracted from the shp as the target coordinate system.
    logging.debug(mask)
    band = mask.GetRasterBand(1)  # Select the first and only band in raster mask.
    band.Fill(0)                  # Fill it with zeros.
    band.SetNoDataValue(0)        # Set its nodata value to zero.

    err = gdal.RasterizeLayer(
        mask,
        [1],                      # Set the target band(s); just the one band mask in this case.
        newlyr,                   # Set the source feature layer to rasterize in band 1.
        burn_values = [1],        # Fill the polygon coverage area with 1s.
    )

    mask.FlushCache()             # "Write" changes to the in-memory dataset.
    marr = mask.GetRasterBand(1).ReadAsArray()
    env = feat.GetGeometryRef().GetEnvelope()
    bbox = [env[0], env[2], env[1], env[3]]
    logging.info(f"Raster mask bounding box: {bbox}")

    logging.info(f"Unique values in mask: {np.unique(marr)}")

    logging.info("Saving the mask as a netCDF file...")
    marr = marr[::-1, :]  # reverse the rows so that marr[0,:] is southernmost
    mask_da = xr.DataArray(
        marr,
        dims=("lat", "lon"),
        coords={"lat": lats, "lon": lons},
        name="mask"
    )
    mask_ds = xr.Dataset({"mask": mask_da})

    # 3) Now invoke our align‐function to guarantee that ds_mask.lat/lon match ds_water.lat/lon
    try:
        mask_ds_aligned = align_mask_to_water_grid(ds_water, mask_ds)
    except ValueError as e:
        # If something is truly wrong (neither a direct match nor a swap), you'll see a clear error.
        raise RuntimeError(f"Could not align mask grid to water grid:\n{e}") from e

    logging.info(f"{mask_ds_aligned.mask.dims = }")   # should say ('lat', 'lon')
    logging.info(f"{mask_ds_aligned.mask.shape = }")  # should say (n_lat, n_lon)

    # At this point, mask_ds_aligned.lat == ds_water.lat  (same shape & same values),
    # and mask_ds_aligned.lon == ds_water.lon (same shape & same values), and dim order is ("lat","lon").
    logging.info("Saving the mask (now guaranteed to match ds_water's lat/lon) to netCDF...")
    mask_ds_aligned.to_netcdf(output_mask_filepath)
    logging.info(f"Finished. Mask saved to: {output_mask_filepath}")


def align_mask_to_water_grid(ds_water: xr.Dataset, ds_mask: xr.Dataset, tol: float = 1e-8) -> xr.Dataset:
    """
    Make sure that `ds_mask.lat`/`ds_mask.lon` end up on the *same* 1D arrays (and in the same order)
    as `ds_water.lat`/`ds_water.lon`.  If ds_mask's coordinates are already correct, returns ds_mask
    unchanged.  If ds_mask.lat/lon are *swapped* (i.e. lat≈ds_water.lon and lon≈ds_water.lat), this
    will:
      1) transpose the 2D variable so that its dims go from ("lon","lat") → ("lat","lon"), and
      2) re-assign the correct coordinate values from ds_water.
    
    Args:
        ds_water: Dataset containing the reference lat/lon grid (e.g., soil moisture or SWE data).
        ds_mask:  Dataset containing the mask to be aligned.
        tol:      Tolerance for floating-point comparison of lat/lon values. Defaults to 1e-8 degrees.
    
    Returns:
        xr.Dataset: A new Dataset with the mask variable aligned to ds_water's lat/lon grid.
    
    Raises:
        ValueError: If ds_mask's lat/lon do not match or swap-match ds_water's lat/lon.
    """
    # 1) Pull out reference lat/lon from ds_water
    ref_lats = ds_water["lat"].values
    ref_lons = ds_water["lon"].values

    # 2) Pull out mask's lat/lon
    mask_lats = ds_mask["lat"].values
    mask_lons = ds_mask["lon"].values

    # 3) First check: are they already identical (same shape & same values)?
    same_lat_order = np.allclose(mask_lats, ref_lats, atol=tol)
    same_lon_order = np.allclose(mask_lons, ref_lons, atol=tol)

    if same_lat_order and same_lon_order:
        logging.info("The mask is already on the same lat/lon grid (and in the same order).")
        return ds_mask

    # 4) Second check: have we accidentally *swapped* latitude ↔ longitude?
    swapped_lat_eq_lon = np.allclose(mask_lats, ref_lons, atol=tol)
    swapped_lon_eq_lat = np.allclose(mask_lons, ref_lats, atol=tol)

    if swapped_lat_eq_lon and swapped_lon_eq_lat:
        # In this case, ds_mask.lat ≈ ds_water.lon  AND  ds_mask.lon ≈ ds_water.lat.
        logging.info('The 2D array is effectively laid out with dims=("lon","lat") instead of ("lat","lon").')

        # a) Grab the 2D “mask” DataArray (whatever its name is—we'll assume it's called “mask”).
        #    If your ds_mask has multiple variables, adjust the name accordingly.
        var = ds_mask["mask"]

        # b) Transpose so that dims go from ("lon","lat") → ("lat","lon").
        #    After this transpose:
        #      var_t.dims     == ("lat","lon")
        #      var_t.coords["lat"] == old coords["lon"]     # (which used to be ds_water.lon)
        #      var_t.coords["lon"] == old coords["lat"]     # (which used to be ds_water.lat)
        var_t = var.transpose("lat", "lon")

        # c) Now re-assign the *correct* coordinate arrays from ds_water:
        var_t = var_t.assign_coords(lat = ref_lats, lon = ref_lons)

        # d) Package back into a Dataset (so that its name stays “mask” and dims are correct):
        new_ds_mask = var_t.to_dataset(name="mask")
        return new_ds_mask

    # 5) If we reach here, neither direct‐match nor swapped‐match was true → throw an error:
    raise ValueError("The ds_mask coordinates do not line up with ds_water at all.  \n"
                     f" ds_mask.lat shape = {mask_lats.shape}, values do not match ds_water.lat or ds_water.lon.\n"
                     f" ds_mask.lon shape = {mask_lons.shape}, values do not match ds_water.lon or ds_water.lat.\n"
                     "Please check that you didn't accidentally assign lat/lon in the wrong order, or that "
                     "the two grids at least share the same 1D values in one of those two ways.")


if __name__ == "__main__":
    main()
