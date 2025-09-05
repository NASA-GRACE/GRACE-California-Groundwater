#!/usr/bin/env bash
set -euo pipefail  # Exit on error, undefined variable, or pipe failure

# Locate the directory that this script lives in, even if
# someone called it via a relative path or symlink.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Project root is one level up from scripts/
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"

confirm_delete_contents() {
    local target="$1"
    read -p "Are you sure you want to delete all files in '$target'? (y/N/q) " -n 1 -r
    echo    # move to a new line
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Deleting files in '$target'..."
        rm -rf "$target"/*
        echo "Files deleted."
    elif [[ $REPLY =~ ^[Qq]$ ]]; then  # Now check if they entered "q" or "Q" to quit
        echo "Quitting."
        exit 0
    else
        echo "Deletion cancelled."
    fi
}

# NO! THINK CAREFULLY ABOUT THE NEW DIR STRUCTURE BEFORE UNCOMMENTING THESE LINES
confirm_delete_contents "$PROJECT_ROOT/input_data/soil_moisture/NLDAS/data_monthly"
confirm_delete_contents "$PROJECT_ROOT/input_data/soil_moisture/NLDAS/data_concatenated"
confirm_delete_contents "$PROJECT_ROOT/input_data/masks"
confirm_delete_contents "$PROJECT_ROOT/input_data/masked_timeseries"
confirm_delete_contents "$PROJECT_ROOT/input_data/reservoirs/CDEC/reservoir_data"
confirm_delete_contents "$PROJECT_ROOT/input_data/reservoirs/CDEC/monthly_sums"
confirm_delete_contents "$PROJECT_ROOT/input_data/reservoirs/CDEC/monthly_anomaly"
confirm_delete_contents "$PROJECT_ROOT/input_data/snow_water_equivalent/SNODAS/daily_data"
confirm_delete_contents "$PROJECT_ROOT/input_data/snow_water_equivalent/SNODAS/masks/basin_masks"
confirm_delete_contents "$PROJECT_ROOT/input_data/snow_water_equivalent/SNODAS/masks/repaired_masks"
confirm_delete_contents "$PROJECT_ROOT/input_data/snow_water_equivalent/SNODAS/monthly_anomaly"
confirm_delete_contents "$PROJECT_ROOT/input_data/snow_water_equivalent/SNODAS/monthly_data"
confirm_delete_contents "$PROJECT_ROOT/input_data/grace_tws/masks"
confirm_delete_contents "$PROJECT_ROOT/input_data/grace_tws/monthly_grace_anomaly"
confirm_delete_contents "$PROJECT_ROOT/input_data/grace_tws/monthly_interpolated_grace_anomaly"
confirm_delete_contents "$PROJECT_ROOT/output"
# confirm_delete_contents "$PROJECT_ROOT/graphics"  # DO YOU *REALLY* WANT TO DELETE FILES IN THIS DIRECTORY?
