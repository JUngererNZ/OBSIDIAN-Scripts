# Shipping Correspondence Markdown Repository

## Purpose

This repository stores shipping correspondence updates in Markdown format. Updates are collected from daily, weekly, and fortnightly shipping communications.

Each file contains:
- Date of the update
- FML shipping file reference
- BARTRAC customer order reference

This is totally a vibe coded a filing system so that I could keep ahead if what shipments are on the go.
Not out of boredom, but out of showing prospectives that I too can vibe code with a AI platform and have conversations on getting to a solution for a particular in-house process/task. ;)

## Data Sources

### Active Shipments
- **Source:** `MASTER-SHIPPING-FILE-LIST.csv`
- **Use:** Source of truth for active ongoing shipments

### Planned Shipments
- **Source:** `MASTER-SHIPPING-FILE-CARGO-TO-ARRIVE-AT-DBN-PORT.csv`
- **Use:** Source of truth for planning/planned shipments

## Folder Structure

### Staging Area
Exported emails are placed into:
```
C:\Users\Jason\Obsidian\Logic\Inbox\
```

### Organized Structure
Files are organized by shipping reference:

```
2510DSI2723/                    (Parent folder - shipping reference)
├── 2510DSI2723-MASTERFILE.md   (Master file with all updates)
```

Or alternative format:
```
2510DSI2723-BAxxxx-MASTERFILE.md
```

## Workflow

1. **Export:** Email updates are exported from Outlook to the staging area
2. **Process:** Script reads exported emails and matches against active shipments CSV
3. **Organize:** Creates folder structure based on shipping reference
4. **Consolidate:** Updates master file with latest correspondence
5. **Archive:** Moves processed files into the parent folder

## Task Priority System

Tasks are tracked using a traffic light priority system:

| Priority | Timeframe | Description |
|----------|-----------|-------------|
| 🔴 High | Current Day | Immediate action required |
| 🟡 Medium | 3 Days | Follow-up needed soon |
| 🟢 Low | 7 Days | Monitor and check |
| ⚪ Future | 14 Days | Upcoming tasks |

## File Types

### Correspondence Files
- Daily shipping updates
- Weekly shipping summaries
- Fortnightly shipping reports

### Reference Files
- In-progress shipping files
- Pending shipping files (starting within hours/days)

## Getting Started

1. Ensure CSV source files are up to date
2. Export email correspondence to staging area
3. Run processing script to organize files

## Script Usage

### Process New Emails
```bash
python process_shipping_emails.py process
```
Scans staging folder, matches emails to shipments, organizes files, and creates/updates master files.

### Scan for Manual Updates
```bash
python process_shipping_emails.py scan
```
Detects manually updated master files without making changes.

### Show Processing Status
```bash
python process_shipping_emails.py status
```
Displays processing status for all shipments.

### Configuration
Edit `config.py` to update:
- `STAGING_PATH` - Location of exported email files
- `CSV_PATH` - Path to shipment reference CSV
- `QUARANTINE_PATH` - Location for unmatched files

## Project Structure

```
OBSIDIAN-Scripts/
├── README.md                          (This file)
├── config.py                          (Script configuration)
├── process_shipping_emails.py         (Main processing script)
├── templates/
│   └── master_template.md             (Master file template)
├── MASTER-SHIPPING-FILE-LIST.csv      (Active shipments)
└── MASTER-SHIPPING-FILE-CARGO-TO-ARRIVE-AT-DBN-PORT.csv (Planned shipments)
```

Give this a read:
https://github.com/JUngererNZ/OBSIDIAN-Scripts/edit/master/README3.md
