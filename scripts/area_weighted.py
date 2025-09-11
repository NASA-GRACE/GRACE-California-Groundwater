import numpy as np
from pathlib import Path
import argparse
import logging

import run_all as ra

# Written by Munish Sikka and ChatGPT 


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name: Path = Path(__file__).stem  # The name of this script without the .py extension


def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Compute area-weighted statistics.")
    parser.add_argument("data_csv",
                        help="CSV file with variable values (e.g., SWE in cm).")
    parser.add_argument("weights_csv",
                        help="CSV file with area weights (e.g., km² per pixel).")
    parser.add_argument("mask_csv",
                        help="CSV file with mask (1=include, 0=exclude).")
    parser.add_argument("-o", "--output",
                        help="Optional output CSV file for results.")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = logging.DEBUG


def area_weighted_stats(data: np.ndarray, weights: np.ndarray, mask: np.ndarray) -> tuple[float, float, float]:
    """
    Compute area-weighted statistics for any variable (e.g., SWE, precipitation).

    Args:
        data (np.ndarray):    2D array of variable values (e.g., SWE in cm).
        weights (np.ndarray): 2D array of area weights (e.g., km² per pixel).
        mask (np.ndarray):    2D boolean or int array (1 = include, 0 = exclude).

    Returns:
        tuple: (weighted_mean, weighted_sum, total_weight)
            - weighted_mean: Mean of variable weighted by area (same units as data)
            - weighted_sum: Total volume/mass (data*weights, e.g., cm*km²)
            - total_weight: Total area/weight included (e.g., km²)
    
    Raises:
        None.
    """
    mask = mask.astype(bool)

    # Apply mask
    masked_data = np.where(mask, data, np.nan)
    masked_weights = np.where(mask, weights, np.nan)

    total_weight = np.nansum(masked_weights)
    if total_weight == 0:
        return np.nan, 0, 0

    weighted_sum = np.nansum(masked_data * masked_weights)
    weighted_mean = weighted_sum / total_weight

    return weighted_mean, weighted_sum, total_weight


def load_csv_as_array(path: str) -> np.ndarray:
    """Load a CSV (no header) as a NumPy 2D array."""
    return np.loadtxt(path, delimiter=",")


def run_cli(data_csv: str, weights_csv: str, mask_csv: str, output_csv: str = None) -> None:
    """
    Run the area-weighted stats calculation using CSV files.

    Args:
        data_csv:    Path to CSV file with the variable values.
        weights_csv: Path to CSV file with area weights.
        mask_csv:    Path to CSV file with mask (1=include, 0=exclude).
        output_csv:  If given, save results here.
    
    Returns:
        None. Prints results to console and optionally saves to output_csv.
    
    Raises:
        None.
    """
    data    = load_csv_as_array(data_csv)
    weights = load_csv_as_array(weights_csv)
    mask    = load_csv_as_array(mask_csv)

    mean_val, total_val, total_area = area_weighted_stats(data, weights, mask)

    logging.info(f"Weighted mean value:        {mean_val}")
    logging.info(f"Weighted sum (volume/mass): {total_val}")
    logging.info(f"Total weight (area):        {total_area}")

    if output_csv:
        np.savetxt(output_csv, np.array([[mean_val, total_val, total_area]]),
                   delimiter=",", header="weighted_mean,weighted_sum,total_weight", comments="")
        logging.info(f"Results saved to {output_csv}")


if __name__ == "__main__":
    options = Options()
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')
    run_cli(options.args.data_csv, options.args.weights_csv, options.args.mask_csv, options.args.output)

'''example usage: 
from area_weighted import area_weighted_stats
mean_val, total_val, total_area = area_weighted_stats(data, weights, mask)

or python area_weighted.py data.csv weights.csv mask.csv -o results.csv
'''