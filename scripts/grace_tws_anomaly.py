import argparse
import os
import numpy as np
import pandas as pd
import xarray as xr
from osgeo import gdal
from grace_orientation import shift_to_grace_orientation
from ellipsoidal_area import area
from read_grace_s3_bucket import read_grace_dataset
from pathlib import Path
import logging

import run_all as ra

#Written by Munish Sikka, Felix Landerer and ChatGPT


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                 Path = Path(__file__).stem  # The name of this script without the .py extension
        self.default_grace_file:       str = "GRCTellus.JPL.200204_202503.GLO.RL06.3M.MSCNv04CRI.nc"
        self.default_grace_input_dir: Path = self.grace_dir
        self.default_start_date:       str = "2002-04-01"
        self.default_end_date:         str = "2025-03-31"
        self.default_mask_file:       Path = self.grace_dir / "masks"                 / f"grace_{self.default_basin_safename}_mask.csv"
        self.default_output_path:     Path = self.grace_dir / "monthly_grace_anomaly" / f"anomaly_timeseries_GRACE_{self.default_basin_safename}_mask.csv"
        
def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Process GRACE TWS data for a basin.")
    parser.add_argument("--start_date", default=options.default_start_date,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", default=options.default_end_date,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--scaling_factor", type=int, choices=[0, 1], default=1,
                        help="Apply scaling factor (1=yes, 0=no)")
    parser.add_argument("--file_access_type", default="local",
                        help="Where to read GRACE data from. currently takes only local dir, cloud option can be added later")
    parser.add_argument("--grace_input_dir",default=options.default_grace_input_dir,
                        help="Path to GRACE data when read locally")
    parser.add_argument("--grace_filename", default=options.default_grace_file,
                        help="GRACE-FO Mascons NetCDF filename containing all the months")
    parser.add_argument("--shortname_mass", default="TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.1_V3",
                        help="Short name for PODAAC dataset when assessing data from cloud s3 bucket")
    parser.add_argument("--mask_basin", default=options.default_mask_file,
                        help="Mask file (CSV)")
    parser.add_argument("--output_csv", default=options.default_output_path,
                        help="Full path and filename to save the output CSV")
    parser.add_argument("--units", default="km3", choices=["km3", "cm"],
                        help="Units for output")
    parser.add_argument("--baseline_start", default=None,
                        help="Optional anomaly baseline start date (YYYY-MM-DD)")
    parser.add_argument("--baseline_end", default=None,
                        help="Optional anomaly baseline end date (YYYY-MM-DD)")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = logging.DEBUG


# ===== Main function =====
def main() -> None:
    """Main function to process GRACE TWS data for a basin."""
    options = Options()
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')
    parse_arguments(options)

    dataset = load_dataset(options.args.grace_input_dir, options.args.grace_filename, options.args.file_access_type, options.args.shortname_mass)
    mask_array = load_mask(options.args.mask_basin)

    region_mask, ma = prepare_grid_and_mask(dataset, mask_array)
    tws, bsn_sig, dates = compute_timeseries(dataset, region_mask, ma, options.args.scaling_factor, options.args.start_date, options.args.end_date)

    baseline = (options.args.baseline_start, options.args.baseline_end) if options.args.baseline_start and options.args.baseline_end else None
    save_results(options.args.output_csv, dates, tws, bsn_sig, ma, options.args.units, baseline)
    

def load_dataset(grace_input_dir: str, grace_filename: str, file_access_type: str, shortname_mass: str) -> xr.Dataset:
    """
    Load GRACE dataset from local or PODAAC cloud.
    
    Args:
        grace_input_dir:  Directory or S3 bucket prefix for GRACE data.
        grace_filename:   GRACE NetCDF filename.
        file_access_type: "local"
        shortname_mass:   Short name for PODAAC dataset.
    
    Returns:
        xr.Dataset: Loaded GRACE dataset.
    
    Raises:
        ValueError: If file_access_type is invalid.
    """
    if file_access_type.lower() == "local":
        full_filename = os.path.join(grace_input_dir, grace_filename)
        print(f"Reading GRACE mascon dataset locally: {full_filename}")
        return xr.open_dataset(full_filename)
    else:
        raise ValueError(f"Invalid file access type: {file_access_type}")


def load_mask(mask_path: str) -> np.ndarray:
    """
    Detect mask file type and load it as numpy array.
    
    Args:
        mask_path: Path to the mask file.
    
    Returns:
        np.ndarray: Loaded mask array.
    
    Raises:
        ValueError: If the mask file type is unsupported.
    """
    ext = os.path.splitext(mask_path)[1].lower()
    if ext == ".csv":
        print(f"Loading CSV mask: {mask_path}")
        return np.loadtxt(mask_path, delimiter=",")
    #more options can be added here for filetypes
    else:
        raise ValueError(f"Unsupported mask file type: {mask_path}")


def prepare_grid_and_mask(dataset: xr.Dataset, mask_array: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Align mask to GRACE grid and compute area weights.
    
    Args:
        dataset:    Loaded GRACE dataset.
        mask_array: 2D numpy array of the mask.
    
    Returns:
        tuple: (region_mask, area_matrix)
            - region_mask: Aligned mask array.
            - area_matrix: Area weights array.
    
    Raises:
        None.
    """
    lat_vector = dataset.lat[:].copy()
    lon_vector = dataset.lon[:].copy()
    flip_lat = lat_vector[0] < lat_vector[-1]
    data_res = abs(lon_vector[2] - lon_vector[1])
    indexes_to_shift = int(360 / (2 * data_res))
    shift_lon = np.max(lon_vector) > 180

    # Compute area weights
    dx = data_res/2
    area_weights = area(lat_vector.data,dx).reshape(1, -1).T
    no_of_lon = lon_vector.data.size
    area_matrix = np.repeat(area_weights, no_of_lon, axis=1)

    # Align mask to GRACE grid orientation
    region_mask = shift_to_grace_orientation(shift_lon, flip_lat, mask_array, indexes_to_shift,axis_no=1)
    ma = shift_to_grace_orientation(shift_lon, flip_lat, area_matrix * mask_array, indexes_to_shift,axis_no=1)

    return region_mask, ma


def compute_timeseries(dataset: xr.Dataset, region_mask: np.ndarray, ma: np.ndarray,
                       scale_factor: int, start_date: str, end_date: str) -> tuple:
    """
    Compute regional TWS time series and uncertainty.

    Args:
        dataset:      Loaded GRACE dataset.
        region_mask:  2D numpy array of the aligned mask.
        ma:           2D numpy array of area weights multiplied by mask.
        scale_factor: 1 to apply scaling factor, 0 to skip.
        start_date:   Start date (YYYY-MM-DD).
        end_date:     End date (YYYY-MM-DD).
    
    Returns:
        tuple: (regional_ts, bsn_sig, dates)
            - regional_ts: 1D numpy array of regional TWS time series.
            - bsn_sig:     1D numpy array of basin uncertainty time series.
            - dates:       1D numpy array of datetime64 dates.
    
    Raises:
        None.
    """
    lwe = dataset["lwe_thickness"].sel(time=slice(start_date, end_date)).values
    scale = dataset["scale_factor"].values if scale_factor else np.ones_like(lwe[0])

    lwe_scaled = lwe * scale
    tdim = lwe_scaled.shape[0]
    regional_ts = np.zeros(tdim)

    for i in range(tdim):
        mx = np.ma.masked_where(region_mask == 0, lwe_scaled[i, :, :], copy=True)
        regional_ts[i] = np.average(mx, weights=ma)

    # Compute uncertainty (sig_lwe)
    sig_lwe = dataset["uncertainty"].sel(time=slice(start_date, end_date)).values
    bsn_sig = compute_uncertainty(sig_lwe, dataset["mascon_ID"].values, ma)

    return regional_ts, bsn_sig, dataset["time"].sel(time=slice(start_date, end_date)).values


def compute_uncertainty(sig_lwe: np.ndarray, mascon_id: np.ndarray, ma: np.ndarray) -> np.ndarray:
    """
    Aggregate mascon-level uncertainty to the basin scale.

    Args:
        sig_lwe:     3D numpy array of mascon uncertainties (time, lat, lon).
        mascon_id:   2D numpy array of mascon IDs.
        ma:          2D numpy array of area weights multiplied by mask.
    
    Returns:
        np.ndarray: 1D numpy array of basin uncertainty time series.
    
    Raises:
        None.
    """
    ma_t = ma.T
    bool_mask = ma_t != 0
    new_sig = np.array([np.transpose(sig)[bool_mask] for sig in sig_lwe])

    mscID_t = mascon_id.T
    mscID_bsn = mscID_t[bool_mask]
    ma_bsn = ma_t[bool_mask]

    unique_ids, ia, ic = np.unique(mscID_bsn, return_index=True, return_inverse=True)
    bsn_I = np.array([np.isin(mscID_bsn, uid) for uid in unique_ids])
    maA = np.dot(bsn_I, ma_bsn)

    maA_matrix = np.tile(maA.T, [new_sig.shape[0], 1])
    sig_ma = new_sig[:, ia] * maA_matrix
    return np.sqrt(np.sum(sig_ma**2, axis=1)) / np.sum(maA)


def save_results(output_csv: str, dates: np.ndarray, tws: np.ndarray, bsn_sig: np.ndarray,
                 ma: np.ndarray, units: str = "km3", baseline: tuple = None) -> None:
    """
    Save final time series with optional anomaly calculation.
    
    Args:
        output_csv: Path to save the output CSV.
        dates:      1D numpy array of datetime64 dates.
        tws:        1D numpy array of TWS time series.
        bsn_sig:    1D numpy array of basin uncertainty time series.
        ma:         2D numpy array of area weights multiplied by mask.
        units:      "km3" or "cm" for output units.
        baseline:   Optional tuple of (start_date, end_date) for anomaly baseline.
    
    Returns:
        None. Saves output CSV to output_csv.
    
    Raises:
        None.
    """
    if units.lower() == "km3":
        tws = (tws / 100000) * (np.sum(ma) / 1e6)
        bsn_sig = (bsn_sig / 100000) * (np.sum(ma) / 1e6)

    df = pd.DataFrame({"date": pd.to_datetime(dates), "tws": tws, "tws_error": bsn_sig})
    
    if baseline: #not used as grace fo mascon is already an anomaly of mean (2004-2009)
        start, end = baseline
        mask = (df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))
        baseline_mean = df.loc[mask, "tws"].mean()
        df["tws"] = df["tws"] - baseline_mean
    
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)  # create folder if it doesn't exist
    df.to_csv(output_csv, index=False)
    print(f"Saved results to {output_csv}")


if __name__ == "__main__":
    main()

'''
This script will:
Read GRACE data (local; Note: Option to read from cloud can be added later, some of its functions exists in the repository and implemented in Open Scince GRACE-FO Tutorials).
Auto-detect mask type (CSV).
Align and shift the mask to GRACE orientation.
Compute regional TWS time series and uncertainty.
Convert to km³ or keep in cm (default).
Optionally subtract baseline mean to output anomalies.
Save results with date, tws, tws_error. 
'''
