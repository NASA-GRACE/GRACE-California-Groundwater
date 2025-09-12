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
import re
from mask_from_shapefile import read_shapefile_multilayers

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                       str = Path(__file__).stem  # The name of this script without the .py extension
        self.shape_dir:                    Path = self.project_root / "input_data" / "shapefiles"
        self.default_region_name:           str = self.default_basin_safename
        self.default_output_file:          Path = self.grace_dir    / "masks" / f"grace_{self.default_basin_safename}_mask.csv"
        self.default_grace_target_dataset: Path = self.grace_dir
        self.default_swe_target_dataset:   Path = self.swe_dir / "monthly_data"
        self.default_dataset_name:          str = "grace_mascon"
        self.default_dataset:              Path = self.default_grace_target_dataset
        if self.default_region_name == "california":
            self.default_input_shapefile:  Path = self.shape_dir / "hybas_na_lev04_v1c.shp"
        else:
            self.default_input_shapefile:  Path = self.shape_dir / "HUC2" / "WBDHU4.shp"

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Generate mask array as csv using input shapefile")
    parser.add_argument("--input_shapefile", default=options.default_input_shapefile,
                        help="path to shapefile")
    parser.add_argument("--output_file", default=options.default_output_file,
                        help="path to save output csv file")
    parser.add_argument("--region_name", default=options.default_region_name,
                        help="mask file region")
    parser.add_argument("--dataset_name", default=options.default_dataset_name,
                        help="grace mascon or any other dataset")
    parser.add_argument("--target_dataset", default=options.default_dataset,
                        help="grid on which mask should be created")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    if options.args.target_dataset == "swe":
        options.dataset_name = options.swe_model
        tif_files = sorted(options.default_swe_target_dataset.glob("*.tif"))  # sort for consistency
        if not tif_files:
            raise FileNotFoundError(f"No .tif files found in {options.default_swe_target_dataset}")
        options.default_swe_target_dataset = options.default_swe_target_dataset / tif_files[0]
        options.target_dataset = options.default_swe_target_dataset #swe_target_dataset
        options.output_file = options.swe_dir / "masks" / "basin_masks" / f"{options.swe_model}_{options.default_basin_safename}_mask.csv"
    else:
        options.dataset_name = options.default_dataset_name
        grace_nc_files = sorted(options.default_grace_target_dataset.glob("*MSCNv04CRI*.nc"))
        if not grace_nc_files:
            raise FileNotFoundError(f"No grace mascon files found in {options.default_grace_target_dataset}")
        def extract_end_date(filename):
            match = re.search(r'_(\d{6})\.', filename)  # match last date like _202503.
            return int(match.group(1)) if match else 0
        latest_nc_file = max(grace_nc_files, key=lambda f: extract_end_date(f.name))
        options.default_grace_target_dataset = latest_nc_file  # This is a complete Path.
        options.target_dataset = options.default_grace_target_dataset
        options.output_file = options.grace_dir / "masks" / f"grace_{options.default_basin_safename}_mask.csv"
                
   
def main(input_shapefile: str, output_file: str, region_name: str, dataset_name: str, target_dataset: str) -> None:
    """
    Main function to create a river basin mask.

    Args:
        input_shapefile: Path to the input shapefile.
        output_file:     Path to save the output CSV file.
        region_name:     Name of the region/basin to mask.
        dataset_name:    Name of the dataset (e.g., 'SNODAS', 'grace_mascon').
        target_dataset:  Path to the target dataset (GeoTIFF or NetCDF).
    
    Returns:
        None. The mask is saved to output_file as a CSV.
    
    Raises:
        ValueError: If the region_name is unknown or if the target_dataset format is unsupported.
    """
    filter_sort = None
    layer_name  = None
    if region_name in ("ca","california"):
        filter_sort = 22 # only used for the California basin
    elif region_name.casefold() == "sacramento":
        pass
    elif region_name.casefold() == "san_joaquin":
        pass
    elif region_name.casefold() == "tulare-buena_vista_lakes":
        pass
    else:
        raise ValueError(f"Unknown basin '{region_name}'")
    basin_title = region_name.replace(' ', '_').casefold()
    logging.info(basin_title)
    #tif dataset
    print(target_dataset)
    print(dataset_name)
    print(output_file)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)  # create folder if it doesn't exist

    if str(target_dataset).lower().endswith(".tif") and dataset_name.upper() == 'SNODAS':
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
    elif str(target_dataset).lower().endswith(".nc")and dataset_name.lower() == 'grace_mascon':
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
    gdal.UseExceptions()  # Enable GDAL exceptions for error handling
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    logging.info(f"Running on dataset:      {options.dataset_name}:")
    logging.info(f"Using target dataset:    {options.target_dataset}")
    logging.info(f"Using shapefile:         {options.args.input_shapefile}")
    logging.info(f"Output will be saved to: {options.output_file}")

    main(options.args.input_shapefile, options.output_file, options.args.region_name, options.dataset_name, options.target_dataset)
