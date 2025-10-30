#!/usr/bin/env python3
from __future__ import annotations

import sys
import shutil
from pathlib import Path
import argparse
import logging

import run_all as ra


class Options(ra.Options):
    """Class that has all global options in one place."""

    def __init__(self) -> None:
        """Initialize the options with values from run_all.Options and add script-specific defaults."""
        super().__init__()  # Defines script_dir, project_root, etc.
        self.my_name:  str = Path(__file__).stem  # The name of this script without the .py extension


def _delete_dir_contents(target: Path) -> None:
    """
    Recursively delete *contents* of `target` (like `rm -rf target/*`)
    but do not remove the target directory itself.
    """
    # Succeed if directory is empty or doesn't exist
    if not target.exists():
        logging.error(f"Path not found, skipping: {target}")
        return
    if not target.is_dir():
        logging.error(f"Not a directory, skipping: {target}")
        return

    # Extra safety: never allow nuking the whole project root itself
    options = Options()
    if target.resolve() == options.project_root.resolve():
        logging.error("Refusing to delete contents of the project root. Skipping.")
        return

    files_deleted = 0
    dirs_deleted = 0
    for child in target.iterdir():
        try:
            if child.is_symlink() or child.is_file():
                child.unlink(missing_ok=True)
                files_deleted += 1
            else:
                shutil.rmtree(child, ignore_errors=True)
                dirs_deleted += 1
        except Exception as e:
            logging.error(f"Warning: failed to remove {child}: {e}")
    if files_deleted > 0:
        logging.info(f"Files deleted:       {files_deleted}")
    if dirs_deleted > 0:
        logging.info(f"Directories deleted: {dirs_deleted}")
    if files_deleted == 0 and dirs_deleted == 0:
        logging.info("No files or directories to delete.")


def _confirm_delete_contents(target: Path, assume_yes: bool = False) -> None:
    """
    Prompt the user: (y/N/q). "y" deletes contents, "q" quits the script,
    anything else cancels for this target.
    """
    logging.info()  # nice spacing between prompts
    logging.info(f"Target: {target}")
    if assume_yes:
        reply = "y"
        logging.info(f"Are you sure you want to delete all files in '{target}'? (y/N/q) y  [--yes provided]")
    else:
        reply = input(f"Are you sure you want to delete all files in '{target}'? (y/N/q) ").strip().lower()[:1]

    if reply == "y":
        logging.info(f"Deleting files in '{target}'...")
        _delete_dir_contents(target)
    elif reply == "q":
        logging.info("Quitting.")
        sys.exit(0)
    else:
        logging.info("Deletion cancelled.")


def main(argv: list[str] | None = None) -> int:
    """
    Python conversion of the original bash cleaner.
    Preserves interactive confirmations and target list,
    using paths from run_all.Options where possible.
    """
    options = Options()
    parser  = argparse.ArgumentParser(description="Delete contents of specific input directories (interactive y/N/q prompts).")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Assume 'yes' for all prompts (non-interactive).")
    args = parser.parse_args(argv)
    logging.basicConfig(level=options.log_mode, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    targets: list[Path] = [
        options.soil_moisture_dir / "data_individual",
        options.soil_moisture_dir / "data_concatenated",
        options.swe_dir           / "masks"                               / "basin_masks",
        options.swe_dir           / "masks"                               / "repaired_masks",
        options.reservoirs_dir    / "reservoir_data",
        options.reservoirs_dir    / "monthly_sums",
        options.grace_dir         / "masks",
        options.grace_dir         / "monthly_grace_anomaly",
        options.grace_dir         / "monthly_interpolated_grace_anomaly",
        options.project_root      / "input_data"                          / "masks",
        options.timeseries_dir,
        options.output_dir,
    ]

    logging.info(f"{targets=}")
    sys.exit(0)

    # De-dup while preserving order (e.g., if two paths resolve the same)
    seen = set()
    unique_targets: list[Path] = []
    for t in targets:
        key = str(t.resolve())
        if key not in seen:
            unique_targets.append(t)
            seen.add(key)

    # Process each target with confirmation
    for t in unique_targets:
        _confirm_delete_contents(t, assume_yes=args.yes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
