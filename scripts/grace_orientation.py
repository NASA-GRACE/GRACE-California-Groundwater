import copy
import numpy as np

# Written by Munish Sikka
#1) circshift/roll the mask for longitudes
#2) then flip it to position 0-359 and S-N to match GRACE grid
#alternatively users can also adjust GRACE dataset to mask orientation
def shift_to_grace_orientation(shift_lon,flip_lat,data_array,indexes_to_shift,axis_no):
    if shift_lon:
        temp_1a = np.roll(data_array, indexes_to_shift, axis =axis_no)
    else:
        temp_1a = copy.copy(data_array)
    if flip_lat:
        reoriented_grid = np.flipud(temp_1a)
    else:
        reoriented_grid = copy.copy(temp_1a)  
    return reoriented_grid
