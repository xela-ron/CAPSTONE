"""
RFID Exporter - Export scan logs to Excel or CSV
Run this anytime to export all data from the database.
"""

import sqlite3
import csv
import os
from datetime import datetime

DB_FILE = "rfid_logs.db"


def export_csv(output_file: str = None):
    """Export all RFID scan records to a CSV file."""
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"rfid_export_{timestamp}.csv"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, tag_id, scan_time, port, notes FROM rfid_scans ORDER BY scan_time DESC")
    rows = cursor.fetchall()
    conn.close()

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Tag ID", "Scan Time", "Port", "Notes"])
        writer.writerows(rows)

    print(f"[EXPORT] CSV saved: {output_file} ({len(rows)} records)")
    return output_file


def export_excel(output_file: str = None):
    """Export all RFID scan records to an Excel (.xlsx) file."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("[ERROR] openpyxl not installed. Run: pip install openpyxl")
        return

    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"rfid_export_{timestamp}.xlsx"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, tag_id, scan_time, port, notes FROM rfid_scans ORDER BY scan_time DESC")
    rows = cursor.fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RFID Scan Logs"

    # Header styling
    headers = ["ID", "Tag ID", "Scan Time", "Port", "Notes"]
    header_fill = PatternFill("solid", fgColor="1F3864")
    header_font = Font(color="FFFFFF", bold=True)

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    row_fill_even = PatternFill("solid", fgColor="DCE6F1")
    for row_num, row_data in enumerate(rows, 2):
        for col_num, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_num, value=value)
            if row_num % 2 == 0:
                cell.fill = row_fill_even

    # Auto column widths
    col_widths = [6, 25, 22, 12, 30]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # Freeze header row
    ws.freeze_panes = "A2"

    wb.save(output_file)
    print(f"[EXPORT] Excel saved: {output_file} ({len(rows)} records)")
    return output_file


def export_summary():
    """Print a summary of scan stats."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM rfid_scans")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT tag_id) FROM rfid_scans")
    unique_tags = cursor.fetchone()[0]

    cursor.execute("SELECT tag_id, COUNT(*) as cnt FROM rfid_scans GROUP BY tag_id ORDER BY cnt DESC LIMIT 5")
    top_tags = cursor.fetchall()

    cursor.execute("SELECT scan_time FROM rfid_scans ORDER BY scan_time DESC LIMIT 1")
    last_scan = cursor.fetchone()
    conn.close()

    print("\n===== RFID Scan Summary =====")
    print(f"Total scans    : {total}")
    print(f"Unique tags    : {unique_tags}")
    print(f"Last scan      : {last_scan[0] if last_scan else 'None'}")
    print("\nTop 5 Most Scanned Tags:")
    for tag, count in top_tags:
        print(f"  {tag:30s} — {count} scans")
    print("=============================\n")


if __name__ == "__main__":
    export_summary()
    print("Choose export format:")
    print("  1. CSV")
    print("  2. Excel (.xlsx)")
    print("  3. Both")
    choice = input("Enter choice (1/2/3): ").strip()

    if choice == "1":
        export_csv()
    elif choice == "2":
        export_excel()
    elif choice == "3":
        export_csv()
        export_excel()
    else:
        print("Invalid choice.")
