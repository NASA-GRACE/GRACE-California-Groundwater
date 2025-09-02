import numpy as np
from pyproj import Geod
import math

#original source: https://github.com/podaac/the-coding-club/blob/main/notebooks/MEaSUREs-SSH-dask.ipynb
def area(lats,dx):
    """
    compute weighted area, returns a vector of latitude weights. 
    takes dx as resolution in degrees divided by 2 e.g. 0.5 deg resolution will have dx = 0.5/2    
    """
    # Define WGS84 as CRS:
    geod = Geod(ellps='WGS84')
    c_area = lambda lat: geod.polygon_area_perimeter(np.r_[-dx,dx,dx,-dx], lat+np.r_[-dx,-dx,dx,dx])[0]
    out = []
    for lat in lats:
        out.append(c_area(lat))
    return np.array(out)

