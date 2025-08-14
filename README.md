This software suite downloads and processes data representing the mass of soil moisture,
snow water equivalent, and water in reservoirs. It masks these data using one of several
specified river basin masks, generates anomaly timeseries and estimates error bars, then
subtracts those masses from the total mass anomaly timeseries derived from GRACE over the
same river basin.


Important scripts:

scripts/run_all.py         - Runs the entire download/process/plot pipeline from start to finish.

scripts/delete_all_work.sh - Deletes everything created by run_all.py to restore a blank slate.

scripts/setup_venv.sh      - Creates a python virtual environment that can run all the scripts.

If using NLDAS or another model that requires earthdata authentication, the user needs to set up
that authentication first. Details in scripts/soil_moisture_download.py