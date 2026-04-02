"""
Configuration settings for Shipping Correspondence Processing Script
"""

import os

# =============================================================================
# PATH CONFIGURATION
# =============================================================================

# Staging area where exported emails are placed
STAGING_PATH = r"C:\Users\Jason\Obsidian\Logic\Inbox"

# CSV file containing active shipments
CSV_PATH = r"MASTER-SHIPPING-FILE-LIST.csv"

# Base output folder for organized files and master files
OUTPUT_PATH = r"C:\Users\Jason\Obsidian\SHIPPING"

# Quarantine folder for unmatched files
QUARANTINE_PATH = r"C:\Users\Jason\Obsidian\SHIPPING\Quarantine"

# Processing log file
LOG_PATH = r"processing_log.txt"

# Processing state JSON file
STATE_PATH = r"processing_state.json"

# Master file template
TEMPLATE_PATH = r"templates\master_template.md"

# =============================================================================
# PATTERN CONFIGURATION
# =============================================================================

# Regex patterns for reference extraction
BARTRAC_PATTERN = r'BA\d{4}'           # Matches BA followed by 4 digits (e.g., BA3088)
FML_PATTERN = r'\d{4}[A-Z]{3}\d{4}'   # Matches 4 digits, 3 letters, 4 digits (e.g., 2601DSI2753)

# =============================================================================
# PROCESSING CONFIGURATION
# =============================================================================

# File extensions to process
SUPPORTED_EXTENSIONS = ['.md']

# Date format for logging and timestamps
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def ensure_directories():
    """Create necessary directories if they don't exist"""
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    os.makedirs(QUARANTINE_PATH, exist_ok=True)
    os.makedirs(os.path.dirname(TEMPLATE_PATH), exist_ok=True)

def get_absolute_path(relative_path):
    """Convert relative path to absolute path based on script location"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, relative_path)