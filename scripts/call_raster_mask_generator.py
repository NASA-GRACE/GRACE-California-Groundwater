#!/usr/bin/env python3
"""
Written by Munish Sikka 
Based on code written in 2025 at JPL by Emmy Killett (she/her), ChatGPT o4-mini-high (it/its), and GitHub Copilot (it/its).
Initial version written by Munish Sikka (he/him) and Jack McNelis (he/him).
"""
import os
from pathlib import Path
import numpy as np
from osgeo import gdal
import argparse
import xarray as xr
import logging
import pandas as pd 
from mask_from_shapefile import read_shapefile_multilayers

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name: Path = Path(__file__).stem  # The name of this script without the .py extension
        self.shape_dir: Path = self.project_root / "input_data" / "shapefiles"
        self.default_input_shapefile = self.shape_dir / "hybas_na_lev04_v1c.shp"
        self.default_output_file: Path = self.project_root / "input_data" / "masks"
        self.default_region_name: str = options.default_basin
        self.default_dataset_name: str = "grace_mascon"
        self.default_target_dataset: Path = self.grace_dir / "GRCTellus.JPL.200204_202503.GLO.RL06.3M.MSCNv04CRI.nc"
        
def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Generate mask array as csv using input shapefile")
    parser.add_argument("--input_shapefile", default=options.default_input_shapefile, required=True,
                        help="path to shapefile")
    parser.add_argument("--output_file", default=options.default_output_file, required=True,
                        help="path to save output csv file")
    parser.add_argument("--region_name", default=options.default_region_name, required=True,
                        help="mask file region")
    parser.add_argument("--dataset_name", default=options.default_dataset_name, required=True,
                        help="grace mascon or any other dataset")
    parser.add_argument("--target_dataset", default=options.default_target_dataset, required=True,
                        help="grid on which mask should be created")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = "DEBUG"


def main(input_shapefile: str, output_file: str, region_name: str, dataset_name: str, target_dataset: str) -> None:
    """
    Main function to create a river basin mask.

    Args:
        input_shapefile: Path to the input shapefile.
        output_file:     Path to save the output CSV file.
        region_name:     Name of the region/basin to mask.
        dataset_name:    Name of the dataset (e.g., 'snodas', 'grace_mascon').
        target_dataset:  Path to the target dataset (GeoTIFF or NetCDF).
    
    Returns:
        None. The mask is saved to output_file as a CSV.
    
    Raises:
        ValueError: If the region_name is unknown or if the target_dataset format is unsupported.
    """
    filter_sort = None
    layer_name  = None
    if region_name.casefold() in ("ca","California"):
        filter_sort = 22 # only used for the California basin
    elif region_name.casefold() == "sacramento":
        pass
    elif region_name.casefold() == "san joaquin":
        pass
    elif region_name.casefold() == "tulare-buena vista lakes":
        pass
    elif region_name.casefold() ==  'Colorado river basin':
        layer_name = 'COLORADO (also COLORADO RIVER)'
    else:
        raise ValueError(f"Unknown basin '{region_name}'")
    basin_title = region_name.replace(' ', '_').replace('-', '_').casefold()
    logging.info(basin_title)
    #tif dataset
    if target_dataset.lower().endswith(".tif") and dataset_name.lower() == 'snodas':
        ds = gdal.Open(target_dataset) #open sample geotif to get geotrasnform info. 
        if ds is None:
            raise RuntimeError(f"Could not open GeoTIFF: {target_dataset}")
        gt = ds.GetGeoTransform()
        n_lon = ds.RasterXSize
        n_lat = ds.RasterYSize
        res_lon = gt[1]
        res_lat = abs(gt[5])
        logging.info(f"GeoTIFF grid detected: res_lon={res_lon}, res_lat={res_lat}")
        mask,bbox = read_shapefile_multilayers(region_name,input_shapefile,gt,n_lon,n_lat,filter_sort,layer_name)
        ds = None
        df = pd.DataFrame(mask)
        df.to_csv(output_file, header=False, index=False)
        logging.info(bbox)
        # nc file datset
    elif target_dataset.lower().endswith(".nc")and dataset_name.lower() == 'grace_mascon':
        dataset = xr.open_dataset((target_dataset))
        lat_var = None
        lon_var = None
        for name in dataset.variables:
            if name.lower() in ["lon", "longitude"]:
                lon_var = name
            elif name.lower() in ["lat", "latitude"]:
                lat_var = name                 
        if lon_var is None or lat_var is None:
            raise ValueError(f"NetCDF file {target_dataset} missing lat/lon variables")
        lons = dataset[lon_var]
        lats = dataset[lat_var]
        res_lon = float(np.abs(lons[1] - lons[0]))
        res_lat = float(np.abs(lats[1] - lats[0]))
        n_lon = len(lons)
        n_lat = len(lats)
        # Build geotransform-like tuple 
        gt = (
        -180.0,       # 0  X minimum (upper-left corner, the origin),
        res_lon,      # 1  X resolution,
        0.0,          # 2  X rotation,
        90.0,         # 3  Y maximum (upper-left corner, the origin),
        0.0,          # 4  Y rotation,
        -1*res_lat,   # 5  Y resolution
        )
        mask,bbox = read_shapefile_multilayers(region_name,input_shapefile,gt,n_lon,n_lat,filter_sort,layer_name)
        df = pd.DataFrame(mask)
        df.to_csv(output_file, header=False, index=False)
    else:
        raise ValueError(f"Unsupported target dataset format: {target_dataset}")


if __name__ == "__main__":
    #gdal.UseExceptions()  # Enable GDAL exceptions for error handling
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    main(options.args.input_shapefile, options.args.output_file, options.args.region_name, options.args.dataset_name, options.args.target_dataset)

'''
sample call geotif:
python generate_mask.py `
  --input_shapefile "C:/data/basins/ca_river_basin.shp" `
  --output_file "C:/data/masks/ca_mask.csv" `
  --region_name "California_Basin" `
  --dataset_name "snowdas" `
  --target_dataset "C:/data/grids/snodas_grid.tif"

or netcdf

python generate_mask.py `
  --input_shapefile "C:/data/basins/ca_river_basin.shp" `
  --output_file "C:/data/masks/ca_mask.csv" `
  --region_name "California_Basin" `
  --dataset_name "grace_mascon" `
  --target_dataset "C:/data/grids/climate_grid.nc"
'''
