import numpy as np
import pandas as pd
import argparse
import os
from osgeo import gdal
from pathlib import Path
import logging

#Written by Munish Sikka and ChatGPT

'''
Generate a grid of repair mask for CONUS as original mask is in uncropped extent including parts of canada
Repaired mask will contain 1's for our desired shape region however any pixels from that shape file mask present in zero repair mask will be set to 0
Script takes 5 arguments:
    1) zero repair mask from Snodas for swe 
    2) masked CONUS tif from Snodas
    3) output CONUS zero repair mask to be saved for future use 
    4) List of base mask csv to generate their repaired mask
    5) Repaired mask output dir.
'''

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name: Path = Path(__file__).stem  # The name of this script without the .py extension
        self.default_full_tif: Path = self.swe_dir / "SNODAS_Zero_Repair_Mask.tif"
        self.default_cropped_tif: Path = self.swe_dir / "SNODAS_Zero_Repair_Mask_Cropped.tif"
        self.default_repaired_masks_dir: Path = self.swe_dir / "masks" / "repaired_masks"
        self.default_base_masks_files: list[Path] = [self.swe_dir / "masks" / "basin_masks" / f"{self.swe_model}_{self.default_basin}_mask.csv"]
        self.default_template_tif: Path = self.swe_dir / "monthly_data" / "monthly_mean_200501.tif"
        

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description="Crop SNODAS repair mask and apply to multiple base masks.")
    parser.add_argument("--full_tif", default=options.default_full_tif,
                        help="Path to full SNODAS zero repair mask (GeoTIFF) to be combined with base mask to generate repaired mask for 2014 oct to 2019 oct")
    parser.add_argument("--template_tif",default=options.default_template_tif,
                        help="Template GeoTIFF for cropping (defines region)")
    parser.add_argument("--cropped_tif", default=options.default_cropped_tif,
                        help="Path to save cropped CONUS repair mask as GeoTIFF")
    parser.add_argument("--base_masks", default=options.default_base_masks_files, nargs='+',
                        help="List of base mask CSV files to repair")
    parser.add_argument("--output_dir", default=options.default_repaired_masks_dir,
                        help="Directory to save repaired CSV masks")
    parser.add_argument('-debug', action='store_true',
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, 'debug', False):
        options.log_mode = "DEBUG"


def main() -> None:
    """Main function to parse arguments and run the repair mask generation for snow water equivalent (SWE) data."""
    gdal.UseExceptions()  # Enable GDAL exceptions for error handling
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    if options.swe_model == "SNODAS":
        repair_mask_generation_for_SNODAS(options)
    else:
        raise ValueError(f"Unsupported snow water equivalent (SWE) model: {options.swe_model}")


def repair_mask_generation_for_SNODAS(options: Options) -> None:
    """
    Run the repair mask generation for SNODAS data.
    
    Args:
        options: An Options instance with parsed command line arguments in options.args. Contains:
           - full_tif:     Path to full SNODAS zero repair mask (GeoTIFF).
           - template_tif: Path to template GeoTIFF for cropping (defines region).
           - cropped_tif:  Path to save cropped repair mask as GeoTIFF.
           - base_masks:   List of base mask CSV files to repair.
           - output_dir:   Directory to save repaired CSV masks.
        
    Returns:
        None. Saves cropped repair mask and repaired CSV masks to output directory.
    
    Raises:
        None.
    """

    # Step 1: Crop the SNODAS repair mask
    print(options.args.full_tif)
    print(options.args.template_tif)
    print(options.args.cropped_tif)
    cropped_arr, _ = crop_by_template(options.args.full_tif, options.args.template_tif, options.args.cropped_tif)

    # Step 2: Apply to each base mask
    for base_mask_path in options.args.base_masks:
        base_name = os.path.basename(base_mask_path)
        logging.info(base_name)
        # Replace 'snodas' with 'repaired' in the filename
        if base_name.startswith("SNODAS_"):
            output_name = base_name.replace("SNODAS_", "repaired_", 1)
        else:
            output_name = f"repaired_{base_name}"
        logging.info(output_name)
        output_path = os.path.join(options.args.output_dir, output_name)
        repair_mask(base_mask_path, cropped_arr, output_path)


def crop_by_template(full_tif: str, template_tif: str, output_tif: str) -> tuple[np.ndarray, tuple]:
    """
    This function takes the Snodas zero repair mask and crops the CONUS region using a masked swe file
    This is step 1 of generating a repaired mask for the period 2014 oct to 2019 oct for Snodas swe data.

    Args:
        full_tif:     Path to full SNODAS zero repair mask (GeoTIFF).
        template_tif: Path to template GeoTIFF for cropping (defines region).
        output_tif:   Path to save cropped repair mask as GeoTIFF.
    
    Returns:
        tuple: A tuple containing:
            - cropped array (np.ndarray): The cropped repair mask array.
            - geo_transform (tuple): The geo-transform of the cropped raster.
    
    Raises:
        None.
    """
    template_ds = gdal.Open(template_tif)
    gt = template_ds.GetGeoTransform()
    x_min = gt[0]
    y_max = gt[3]
    x_res = gt[1]
    y_res = gt[5]
    x_size = template_ds.RasterXSize
    y_size = template_ds.RasterYSize
    
    # Compute max coords with adjustment
    x_max = x_min + x_res * x_size - x_res
    y_min = y_max + y_res * y_size - y_res
    
    #x_max = x_min + x_res * x_size #worked with python 3.9 but gives extra row and col in python 3.12 gdal stricter settings.
    #y_min = y_max + y_res * y_size

    # Crop and save
    gdal.Translate(
        output_tif,
        full_tif,
        projWin=[x_min, y_max, x_max, y_min]
    )

    # Read output raster into array
    ds_out = gdal.Open(output_tif)
    arr = ds_out.ReadAsArray()
    gt_out = ds_out.GetGeoTransform()
    logging.info(f"Cropped and loaded array with shape: {arr.shape}")
    return arr, gt_out


def repair_mask(base_mask_path: str, repair_mask_arr: np.ndarray, output_path: str) -> None:
    """
    Applies the repair mask (already cropped) to a base mask CSV.
    Returns and saves the repaired mask as CSV.

    Args:
        base_mask_path:  Path to the base mask CSV file.
        repair_mask_arr: Numpy array of the cropped repair mask.
        output_path:     Path to save the repaired mask CSV.
    
    Returns:
        None. Saves the repaired mask to output_path.
    
    Raises:
        None.
    """
    base_mask = pd.read_csv(base_mask_path, header=None).values

    # Force repair mask to binary
    mask_repair = np.where(repair_mask_arr == 1, 1, 0)
    mask_repair_inverted = 1 - mask_repair

    # Apply repair: zero out base mask where repair mask is 0
    mask_repaired = np.where(mask_repair_inverted == 0, 0, base_mask)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    pd.DataFrame(mask_repaired).to_csv(output_path, index=False, header=False)
    logging.info(f"Repaired mask saved to {output_path}")


if __name__ == "__main__":
    main()
    
# sample call:
# python C:\work\snowdas_repair_mask_generator.py C:\data\full_snodas_mask.tif C:\data\template_conus.tif C:\data\cropped_repair_mask.tif C:\data\masks\snodas_ca_mask.csv C:\data\masks\snodas_tx_mask.csv C:\data\masks\repaired\
