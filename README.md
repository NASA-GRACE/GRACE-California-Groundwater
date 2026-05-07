# Groundwater Toolkit Quickstart Guide

#### J.T. Reager<sup>1</sup>, Felix Landerer<sup>1</sup>, Munish Sikka<sup>1</sup>, Emmy Killett<sup>1</sup>
#### <sup>1</sup>Jet Propulsion Laboratory, California Institute of Technology, Pasadena, CA, USA

---

## Table of Contents
- [1. Introduction](#1-introduction)
- [2. Pipeline & Runbook (overview)](#2-pipeline--runbook-overview)
- [3. Run orchestration (`run_all.py`)](#3-run-orchestration-run_allpy)
- [4. GRACE (Total Water Storage, TWS)](#4-grace-total-water-storage-tws)
  - [4.1 GRACE: Data & Masks](#41-grace-data--masks)
  - [4.2 GRACE: Anomalies](#42-grace-anomalies)
  - [4.3 GRACE: Mid-Month Alignment](#43-grace-mid-month-alignment)
- [5. SNODAS SWE (snow water equivalent)](#5-snodas-swe-snow-water-equivalent)
  - [5.1 Download + Monthly Means](#51-download--monthly-means)
  - [5.2 Basin Masks for SWE](#52-basin-masks-for-swe)
  - [5.3 SWE Basin Anomalies](#53-swe-basin-anomalies)
- [6. Soil Moisture (NLDAS)](#6-soil-moisture-nldas)
  - [6.1 Download](#61-download)
  - [6.2 Process & Mask](#62-process--mask)
  - [6.3 Basin Anomalies & Maps](#63-basin-anomalies--maps)
- [7. CDEC Reservoirs (mass)](#7-cdec-reservoirs-mass)
  - [7.1 Download](#71-download)
  - [7.2 Regional Sums & Mapping](#72-regional-sums--mapping)
  - [7.3 Regional Anomalies & Errors](#73-regional-anomalies--errors)
- [8. Groundwater (final synthesis)](#8-groundwater-final-synthesis)
- [9. Appendices](#9-appendices)
  - [9.1 Data directories & naming conventions](#91-data-directories--naming-conventions)
  - [9.2 Troubleshooting](#92-troubleshooting)

---

## 1. Introduction

This toolkit produces basin‐scale **groundwater storage anomalies** by combining multiple hydrologic data sources into a coherent, reproducible workflow. It is designed for rapid testing over a short window and for full historical runs with robust logging, QC, and exportable artifacts (CSV/NetCDF/plots).

***
### What problem are we solving?
GRACE satellites measure **total water storage (TWS)** changes. To isolate **groundwater**, we subtract other major storage components over the same region and period:

> **Groundwater = GRACE TWS − (Snow Water Equivalent + Soil Moisture + Reservoirs)**

All inputs are aligned monthly, converted to consistent units, mean-removed over a baseline, and combined with **propagated uncertainties**.

***
### Datasets (high-level)
- **Soil Moisture** from **NLDAS** → subset, masked, and converted to basin time series.
- **Reservoirs** from **CDEC** → site-level storage (AF) fetched and converted to m³, summed to basin monthly volumes.
- **GRACE TWS** (mascon solution) → JPL Mascon CRI granules from PO.DAAC, masked and area-averaged for the basin.
- **Snow Water Equivalent (SWE)** from **SNODAS** → downloaded daily, converted to monthly means, then area-weighted and mean-removed.  

All four series output **(value, error)** columns and share the same monthly timestamp convention.

***
### How the pieces fit together
1. **Masks**: Basin polygons are rasterized to each gridded dataset and used to extract/aggregate values.
2. **Ingestion & Pre-processing**: Download all components (SNODAS, NLDAS, CDEC, GRACE); align GRACE TWS to mid-month.
3. **Basin Time Series**: Apply masks, compute area-weighted means/sums, and export CSVs with errors.
4. **Anomalies & Baselines**: Remove the mean over an adaptive baseline (requested vs. available overlap).
5. **Groundwater Synthesis**: `compute_groundwater.py` aligns months, subtracts components from GRACE, and **propagates error** assuming independence (variance additivity).  
6. **Outputs & Plots**: Monthly unsmoothed, monthly smoothed (e.g., 3-mo), calendar-year and water-year averages; plots for inspection.

***
### What you can run (quick start)
- **Smoke test**: From the `scripts` directory run `python run_all.py` (short test period).  
- **Full history**: Run `python run_all.py --full`. This requires ~40 GB, mostly for SNODAS files. The first time this is run, it will take 10 hours or more, mostly because of the need to cache monthly SNODAS files. Subsequent runs will be significantly faster.
Both produce intermediate CSVs/plots and final groundwater products in `input_data/masked_timeseries` and `output/`.

***
### Key assumptions
- **Independence of errors** across components when propagating uncertainty.  
- **Monthly alignment**: All series are resampled to a common monthly timestamp (mid-month convention).  
- **Unit consistency**: Volumes are in **km³** for basin totals; GRACE/NLDAS/SNODAS anomalies are in mm-equivalent then converted/aggregated as needed.  
- **Adaptive baselines** ensure a valid mean-removal window even when the requested baseline partially falls outside the available record.

***
### Where to look for details (cross-references)
- **Pipeline & Runbook** — end-to-end flow, copy-paste run sequences, expected artifacts.
- **Run orchestration (run_all.py)** — CLI flags, logging, environment/venv guidance.
- **GRACE TWS** — masks, anomaly generation, interpolation to mid-month, plotting.
- **SNODAS SWE** — daily downloader → monthly means, mask creation, anomalies, spot checks.
- **Soil Moisture (NLDAS)** — preprocessing, masking, timeseries extraction, plotting.
- **CDEC Reservoirs** — data sources/endpoints, units & AF→m³ conversion, basin aggregation, QC.
- **Groundwater (final synthesis)** — `compute_groundwater.py` inputs, alignment, error propagation, outputs.
- **Appendix — Data directories & naming** — canonical paths, file patterns.
- **Appendix — Troubleshooting** — download hiccups, GDAL pitfalls, mask/grid mismatches, baselines, plotting, venv, quick fixes.

***
### Outputs at a glance
- **Timeseries CSVs** per component and **groundwater** (monthly unsmoothed, smoothed), plus **calendar** and **water-year** averages.
- **Plots** summarizing each component and a comparison figure including groundwater.
- **Logged provenance** (headers with source URLs/attributes) for downstream audit.

***
### Audience
Hydrologists, water resources analysts, and data practitioners who need a transparent, scriptable path from raw satellite/terrestrial data to basin-scale **groundwater anomaly** products.

---

## 2. Pipeline & Runbook (overview)
High-level stages (see full run sequence in `scripts/run_all.py`):
1) **Soil Moisture (NLDAS)**: download → process NetCDF → create mask → masked timeseries → plots.
2) **Reservoirs (CDEC)**: download (CSV) → site→region mapping → monthly sums by region → anomalies/errors → plots.
3) **GRACE**: download → create raster mask → compute anomalies → interpolate to mid-month → plots.
4) **SWE (SNODAS)**: download daily → monthly means → SWE mask → basin anomalies → plots.
5) **Groundwater**: align series, remove means over baseline, compute groundwater anomaly + smoothed/calendar/water-year outputs → plots.

Key artifacts per stage are written under `input_data/**` and `input_data/masked_timeseries` with final figures in `graphics/` and outputs in `output/`. See directory conventions in [§9.1](#91-data-directories--naming-conventions).

---

## 3. Run orchestration (`run_all.py`)
**Quick test run** (from `scripts/`):
```bash
python run_all.py
```
Uses `test_start=2005-01-01` to `test_end=2005-03-31T23:59:59` for a fast check. Passing the `--dry_run` flag skips execution but shows what commands *would* be run.

**Full run**:
```bash
python run_all.py --full
```
Propagates `--full` and `--debug` flags to each stage. Chooses venv Python if available at `scripts/.venv/bin/python`, else system Python. See `run_all.py` for section ordering and logging.

Supported basins: California (default), Sacramento, San Joaquin, Tulare-Buena Vista Lakes.

**Pre-run checks** (abbrev): Python 3.11+, GDAL installed, write access to project folders, Earthdata Login prerequisite files (.netrc, .urs_cookies) configured for GRACE and NLDAS downloads, network access for GRACE/SNODAS/CDEC endpoints, shapefiles present, and environment variables for optional tools (FFmpeg) if used.

---

## 4. GRACE (Total Water Storage, TWS)

### 4.1 GRACE: Data & Masks
- **Download**: `grace_download.py` fetches JPL Mascon CRI granules from PO.DAAC via `earthaccess` (requires Earthdata Login prerequisites).
- **Data**: GRACE/GRACE-FO mascon NetCDF files in `input_data/grace_tws/`.
- **Masking**: `call_raster_mask_generator.py` with target dataset = GRACE NetCDF.
  - Selects basin polygon (HYBAS/WBDHU4) → rasterizes to the GRACE grid.
  - Outputs mask CSV under `input_data/grace_tws/masks/`.
- **Spot checks**: CRS/geotransform match, mask footprint within basin, correct variable names (lat/lon).

### 4.2 GRACE: Anomalies
- `grace_tws_anomaly.py` computes basin-average anomalies from masked GRACE.
- **Baseline**: adaptive—intersects requested baseline (default 2004–2009) with available data; logged in headers.
- **Outputs**: `anomaly_timeseries_GRACE_<basin>_mask.csv` in `input_data/masked_timeseries/` plus plots in `graphics/`.

### 4.3 GRACE: Mid-Month Alignment
- `interpolate_grace.py` resamples the GRACE anomaly series onto the 15th of each month, so it lines up with the other monthly series. Months with no original solution are dropped, not filled.

---

## 5. SNODAS SWE (snow water equivalent)

### 5.1 Download + Monthly Means
- `swe_daily_downloader_and_monthly_mean.py`:
  - Downloads daily SNODAS files from `https://noaadata.apps.nsidc.org/NOAA/G02158/masked/<YYYY>/<MM_Mon>/SNODAS_YYYYMMDD.tar`.
  - Extracts, gunzips, converts to GeoTIFF, and computes **monthly means** with missing-day suffix logic.
  - Cleans up daily GeoTIFFs unless last month is incomplete.
  - **Outputs**: daily GeoTIFFs in `input_data/snow_water_equivalent/SNODAS/daily_data/` and monthly means in `.../monthly_data/`.

**Spot checks before running**
- Disk space for daily TARs and GeoTIFFs.
- GDAL operational (`gdalinfo --version`).
- Confirm date window and that end-month completeness rules fit the analysis.

### 5.2 Basin Masks for SWE
- `call_raster_mask_generator.py --target_dataset swe`:
  - Opens a representative monthly GeoTIFF → derives grid → rasterizes basin shapefile to SWE grid.
  - Saves mask CSV to `.../SNODAS/masks/basin_masks/`.

### 5.3 SWE Basin Anomalies
- `swe_monthly_anomaly.py`:
  - Loads monthly SWE GeoTIFFs, computes **area-weighted** basin sums using lat-dependent cell areas, converts to km³, and removes baseline mean (adaptive).
  - **Outputs**: `anomaly_timeseries_SNODAS_<basin>_mask.csv` in `input_data/masked_timeseries/`.

---

## 6. Soil Moisture (NLDAS)

### 6.1 Download
- `soil_moisture_download.py` fetches NLDAS VIC LSM L4 Monthly 0.125° v2.0 (DOI `10.5067/NL7JTZYO2RVK`) via `earthaccess` (requires Earthdata Login prerequisites).
- **Outputs**: per-month NetCDFs in `input_data/soil_moisture/NLDAS/data_individual/`.

### 6.2 Process & Mask
- `soil_moisture_process.py` concatenates the per-month NetCDFs into a single time-stacked file in `.../NLDAS/data_concatenated/`.
- `soil_moisture_create_mask.py` rasterizes the basin polygon onto the NLDAS grid and writes a mask NetCDF (e.g., `NLDAS_<basin>_mask.nc`) to `input_data/masks/`; it auto-corrects a swapped lat/lon layout if encountered.

### 6.3 Basin Anomalies & Maps
- `soil_moisture_mask_timeseries.py` applies the mask, computes the basin-mean soil moisture anomaly (variable `SMTa`) over the adaptive baseline, and writes both a CSV time series and a gridded NetCDF subset. **Outputs**: `anomaly_timeseries_NLDAS_<basin>_mask*.csv` (and matching `.nc`) in `input_data/masked_timeseries/`.
- `soil_moisture_map_fields.py` produces a time-mean anomaly map and (if `ffmpeg` is available) a movie of the masked NetCDF. **Outputs**: PNG/MP4 in `graphics/`.

---

## 7. CDEC Reservoirs (mass)

### 7.1 Download
- `reservoirs_download.py` pulls CSVs from CDEC (`CSVDataServlet`) for a station list.
- Converts storage to **m³** (from acre-feet) and saves per-station files plus a combined file.
- Handles sensor fallbacks (e.g., 15 → 69), header/units parsing, and logs failures.

### 7.2 Regional Sums & Mapping
- `reservoirs_monthly_sums.py`:
  - Maps stations to basin polygons (HYBAS/WBDHU4 or SORT for statewide) and builds **monthly sums**.
  - **Outputs**: `<region>_monthly_km3.csv` in `.../CDEC/monthly_sums/` (values in km³) and mapping CSVs (`sites_<region>.csv`).

### 7.3 Regional Anomalies & Errors
- `reservoirs_regional_anomaly_mean_err_vals.py`:
  - Reads each `<region>_monthly_km3.csv`, computes **error = |value|×err_val** and **anomaly = value − baseline_mean** (adaptive baseline via `run_all.compute_baseline`).
  - **Outputs**: `anomaly_timeseries_CDEC_<region>_mask.csv` in `input_data/masked_timeseries/` with header provenance.

---

## 8. Groundwater (final synthesis)
- `compute_groundwater.py` aligns **GRACE**, **SNODAS**, **NLDAS**, and **CDEC** monthly series on common months, drops any months with missing components, and removes means over the **actual baseline window** (intersection of requested vs available).
- **Formula**: `groundwater = grace − (swe + soilm + reservoirs)`.
- **Uncertainty propagation** (assumed independent):
  \[ \sigma_{gw} = \sqrt{\sigma_{grace}^2 + \sigma_{swe}^2 + \sigma_{soilm}^2 + \sigma_{reservoirs}^2} \]
- **Outputs** (all with commented headers carrying source metadata):
  - Monthly **unsmoothed** anomalies.
  - Monthly **smoothed** (groundwater estimate and its error only, centered 3-month window; components remain unsmoothed).
  - **Calendar-year** averages (YE-DEC) and **Water-year** averages (Oct–Sep).
- See also plotting stage for multi-component comparisons.

---

## 9. Appendices

### 9.1 Data directories & naming conventions
- **Top-level** under project root:
  - `input_data/` → raw & processed component inputs
    - `grace_tws/`, `snow_water_equivalent/SNODAS/`, `soil_moisture/NLDAS/`, `reservoirs/CDEC/`
    - `masked_timeseries/` → component anomalies per basin (CSV)
    - `shapefiles/` (basin polygons, HYBAS/WBDHU4), `masks/` (NLDAS basin masks)
  - `graphics/` → plots; `output/` → final exports; `scripts/` → Python scripts
- **File naming** examples:
  - GRACE anomalies: `anomaly_timeseries_GRACE_<basin>_mask.csv`
  - SWE monthly mean: `monthly_mean_YYYYMM_DD_DD[_missing_..].tif`
  - CDEC regional sums: `<region>_monthly_km3.csv`
  - Groundwater: `anomaly_timeseries_groundwater_<basin>_DATA_START_to_DATA_END_*.csv`

### 9.2 Troubleshooting
- **CMR/HTTP hiccups**: retry downloads, verify endpoints, check network/VPN, respect rate limiting.
- **GDAL pitfalls**: CRS mismatches, nodata handling, geotransform ordering; confirm with `gdalinfo` and test small windows.
- **Mask/grid mismatches**: ensure mask grid matches the **target** dataset grid (rasterize with the dataset’s geotransform).
- **Missing months**: SWE monthly filenames encode missing-day info via a filename suffix. GRACE months with no solution are dropped by `interpolate_grace.py` rather than filled — `compute_groundwater.py` will then drop those months from the synthesis when it aligns components.
- **CDEC units**: confirm converted to **m³**; check sensor numbers; scan logs for “Units not M3”.

---
