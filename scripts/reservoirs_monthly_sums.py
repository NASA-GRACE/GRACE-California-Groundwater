import argparse
import os
import pandas as pd
import unicodedata
from osgeo import ogr, gdal
import re
from pathlib import Path
import logging
import datetime

import run_all as ra

#Written by Munish Sikka and ChatGPT


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_data_dir:      Path = self.reservoirs_dir / "reservoir_data"
        self.default_output_dir:    Path = self.reservoirs_dir / "monthly_sums"
        self.default_region_name:    str = self.default_basin_safename #default_basin
        self.default_input_xlsx:    Path = self.reservoirs_dir / f"{self.reservoirs_model.lower()}_data_webpage.xlsx"

        self.default_start_date:     str = self.test_start
        self.default_end_date:       str = self.test_end

        if self.default_region_name == "california":
            self.default_shapefile:     Path = self.project_root / "input_data" / "shapefiles" / "hybas_na_lev04_v1c.shp"
            self.default_allowed_names: list = ["22"]
        else:
            self.default_shapefile:     Path = self.project_root / "input_data" / "shapefiles" / "HUC2" / "WBDHU4.shp"
            self.default_allowed_names: list = self.valid_basins


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description=f"Map {options.reservoirs_model} sites to regions and generate time series + mapping CSVs.")
    parser.add_argument("--shapefile", default=options.default_shapefile,
                        help="Path to shapefile defining regions")
    parser.add_argument("--shapefile_name_field", default="name",
                        help="Field in shapefile for region names (ignored if region_name=ca)")
    parser.add_argument("--input_xlsx", default=options.default_input_xlsx,
                        help="Excel file with site info (Station ID, LATITUDE, LONGITUDE)")
    parser.add_argument("--sheet_name", type=int, default=0,
                        help="Sheet index in Excel (default 0)")
    parser.add_argument("--allowed_names", default=options.default_allowed_names, nargs="+",
                        help="Region names (strings) or SORT codes (if region_name=ca)")
    parser.add_argument("--region_name", default=options.default_region_name,
                        help="Overall region name, e.g. 'ca' to use SORT field")
    parser.add_argument("--data_dir", default=options.default_data_dir,
                        help="Directory containing site CSVs")
    parser.add_argument("--output_dir", default=options.default_output_dir,
                        help="Directory to save per-region outputs")
    parser.add_argument("--start_date", default=options.default_start_date,
                        help="start date yyyy-mm-dd format in reservoir filenames")
    parser.add_argument("--end_date", default=options.default_end_date,
                        help="end date yyyy-mm-dd format in reservoir filenames")
    parser.add_argument("--units", default="km3", choices=["km3", "m3"],
                        help="Units for output")
    parser.add_argument("--full", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG

    # Format dates as YYYY-MM-DD regardless of their original format by parsing and reformatting.
    options.args.start_date = (ra.parse_datetime(options.args.start_date)).strftime("%Y-%m-%d")
    options.args.end_date   = (ra.parse_datetime(options.args.end_date  )).strftime("%Y-%m-%d")


def main() -> None:
    """Main function to compute monthly sums of reservoirs data."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    if options.reservoirs_model == "CDEC":
        monthly_sums_CDEC(options)
    else:
        raise ValueError(f"Unsupported reservoirs model: {options.reservoirs_model}")


def monthly_sums_CDEC(options: Options) -> None:
    """
    Map CDEC sites to regions from shapefile, generate mapping CSVs and regional monthly sums
    
    Args:
        options: An Options instance with parsed command line arguments in options.args. Contains:
           - shapefile:              Path to shapefile defining regions.
           - shapefile_name_field:   Field in shapefile for region names (ignored if region _name=ca).
           - input_xlsx:             Excel file with site info (Station ID, LATITUDE, LONGITUDE).
           - sheet_name:             Sheet index in Excel (default 0).
           - allowed_names:          Region names (strings) or SORT codes (if region_name=california).
           - region_name:            Overall region name, e.g. 'California' to use SORT field.
           - data_dir:               Directory containing site CSVs.
           - output_dir:             Directory to save per-region outputs.
    
    Returns:
        None. Saves mapping CSVs and regional monthly sums CSVs to output_dir.
    
    Raises:
        None.    
    """
    shapefile            = options.args.shapefile
    shapefile_name_field = options.args.shapefile_name_field
    input_xlsx           = options.args.input_xlsx
    sheet_name           = options.args.sheet_name
    allowed_names        = options.args.allowed_names
    region_name          = options.args.region_name
    data_dir             = options.args.data_dir
    output_dir           = options.args.output_dir
    start_date           = options.args.start_date
    end_date             = options.args.end_date
    units                = options.args.units
    
    os.makedirs(output_dir, exist_ok=True)
    gdal.UseExceptions()  # Enable GDAL exceptions for error handling
    # Load site data from Excel
    site_df = pd.read_excel(input_xlsx, sheet_name=sheet_name)
    site_df['LONGITUDE'] = site_df['LONGITUDE'].apply(clean_unicode_whitespace).astype(float)

    site_df = site_df.rename(columns={
        'Station ID': 'sitename',
        'LATITUDE': 'latitude',
        'LONGITUDE': 'longitude'
    })
    site_df.columns = site_df.columns.str.lower()
    required_cols = {'sitename', 'latitude', 'longitude'}
    if not required_cols.issubset(site_df.columns):
        raise ValueError(f"Excel file must have columns: {required_cols}")

    site_names = site_df['sitename'].tolist()
    latitudes  = site_df['latitude'].tolist()
    longitudes = site_df['longitude'].tolist()

    # Handle California SORT shapefile (numeric) case
    use_sort_field = region_name == "california"
    if use_sort_field:
        shapefile_name_field = "SORT"
        allowed_names = [int(x) for x in allowed_names]  # Ensure integers
    else:
        shapefile_name_field = "name"
        # keep as string list, normalize names
        allowed_names = [x.strip() for x in allowed_names]

    # Load shapefile
    shapefile_ds = ogr.Open(shapefile)
    layer = shapefile_ds.GetLayer()

    shape_to_sites = {name: [] for name in allowed_names}

    # Match sites to regions
    for sitename, lat, lon in zip(site_names, latitudes, longitudes):
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint(lon, lat)
        for feature in layer:
            geom = feature.GetGeometryRef()
            match_value = feature.GetField(shapefile_name_field)

            if use_sort_field:
                if geom.Contains(point) and int(match_value) in allowed_names:
                    shape_to_sites[int(match_value)].append(sitename)
                    break
            else:
                if geom.Contains(point) and match_value in allowed_names:
                    shape_to_sites[match_value].append(sitename)
                    break
        layer.ResetReading()

    # For each region: save mapping CSV and compute monthly totals
    for region_key, sites in shape_to_sites.items():
        sanitized_region = sanitize_name(region_key)
        print(sanitized_region)
        # Save site-to-region mapping CSV
        if use_sort_field:
            mapping_csv = os.path.join(output_dir, f"sites_{region_name}.csv")
        else:
            mapping_csv = os.path.join(output_dir, f"sites_{sanitized_region}.csv")

        pd.DataFrame({'sitename': sites}).to_csv(mapping_csv, index=False)
        logging.info(f"Saved site-to-region mapping: {mapping_csv}")

        # Generate regional time series CSV
        monthly_dfs = []
        """
        Look in directory for files with pattern *_monthly_m3_YYYY-MM-DD_to_YYYY-MM-DD.csv
        """
        pattern = f"monthly_m3_{start_date}_to_{end_date}"

        for sitename in sites:
            file_path = os.path.join(data_dir, f"{sitename}_{pattern}.csv")
            if os.path.exists(file_path):
                monthly_dfs.append(read_monthly_csv(file_path))
            else:
                logging.error(f"[Missing] {file_path}")

        if monthly_dfs:
            combined_df = pd.concat(monthly_dfs, axis=1).fillna(0)
            if units.lower() == "km3":
                 region_series = combined_df.sum(axis=1) / 1e9  # Convert m³ to km³
            elif units.lower() == "m3":
                 region_series = combined_df.sum(axis=1)
            else:
                 raise ValueError(f"Unsupported units: {units}. Use 'm3' or 'km3'.")     
            
            if use_sort_field:
                region_df = pd.DataFrame({'date': region_series.index, region_name: region_series.values})
            else:
                region_df = pd.DataFrame({'date': region_series.index, sanitized_region: region_series.values})
 
            region_df = region_df.sort_values('date')

            if use_sort_field:
                region_csv = os.path.join(output_dir, f"{region_name}_monthly_km3.csv")
            else:
                region_csv = os.path.join(output_dir, f"{sanitized_region}_monthly_km3.csv")
            region_df.to_csv(region_csv, index=False)
            logging.info(f"Saved time series: {region_csv}")
        else:
            logging.warning(f"No data found for region: {region_key}")


def clean_unicode_whitespace(val: str) -> str:
    """Normalize string to remove non-breaking spaces or invisible characters."""
    return ''.join(ch for ch in str(val) if not unicodedata.category(ch).startswith('Z'))


def sanitize_name(name: str) -> str:
    """Lowercase and replace spaces with underscores for filenames."""
    return re.sub(r'[\s]+', '_', str(name).lower())


def read_monthly_csv(file_path: str) -> pd.DataFrame:
    """
    Reads a monthly CSV file and returns a DataFrame with monthly sums.

    Args:
        file_path: Path to the CSV file.

    Returns:
        A DataFrame with monthly sums.

    Raises:
        None.
    """
    df = pd.read_csv(file_path, parse_dates=['DATETIME'])
    df = df[['DATETIME', 'VALUE']].copy()
    df = df.groupby('DATETIME').sum()  # Sum per month if duplicates exist
    return df


if __name__ == "__main__":
    main()

r'''
This script matches sites from the Excel file to the shapefile region for each shapefile region name (or SORT code)

Saves a mapping CSV:sites_<region>.csv
Reads all corresponding *_monthly_m3_*.csv files for those sites.

Combines and sums them to produce a regional time series CSV:<region>_monthly_km3.csv
(values in km³).

'''
