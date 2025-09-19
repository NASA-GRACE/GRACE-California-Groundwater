import argparse
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
from pathlib import Path
from io import StringIO # Import StringIO

import run_all as ra

#Written by Felix Landerer, Munish Sikka, Gemini and ChatGPT

# CDEC sensor ID for storage in Acre-Feet
STORAGE_SENSOR_AF     = "15" # Primary sensor for storage
ALT_STORAGE_SENSOR_AF = "69" # Alternative sensor, often for more current daily

# CDEC base URL for CSV data
CDEC_BASE_URL = "https://cdec.water.ca.gov/dynamicapp/req/CSVDataServlet"

# Conversion factor
ACRE_FEET_TO_CUBIC_METERS = 1233.4818375475


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:                 str = Path(__file__).stem  # The name of this script without the .py extension
        self.default_csv_file:       Path = self.reservoirs_dir / f"{self.reservoirs_model.lower()}_data_webpage.csv"  # default reservoir list file
        self.default_out_dir:        Path = self.reservoirs_dir / "reservoir_data"
        self.default_data_type_input: str = "M"

def parse_arguments(options: Options) -> None:
    """Parse command-line arguments into options.args."""
    parser = argparse.ArgumentParser(description=f"Download {options.reservoirs_model} monthly sites data")
    parser.add_argument("--reservoir_list_file", default=options.default_csv_file,
                        help=f"CSV file containing reservoir names and station IDs (default: '{options.default_csv_file}')")
    parser.add_argument("--output_dir", default=options.default_out_dir,
                        help=f"Directory for outputting {options.reservoirs_model} data (default: '{options.default_out_dir}')")
    parser.add_argument("--data_type_input", default=options.default_data_type_input,
                        help="download monthly data for reservoirs.")
    parser.add_argument("--start_date_str_input", default=options.test_start,
                        help=f"Start date (YYYY-MM-DD) (default: {options.test_start})")
    parser.add_argument("--end_date_str_input", default=options.test_end,
                        help=f"End date (YYYY-MM-DD) (default: {options.test_end})")
    parser.add_argument("--full", action="store_true",
                        help=f"If set, download the full timespan ({options.full_start} - {options.full_end}).")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Run this program in debug mode, which prints additional debug messages.")
    options.args = parser.parse_args()
    if getattr(options.args, "debug", False):
        options.log_mode = logging.DEBUG
    if options.args.full:
        options.args.start_date_str_input, options.args.end_date_str_input = options.full_start, options.full_end
    # Format dates as YYYY-MM-DD regardless of their original format by parsing and reformatting.
    options.args.start_date_str_input = (ra.parse_datetime(options.args.start_date_str_input)).strftime("%Y-%m-%d")
    options.args.end_date_str_input   = (ra.parse_datetime(options.args.end_date_str_input  )).strftime("%Y-%m-%d")

def main() -> None:
    """Main function to download reservoirs data."""
    options = Options()
    parse_arguments(options)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    if options.reservoirs_model == "CDEC":
        reservoirs_download_CDEC(options)
    else:
        raise ValueError(f"Unsupported reservoirs model: {options.reservoirs_model}")


def reservoirs_download_CDEC(options: Options) -> None:
    """
    Download reservoirs data from CDEC.
    
    Args:
        options: An Options instance with parsed command line arguments in options.args. Contains:
           - reservoir_list_file: CSV file containing reservoir names and station IDs.
           - output_dir:          Directory for outputting reservoirs data.
    
    Returns:
        None. Downloads data and saves to output_dir.
    
    Raises:
        ValueError: If start date is after end date.
    """
    reservoir_list_file = options.args.reservoir_list_file
    output_dir          = options.args.output_dir

    logging.info("CDEC Reservoir Data Downloader")
    logging.info("------------------------------")

    # --- Load reservoirs from file ---
    reservoirs_to_fetch = load_reservoirs_from_file(reservoir_list_file)
    if not reservoirs_to_fetch:
        logging.error(f"Exiting: Could not load reservoir list from '{reservoir_list_file}'.")
        return # Exit if reservoir list can't be loaded

    duration_code = options.args.data_type_input
    time_period_name = "Daily" if duration_code == "D" else "Monthly"

    if not options.args.end_date_str_input:
        end_date = datetime.now() - timedelta(days=1)
    else:
        end_date = datetime.strptime(options.args.end_date_str_input, "%Y-%m-%d")

    if duration_code == "D":
        default_start_days = 30
        period_name_prompt = "days"
    else:
        default_start_days = 365 * 2 # Default to 2 years for monthly, 5 can be a lot
        period_name_prompt = f"days (for ~{default_start_days//365} years of monthly data)"

    if not options.args.start_date_str_input:
        start_date = end_date - timedelta(days=default_start_days)
    else:
        start_date = datetime.strptime(options.args.start_date_str_input, "%Y-%m-%d")

    if start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    start_date_str_cdec = start_date.strftime("%Y-%m-%d")
    end_date_str_cdec   =   end_date.strftime("%Y-%m-%d")

    logging.info(f"\nFetching {time_period_name} reservoir storage data from {start_date_str_cdec} to {end_date_str_cdec} (units will be M3)...\n")

     
    os.makedirs(output_dir, exist_ok=True)
    logging.info(f"Data will be saved in the '{output_dir}' directory.")

    all_data_frames = {}
    failed_reservoirs_details = [] # Store (name, station_id, reason)

    for reservoir_info in reservoirs_to_fetch:
        name = reservoir_info["name"]
        station_id = reservoir_info["id"]
        logging.info(f"Fetching data for {name} ({station_id})...")

        df_reservoir = None
        current_sensor_used = STORAGE_SENSOR_AF # Assume primary sensor first
        
        # Try primary sensor
        df_reservoir = get_cdec_data(station_id, STORAGE_SENSOR_AF, duration_code, start_date_str_cdec, end_date_str_cdec)

        # If primary fails or returns no usable data, and it's daily, try alternative sensor
        if not (df_reservoir is not None and not df_reservoir.empty and 'VALUE' in df_reservoir.columns and df_reservoir['UNITS'].iloc[0] == 'M3'):
            if duration_code == "D": 
                logging.info(f"  Primary sensor {STORAGE_SENSOR_AF} failed or data not convertible for {name}. Trying sensor {ALT_STORAGE_SENSOR_AF}...")
                df_reservoir_alt = get_cdec_data(station_id, ALT_STORAGE_SENSOR_AF, duration_code, start_date_str_cdec, end_date_str_cdec)
                if df_reservoir_alt is not None and not df_reservoir_alt.empty and 'VALUE' in df_reservoir_alt.columns and df_reservoir_alt['UNITS'].iloc[0] == 'M3':
                    df_reservoir = df_reservoir_alt # Use data from alternative sensor
                    current_sensor_used = ALT_STORAGE_SENSOR_AF
                else:
                    logging.warning(f"  Alternative sensor {ALT_STORAGE_SENSOR_AF} also failed or data not convertible for {name}.")
            # If not daily, or if alt sensor also failed for daily
            if not (df_reservoir is not None and not df_reservoir.empty and 'VALUE' in df_reservoir.columns and df_reservoir['UNITS'].iloc[0] == 'M3'):
                 # Check if df_reservoir has any data at all, even if not M3 (e.g. original units warning)
                if df_reservoir is not None and not df_reservoir.empty and 'VALUE' in df_reservoir.columns:
                    # Data exists but wasn't converted to M3 (e.g., original units were not AF)
                    # We can still save this data if the user wants, but it won't be in M3.
                    # For simplicity in this version, we'll treat it as a "failed M3 conversion" for the combined file.
                    logging.info(f"  Data found for {name} (Sensor {current_sensor_used}) but units are not M3 (Original units: {df_reservoir['UNITS'].iloc[0] if 'UNITS' in df_reservoir.columns and not df_reservoir['UNITS'].empty else 'Unknown'}). Will save individual file if possible.")
                    # Save this non-M3 data individually
                    filename_suffix = f"_sensor{current_sensor_used}" if current_sensor_used != STORAGE_SENSOR_AF else ""
                    original_unit_tag = df_reservoir['UNITS'].iloc[0] if 'UNITS' in df_reservoir.columns and not df_reservoir['UNITS'].empty else "UNKNOWN_UNITS"
                    filename = f"{station_id}{filename_suffix}_{time_period_name.lower()}_{original_unit_tag}_{start_date_str_cdec}_to_{end_date_str_cdec}.csv"
                    filepath = os.path.join(output_dir, filename)
                    try:
                        df_reservoir.to_csv(filepath, index=False)
                        logging.info(f"  Successfully saved data for {name} (Sensor: {current_sensor_used}, Units: {original_unit_tag}) to {filepath}")
                    except Exception as e:
                        logging.error(f"  Error saving non-M3 data for {name} to {filepath}: {e}")
                    failed_reservoirs_details.append({"name": name, "id": station_id, "reason": f"Units not M3 (were {original_unit_tag})"})
                    df_reservoir = None # Nullify so it's not added to M3 combined list
                else:
                    failed_reservoirs_details.append({"name": name, "id": station_id, "reason": "No data or processing error"})


        if df_reservoir is not None and not df_reservoir.empty and 'VALUE' in df_reservoir.columns and df_reservoir['UNITS'].iloc[0] == 'M3':
            all_data_frames[name] = df_reservoir # Add to list for combined M3 file
            filename_suffix = f"_sensor{current_sensor_used}" if current_sensor_used != STORAGE_SENSOR_AF else ""
            filename = f"{station_id}{filename_suffix}_{time_period_name.lower()}_m3_{start_date_str_cdec}_to_{end_date_str_cdec}.csv"
            filepath = os.path.join(output_dir, filename)
            try:
                df_reservoir.to_csv(filepath, index=False)
                logging.info(f"  Successfully saved M3 data for {name} (Sensor: {current_sensor_used}) to {filepath}")
            except Exception as e:
                logging.error(f"  Error saving M3 data for {name} to {filepath}: {e}")
        elif df_reservoir is None and not any(d['id'] == station_id for d in failed_reservoirs_details): # If it wasn't already added to failed list for other reasons
            # This case handles if df_reservoir became None after all checks
            failed_reservoirs_details.append({"name": name, "id": station_id, "reason": "No M3 data after processing"})

        logging.info("-" * 40)

    if all_data_frames: # Only combine if there's M3 data
        logging.info("Combining all successfully fetched M3 data into a single file...")
        combined_df_list = []
        for reservoir_name_key, df_item in all_data_frames.items():
            df_copy = df_item.copy()
            df_copy.loc[:, 'RESERVOIR_NAME'] = reservoir_name_key
            # Ensure original station ID is present from the input list
            # Find the original station ID from the reservoirs_to_fetch list
            original_station_id = next((res['id'] for res in reservoirs_to_fetch if res['name'] == reservoir_name_key), None)
            if original_station_id:
                 df_copy.loc[:, 'STATION_ID_INPUT'] = original_station_id
            combined_df_list.append(df_copy)

        if combined_df_list:
            final_combined_df = pd.concat(combined_df_list, ignore_index=True)
            combined_filename = f"all_reservoirs_combined_{time_period_name.lower()}_m3_{start_date_str_cdec}_to_{end_date_str_cdec}.csv"
            combined_filepath = os.path.join(output_dir, combined_filename)
            try:
                final_combined_df.to_csv(combined_filepath, index=False)
                logging.info(f"Successfully saved combined M3 data to {combined_filepath}")
            except Exception as e:
                logging.error(f"Error saving combined M3 data to {combined_filepath}: {e}")
        else:
            logging.warning("No M3 dataframes were available to combine.")
    else:
        logging.warning("No data was successfully fetched and converted to M3 for any reservoir.")

    if failed_reservoirs_details:
        logging.info("Summary of reservoirs with issues or no M3 data:")
        for detail in failed_reservoirs_details:
            logging.info(f"- {detail['name']} ({detail['id']}): {detail['reason']}")

    logging.info("Script finished.")


def load_reservoirs_from_file(filepath: str) -> list[dict] | None:
    """
    Loads reservoir names and station IDs from a CSV file.

    Args:
        filepath: The path to the CSV file.
                  Expected columns: "Reservoir Name", "Station ID"

    Returns:
        A list of dictionaries, where each dictionary has "name" and "id" keys, or None if an error occurs.
    
    Raises:
        None. Catches exceptions (FileNotFoundError, pd.errors.EmptyDataError, etc.) and logs errors.
    """
    try:
        df = pd.read_csv(filepath)
        if "Reservoir Name" not in df.columns or "Station ID" not in df.columns:
            logging.error(f"The file '{filepath}' must contain 'Reservoir Name' and 'Station ID' columns.")
            return None
        
        # Strip any leading/trailing whitespace from column names and values
        df.columns = [col.strip() for col in df.columns]
        df["Reservoir Name"] = df["Reservoir Name"].astype(str).str.strip()
        df["Station ID"] = df["Station ID"].astype(str).str.strip()

        # Drop rows where Station ID might be missing after stripping
        df.dropna(subset=["Station ID"], inplace=True)
        df = df[df["Station ID"] != '']


        reservoirs_list = []
        for index, row in df.iterrows():
            reservoirs_list.append({"name": row["Reservoir Name"], "id": row["Station ID"]})
        
        if not reservoirs_list:
            logging.warning(f"No valid reservoir entries found in '{filepath}'.")
            return None

        logging.info(f"Successfully loaded {len(reservoirs_list)} reservoirs from '{filepath}'.")
        return reservoirs_list
    except FileNotFoundError:
        logging.error(f"Reservoir list file '{filepath}' not found. Please create it.")
        logging.error(f"The file should be a CSV with columns: Reservoir Name,Station ID")
        return None
    except pd.errors.EmptyDataError:
        logging.error(f"The file '{filepath}' is empty.")
        return None
    except Exception as e:
        logging.error(f"Error reading reservoir list file '{filepath}': {e}")
        return None


def get_cdec_data(station_id: str, sensor_num: str, duration_code: str,
                  start_date_str: str, end_date_str: str) -> pd.DataFrame | None:
    """
    Fetches data from CDEC and converts storage to cubic meters.

    Args:
        station_id:     The CDEC station ID (e.g., "SHA").
        sensor_num:     The sensor number (e.g., "15" for storage).
        duration_code:  "D" for daily, "M" for monthly.
        start_date_str: Start date in "YYYY-MM-DD" format.
        end_date_str:   End date in "YYYY-MM-DD" format.

    Returns:
        A Pandas DataFrame containing the data with storage in cubic meters, or None if an error occurs.
    
    Raises:
        None. Catches exceptions and logs errors.
    """
    params = {
        "Stations": station_id,
        "SensorNums": sensor_num,
        "dur_code": duration_code,
        "Start": start_date_str,
        "End": end_date_str,
    }
    logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"  Requesting URL: {CDEC_BASE_URL} with params: {params}")

    try:
        response = requests.get(CDEC_BASE_URL, params=params, timeout=45)
        response.raise_for_status()

        response_text_upper = response.text.strip().upper()
        if response_text_upper.startswith("<!DOCTYPE HTML") or \
           response_text_upper.startswith("<HTML>") or \
           "<TITLE>ERROR</TITLE>" in response_text_upper:
            logging.warning(f"Received HTML error page for {station_id} (Sensor: {sensor_num}, Duration: {duration_code}).")
            return None
        if not response.text.strip() or "NO DATA FOUND" in response_text_upper or "NO DATA AVAILABLE" in response_text_upper :
            logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"  Info: No data found for {station_id} with sensor {sensor_num} for the given period and duration.")
            return None

        lines = response.text.splitlines()
        header_row_index = -1
        possible_headers = ["STATION_ID", "DATE TIME", "OBS DATE", "DATETIME"] # Common CDEC headers
        for i, line in enumerate(lines):
            # Check if any of the possible headers start the line
            if any(line.upper().strip().startswith(h) for h in possible_headers):
                header_row_index = i
                break
        
        if header_row_index == -1: # If no standard header found, look for a line with 'VALUE' and multiple commas
            for i, line in enumerate(lines):
                if 'VALUE' in line.upper() and line.count(',') > 1:
                    header_row_index = i
                    break
        
        if header_row_index == -1:
            if len(lines) < 5 and ("NO DATA" in response.text.upper() or "ERROR" in response.text.upper()):
                logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"  Info: No data or error message for {station_id} (Sensor: {sensor_num}, Duration: {duration_code}). Response: {response.text[:100]}")
                return None
            logging.warning(f"Could not reliably determine header row for {station_id} (Sensor {sensor_num}).")
            logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"  Problematic response text snippet for header detection: {' '.join(lines[:5])}")
            return None

        csv_data_io = StringIO("\n".join(lines[header_row_index:]))
        df = pd.read_csv(csv_data_io)

        if df.empty:
            logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"  Info: Dataframe is empty for {station_id} after parsing.")
            return None

        df.columns = [str(col).strip().upper().replace(" ", "_") for col in df.columns]

        datetime_candidates = ['DATE_TIME', 'DATETIME', 'OBS_DATE']
        datetime_processed_flag = False # To ensure we only rename once
        for candidate in datetime_candidates:
            if candidate in df.columns and not datetime_processed_flag:
                df.rename(columns={candidate: 'DATETIME'}, inplace=True)
                datetime_processed_flag = True 
                break
        
        if 'DATETIME' not in df.columns:
            logging.warning(f"No standard DATETIME column found for {station_id}. Available: {df.columns.tolist()}")
        else:
            df['DATETIME'] = pd.to_datetime(df['DATETIME'], errors='coerce')
            df.dropna(subset=['DATETIME'], inplace=True)
            if df.empty: # Check if all rows were dropped
                return None


        value_candidates = ['VALUE', 'STORAGE_AF', 'STORAGE,_AF']
        renamed_value_col = False
        original_units = None
        if 'UNITS' in df.columns:
            if not df['UNITS'].empty:
                # Use .iloc[0] if mode is empty or to be more direct if units are consistent
                try:
                    original_units = df['UNITS'].mode()[0] if not df['UNITS'].mode().empty else df['UNITS'].iloc[0]
                except IndexError:
                    original_units = "ACRE-FEET" # Fallback if UNITS column is all NaN or empty
            else: # UNITS column exists but is all empty/NaN
                original_units = "ACRE-FEET"
        else: # UNITS column does not exist
            original_units = "ACRE-FEET" # Default assumption if no units column


        for val_col_name in value_candidates:
            if val_col_name in df.columns:
                df.rename(columns={val_col_name: 'VALUE'}, inplace=True)
                renamed_value_col = True
                break
        
        if not renamed_value_col and 'VALUE' not in df.columns:
            numeric_cols = df.select_dtypes(include='number').columns
            potential_value_cols = [
                col for col in numeric_cols
                if col not in ['SENSOR_NUM', 'DURATION', 'HOUR', 'MINUTE', 'SECOND'] # Add other known non-value numeric columns
            ]
            if len(potential_value_cols) == 1:
                df.rename(columns={potential_value_cols[0]: 'VALUE'}, inplace=True)
                logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"  Inferred 'VALUE' column from '{potential_value_cols[0]}'.")
            # Silently proceed if cannot infer, will be caught by next 'VALUE' in df.columns check

        if 'VALUE' in df.columns:
            df['VALUE'] = pd.to_numeric(df['VALUE'], errors='coerce')
            df.dropna(subset=['VALUE'], inplace=True)
            if df.empty: return None # All values became NaN or were NaN
            
            perform_conversion = False
            if original_units: # original_units is now guaranteed to be a string
                if original_units.upper() in ["ACRE-FEET", "ACRE FEET", "AF", "STORAGE AF"]: # Added "STORAGE AF"
                    perform_conversion = True
            # If original_units was not conclusive (e.g. "UNKNOWN"), but sensor is known storage sensor
            elif sensor_num in [STORAGE_SENSOR_AF, ALT_STORAGE_SENSOR_AF]:
                perform_conversion = True

            if perform_conversion:
                logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"  Converting 'VALUE' from Acre-Feet to Cubic Meters for {station_id}.")
                df['VALUE_M3'] = df['VALUE'] * ACRE_FEET_TO_CUBIC_METERS
                df['UNITS'] = 'M3'
                # Keep original value column for reference if desired, or drop it
                # df.drop(columns=['VALUE'], inplace=True)
                # df.rename(columns={'VALUE_M3': 'VALUE'}, inplace=True)
            elif 'UNITS' not in df.columns:
                df['UNITS'] = 'UNKNOWN' # If units couldn't be determined and not converted
            elif original_units and not perform_conversion: # Original units were not AF
                logging.warning(f"Original units for {station_id} (Sensor {sensor_num}) were '{original_units}'. Value not converted to M3. Output units will reflect original.")
                # df['UNITS'] will retain its original_units value
            
            # Ensure the primary value column is named 'VALUE' and contains the M3 data if converted
            if 'VALUE_M3' in df.columns:
                df.drop(columns=['VALUE'], inplace=True, errors='ignore') # drop original AF value
                df.rename(columns={'VALUE_M3': 'VALUE'}, inplace=True)

        else:
            logging.critical(f"'VALUE' column could not be identified or created for {station_id} (Sensor {sensor_num}). Columns: {df.columns.tolist()}")
            return None

        # Select and order essential columns if they exist
        # Ensure 'VALUE' (now in M3 if converted) and 'UNITS' (now 'M3' if converted) are primary
        essential_cols = ['STATION_ID', 'DATETIME', 'VALUE', 'UNITS']
        # Add other potentially useful columns from CDEC output
        optional_cols = ['SENSOR_NUMBER', 'DURATION', 'MEASUREMENT_METHOD', 'DATA_FLAG', 'VALUE_UNCORRECTED']
        
        output_cols = []
        for col in essential_cols + optional_cols:
            if col in df.columns and col not in output_cols:
                output_cols.append(col)
        
        # Add any remaining columns not explicitly listed
        other_cols = [col for col in df.columns if col not in output_cols]
        final_cols = output_cols + other_cols
        
        return df[final_cols]

    except requests.exceptions.Timeout:
        logging.error(f"Timeout occurred while fetching data for {station_id} (Sensor {sensor_num}).")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Request failed for {station_id} (Sensor {sensor_num}): {e}")
        return None
    except pd.errors.EmptyDataError:
        logging.getLogger().isEnabledFor(logging.DEBUG) and logging.debug(f"No data returned in CSV for {station_id} (Sensor: {sensor_num}, Duration: {duration_code}).")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred while processing {station_id} (Sensor {sensor_num}): {e}")
        if 'response' in locals() and response is not None:
            logging.error(f"Problematic response text snippet: {response.text[:200]}")
        else:
            logging.error("Response object was not available for inspection.")
        return None


if __name__ == "__main__":
    main()

