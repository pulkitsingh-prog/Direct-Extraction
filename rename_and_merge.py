#!/usr/bin/env python3
"""
Rename final_extracted.json files back to original PDF numbers using the rename log CSV.

This script:
1. Reads the PDF rename log CSV
2. Creates a mapping from renamed numbers to original numbers
3. Renames files from XXX_final_extracted.json to ORIGINAL_final_extracted.json
"""

import csv
import os
import re
from pathlib import Path


def extract_number_from_filename(filename):
    """Extract the 3-digit number from renamed PDF filename (e.g., '001_iqudr.pdf' -> '001')"""
    match = re.match(r'(\d{3})_\w+\.pdf', filename)
    if match:
        return match.group(1)
    return None


def extract_original_number(original_name):
    """Extract the original 3-digit number from original PDF name (e.g., '001 Qlik...' -> '001')"""
    match = re.match(r'(\d{3})\s', original_name)
    if match:
        return match.group(1)
    return None


def create_rename_mapping(csv_path):
    """
    Create a mapping from renamed numbers to original numbers.
    
    Returns:
        dict: {renamed_number: original_number}
              e.g., {'001': '001', '002': '002', '003': '003', ...}
    """
    mapping = {}
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            original_name = row['Original Name']
            new_name = row['New Name']
            
            original_num = extract_original_number(original_name)
            renamed_num = extract_number_from_filename(new_name)
            
            if original_num and renamed_num:
                mapping[renamed_num] = original_num
    
    return mapping


def rename_files(directory, mapping, dry_run=True):
    directory = Path(directory)

    json_files = sorted(directory.glob('*_final_extracted.json'))

    if not json_files:
        print(f"No *_final_extracted.json files found in {directory}")
        return

    print(f"Found {len(json_files)} files to process\n")

    temp_files = []
    skipped_count = 0

    # -------------------------
    # Phase 1: Rename to temp
    # -------------------------
    for json_file in json_files:
        match = re.match(r'(\d{3})_final_extracted\.json', json_file.name)
        if not match:
            print(f"⚠️  Skipping {json_file.name} - invalid filename")
            skipped_count += 1
            continue

        current_num = match.group(1)

        if current_num not in mapping:
            print(f"⚠️  Skipping {json_file.name} - no mapping found")
            skipped_count += 1
            continue

        temp_name = f"{current_num}__tmp__.json"
        temp_path = directory / temp_name

        if dry_run:
            print(f"Phase 1: {json_file.name} -> {temp_name}")
        else:
            json_file.rename(temp_path)

        temp_files.append(temp_path)

    # -------------------------
    # Phase 2: Rename to final
    # -------------------------
    renamed_count = 0

    for temp_path in temp_files:
        match = re.match(r'(\d{3})__tmp__\.json', temp_path.name)
        current_num = match.group(1)

        original_num = mapping[current_num]
        final_name = f"{original_num}_final_extracted.json"
        final_path = directory / final_name

        if dry_run:
            print(f"Phase 2: {temp_path.name} -> {final_name}")
        else:
            temp_path.rename(final_path)
            renamed_count += 1

    print(f"\n{'DRY RUN - ' if dry_run else ''}Summary:")
    print(f"  Files renamed: {renamed_count}")
    print(f"  Files skipped: {skipped_count}")
    print(f"  Total processed: {len(json_files)}")


def main():
    # 👉 Directly provide paths here
    csv_path = r"C:\Users\Administrator\OneDrive\Desktop\new_direct_extraction\pdf_rename_log.csv"
    directory = r"outputs"

    execute = False        # set True to actually rename
    show_mapping = False   # set True to only display mapping

    print(f"Reading rename log from: {csv_path}\n")
    mapping = create_rename_mapping(csv_path)

    if show_mapping:
        print("Rename Mapping (renamed -> original):")
        print("-" * 40)
        for renamed, original in sorted(mapping.items()):
            print(f"  {renamed} -> {original}")
        print(f"\nTotal mappings: {len(mapping)}")
        return

    rename_files(directory, mapping, dry_run= execute)


if __name__ == "__main__":
    main()