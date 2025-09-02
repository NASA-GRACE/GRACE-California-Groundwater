import numpy as np
from osgeo import gdal, ogr, osr
import os.path

# Written by Munish Sikka and ChatGPT based on original function provided by Jack McNelis     
def read_shapefile_multilayers(region_name,shapefile,gt,n_lon,n_lat,filter_sort=None,layer_name = None):
    driver = ogr.GetDriverByName('ESRI Shapefile')
    shp = driver.Open(shapefile, 0)
    if shp is None:
        raise FileNotFoundError(f"Could not open {shapefile}")

    lyr = shp.GetLayer()
    ssrs = lyr.GetSpatialRef()
    wkt = ssrs.ExportToPrettyWkt()
    for i, feat in enumerate(lyr):
        if region_name.casefold() in ("ca","California"):
            if feat.GetField("SORT") == filter_sort:
                break
        elif region_name.casefold() == "Colorado river basin":
            if feat.GetField("WMOBB_NAME") == layer_name:
                break
        else:
            if feat.GetField("name").casefold() == region_name.casefold():
                break
        
    feat = lyr.GetFeature(i)     
    #Get the feature's geojson representation:
    geom = feat.GetGeometryRef()
    geojson = geom.ExportToJson()
    list(json.loads(geojson).keys())
    driver = ogr.GetDriverByName("MEMORY")
    featds = driver.CreateDataSource("MemoryDataset")
    newlyr = featds.CreateLayer("temp layer", ssrs, geom_type=ogr.wkbPolygon)
    lyrid = ogr.FieldDefn("ID", ogr.OFTInteger)
    newlyr.CreateField(lyrid)
    lyrdefn = newlyr.GetLayerDefn()
    newfeat = ogr.Feature(lyrdefn)
    newgeom = ogr.CreateGeometryFromJson(geojson)
    newfeat.SetGeometry(newgeom)
    newfeat.SetField("ID", 1)
    newlyr.CreateFeature(newfeat)
    newfeat = None 
      
    mask = gdal.GetDriverByName('MEM').Create(
    '',                       # No filename required for in-memory dataset.
    n_lon,n_lat,  # Dimensions of the output mask (x,y)
    1,            # Output mask should contain only one band.
    gdal.GDT_Byte,# Output type should be byte [0,1].
    )
    
    mask.SetGeoTransform(gt)      # Set the affine transform defined above as the mask's geotransform.

    mask.SetProjection(wkt)       # Set the wkt defn extracted from the shp as the target coordinate system.

    band = mask.GetRasterBand(1)  # Select the first and only band in raster mask.

    band.Fill(0)              # Fill it with zeros.
    band.SetNoDataValue(0)    # Set its nodata value to zero.
    err = gdal.RasterizeLayer(
    mask,
    [1],                      # Set the target band(s); just the one band mask in this case.
    newlyr,                   # Set the source feature layer to rasterize in band 1.
    burn_values = [1],        # Fill the polygon coverage area with 1s.
    )
    
    mask.FlushCache()         # "Write" changes to the in-memory dataset.
    marr = mask.GetRasterBand(1).ReadAsArray()
    env = feat.GetGeometryRef().GetEnvelope()
    bbox = [env[0], env[2], env[1], env[3]]
    return marr,bbox
