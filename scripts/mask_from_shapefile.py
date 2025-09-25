import os
import numpy as np

import run_all as ra


def read_shapefile_multilayers(region_name: str,
                               shapefile:   str | os.PathLike[str],
                               gt:          tuple[float, float, float, float, float, float],
                               n_lon:       int,
                               n_lat:       int,
                               filter_sort: int | None = None,
                               layer_name:  str | None = None) -> tuple[np.ndarray, list[float]]:
    """
    Thin wrapper retained for backward compatibility. Delegates to ra.rasterize_shapefile_to_mask().

    Args:
        shapefile:    Path to the ESRI Shapefile (.shp).
        region_name:  Region/basin name to select (case-insensitive compare).
        gt:           GDAL geotransform tuple for the *target* grid (origin at NW corner).
        n_lon, n_lat: Output raster width/height (x,y).
        filter_sort:  Used for California in HYBAS (field SORT)
        layer_name:   Used for Colorado river basin (field WMOBB_NAME)

    Returns:
        (mask_array, bbox) where:
            mask_array is (n_lat, n_lon) with values {0,1}
            bbox is [minx, miny, maxx, maxy] of the chosen feature.
    """
    select = {"filter_sort": filter_sort, "layer_name": layer_name}
    marr, bbox = ra.rasterize_shapefile_to_mask(
        shapefile=shapefile,
        region_name=region_name,
        gt=gt,
        n_lon=n_lon,
        n_lat=n_lat,
        select=select,
    )
    return marr, bbox


# If you want to bypass this thin wrapper, all you have to do is delete this line in call_raster_mask_generator.py:
# 
# from mask_from_shapefile import read_shapefile_multilayers
# 
# Then look for this line in that file:
# 
# mask,bbox = read_shapefile_multilayers(region_name,input_shapefile,gt,n_lon,n_lat,filter_sort,layer_name)
# 
# and replace it with:
# 
# mask,bbox = ra.rasterize_shapefile_to_mask(region_name=region_name, shapefile=input_shapefile, gt=gt, n_lon=n_lon, n_lat=n_lat, select={"filter_sort": filter_sort, "layer_name": layer_name})
# 
# However, that's up to you. Just thought I'd mention it as an option.

# I'm also leaving the original code commented out below for reference, just in case you'd like to keep it around:


# import numpy as np
# from osgeo import gdal, ogr, osr
# import os.path
# import json

# # Written by Munish Sikka and ChatGPT based on original function provided by Jack McNelis     
# def read_shapefile_multilayers(region_name,shapefile,gt,n_lon,n_lat,filter_sort=None,layer_name = None):
#     driver = ogr.GetDriverByName('ESRI Shapefile')
#     shp = driver.Open(shapefile, 0)
#     if shp is None:
#         raise FileNotFoundError(f"Could not open {shapefile}")

#     lyr = shp.GetLayer()
#     ssrs = lyr.GetSpatialRef()
#     wkt = ssrs.ExportToPrettyWkt()
#     for i, feat in enumerate(lyr):
#         if region_name.casefold() in ("ca","california"):
#             if feat.GetField("SORT") == filter_sort:
#                 break
#         elif region_name.casefold() == "Colorado river basin":
#             if feat.GetField("WMOBB_NAME") == layer_name:
#                 break
#         else:
#             if feat.GetField("name").casefold() == region_name.casefold():
#                 break
        
#     feat = lyr.GetFeature(i)     
#     #Get the feature's geojson representation:
#     geom = feat.GetGeometryRef()
#     geojson = geom.ExportToJson()
#     list(json.loads(geojson).keys())
#     driver = ogr.GetDriverByName("MEM") #changed from MEMORY to MEM
#     featds = driver.CreateDataSource("MemoryDataset")
#     newlyr = featds.CreateLayer("temp layer", ssrs, geom_type=ogr.wkbPolygon)
#     lyrid = ogr.FieldDefn("ID", ogr.OFTInteger)
#     newlyr.CreateField(lyrid)
#     lyrdefn = newlyr.GetLayerDefn()
#     newfeat = ogr.Feature(lyrdefn)
#     newgeom = ogr.CreateGeometryFromJson(geojson)
#     newfeat.SetGeometry(newgeom)
#     newfeat.SetField("ID", 1)
#     newlyr.CreateFeature(newfeat)
#     newfeat = None 
#     mask = gdal.GetDriverByName('MEM').Create(
#     '',                       # No filename required for in-memory dataset.
#     n_lon,n_lat,  # Dimensions of the output mask (x,y)
#     1,            # Output mask should contain only one band.
#     gdal.GDT_Byte,# Output type should be byte [0,1].
#     )
    
#     mask.SetGeoTransform(gt)      # Set the affine transform defined above as the mask's geotransform.

#     mask.SetProjection(wkt)       # Set the wkt defn extracted from the shp as the target coordinate system.

#     band = mask.GetRasterBand(1)  # Select the first and only band in raster mask.

#     band.Fill(0)              # Fill it with zeros.
#     band.SetNoDataValue(0)    # Set its nodata value to zero.
#     err = gdal.RasterizeLayer(
#     mask,
#     [1],                      # Set the target band(s); just the one band mask in this case.
#     newlyr,                   # Set the source feature layer to rasterize in band 1.
#     burn_values = [1],        # Fill the polygon coverage area with 1s.
#     )
    
#     mask.FlushCache()         # "Write" changes to the in-memory dataset.
#     marr = mask.GetRasterBand(1).ReadAsArray()
#     env = feat.GetGeometryRef().GetEnvelope()
#     bbox = [env[0], env[2], env[1], env[3]]
#     return marr,bbox
