import json
from pathlib import Path
import sys


def is_metadata_empty(entry: dict) -> bool:
    """
    Returns True if ALL metadata fields are null/empty.
    """
    metadata_keys = [
        "page",
        "block_id",
        "bbox",
        "page_width",
        "page_height",
    ]

    for key in metadata_keys:
        value = entry.get(key)

        if value not in (None, "", {}, 0):
            return False

    return True


def check_file(file_path: Path):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    null_count = 0
    total_values = 0

    metadata_mapping = data.get("metadata_mapping", {})

    if not isinstance(metadata_mapping, dict):
        return 0, 0

    for key, items in metadata_mapping.items():

        if not isinstance(items, list):
            continue

        for entry in items:
            if not isinstance(entry, dict):
                continue

            total_values += 1
            value = entry.get("value")

            if (
                is_metadata_empty(entry)
                and value not in ("NOT SPECIFIED", None, "")
            ):
                print(f"❌ {file_path.name} → {key}: {value}")
                null_count += 1

    return total_values, null_count


def validate_folder(folder_path: Path):
    if not folder_path.exists():
        print(f"❌ Folder not found: {folder_path}")
        return

    total_files = 0
    grand_total_values = 0
    grand_null_count = 0

    print(f"\n🔎 Scanning folder: {folder_path}\n")

    for file in folder_path.glob("*.json"):
        total_files += 1
        total_values, null_count = check_file(file)

        grand_total_values += total_values
        grand_null_count += null_count

    print("\n===================================")
    print(f"Files scanned: {total_files}")
    print(f"Total metadata entries checked: {grand_total_values}")
    print(f"Entries with NULL metadata: {grand_null_count}")

    if grand_total_values > 0:
        success_rate = (
            (grand_total_values - grand_null_count)
            / grand_total_values
        ) * 100
        print(f"Metadata Mapping Success Rate: {success_rate:.2f}%")

    print("===================================\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python empty.py <path_to_folder>")
        sys.exit(1)

    folder_path = Path(sys.argv[1])
    validate_folder(folder_path)
