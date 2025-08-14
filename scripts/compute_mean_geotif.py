import numpy as np
import warnings
from osgeo import gdal
import logging

#Written by Munish Sikka and ChatGPT
def compute_mean_raster(file_list, output_path,scale_factor):
    """
    Computes the mean of a list of raster (.tif) files at each pixel location
    and saves the result as a new raster with filename containing start and end day.

    Parameters:
        file_list (list): Sorted list of raster file paths.
        output_dir (str): Directory to save the output mean raster.
        start_day (str): Start day in 'YYYYMMDD' format.
        end_day (str): End day in 'YYYYMMDD' format.
    """
    if not file_list:
        raise ValueError("No valid files provided.")

    # Open the first raster to get dimensions
    first_ds = gdal.Open(file_list[0])
    band = first_ds.GetRasterBand(1)
    rows, cols = band.YSize, band.XSize
    # Initialize an array to hold stacked data
    data_stack = np.full((len(file_list), rows, cols), np.nan, dtype=np.float32)
    shape = (rows,cols)

    # Read each file and stack them
    for i, file in enumerate(file_list):
        ds = gdal.Open(file)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray().astype(np.float32)
        # Convert nodata values to NaN
        nodata_value = band.GetNoDataValue()
        if nodata_value is not None:
            arr[arr == nodata_value] = np.nan
        # Apply scale factor
        arr = arr / scale_factor
        data_stack[i, :, :] = arr
        ds = None  # Close file
    # Compute the mean across the time axis
    # Suppress warnings about empty slices
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean_raster = np.nanmean(data_stack, axis=0)

    # Replace all-NaN pixels with a NoData value (e.g., NaN or -9999)
    mean_raster = np.where(np.isnan(mean_raster), np.nan, mean_raster)

    # Save output raster
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(output_path, cols, rows, 1, gdal.GDT_Float32)
    # Copy geotransform and projection from first input file
    out_ds.SetGeoTransform(first_ds.GetGeoTransform())
    out_ds.SetProjection(first_ds.GetProjection())
    # Write mean array to raster
    out_band = out_ds.GetRasterBand(1)
    out_band.WriteArray(mean_raster)
    # Set NoData value to NaN for consistency
    out_band.SetNoDataValue(np.nan)
    out_band.FlushCache()
    out_ds = None  # Close file
    print(f"Mean raster saved to: {output_path}")
    logging.info(f"Mean raster saved to: {output_path}")

