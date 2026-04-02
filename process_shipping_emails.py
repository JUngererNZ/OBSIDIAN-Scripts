    #!/usr/bin/env python3
"""
Shipping Correspondence Processing Script
Processes exported email markdown files, organizes them by shipment reference,
and generates/updates master shipping files.
"""

import os
import re
import csv
import json
import hashlib
import shutil
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import config

STATUS_LABELS = {
    'completed': '🟢 Completed',
    'in_progress': '🟡 In Progress',
    'action_required': '🔴 Action Required',
    'na': '⚪ N/A',
}

STATUS_PATTERNS = {
    'action_required': [
        r'\baction required\b',
        r'\burgent\b',
        r'\bdelay(?:ed)?\b',
        r'\bissue\b',
        r'\bproblem\b',
        r'\bblocked\b',
        r'\bhold\b',
        r'\bneeds.*action\b',
        r'\battention\b',
        r'\bstop\b',
        r'\bunresolved\b',
    ],
    'completed': [
        r'\bcompleted\b',
        r'\bconfirmed\b',
        r'\breleased\b',
        r'\bdelivered\b',
        r'\bclosed\b',
        r'\bresolved\b',
        r'\bcleared\b',
        r'\bfinalized\b',
        r'\bdone\b',
        r'\bready\b',
        r'\bimproved\b',
        r'\bapproved\b',
    ],
    'in_progress': [
        r'\bin progress\b',
        r'\bpending\b',
        r'\bexpected\b',
        r'\bscheduled\b',
        r'\bon track\b',
        r'\bwaiting\b',
        r'\bawaiting\b',
        r'\bunderway\b',
        r'\bongoing\b',
        r'\bprogress\b',
    ],
    'na': [
        r'\bn/?a\b',
        r'\bnot applicable\b',
        r'\bnot relevant\b',
    ],
}

STRONG_COMPLETION_PATTERNS = [
    r'\bissue(?:s)? resolved\b',
    r'\bcleared\b',
    r'\breleased\b',
    r'\bdelivered\b',
    r'\bcompleted\b',
    r'\bfinalized\b',
    r'\bapproved\b',
    r'\bconfirmed\b',
    r'\bready for release\b',
    r'\bfully.*confirmed\b',
    r'\bno further action\b',
]


def configure_utf8_console():
    """Configure console streams for UTF-8 output on Windows."""
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# =============================================================================
# LOGGING
# =============================================================================

class Logger:
    """Simple file and console logger"""
    
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.messages = []
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message to file and console"""
        timestamp = datetime.now().strftime(config.DATE_FORMAT)
        log_message = f"[{timestamp}] [{level}] {message}"
        try:
            encoding = sys.stdout.encoding or 'utf-8'
            safe_message = log_message.encode(encoding, errors='replace').decode(encoding, errors='replace')
        except Exception:
            safe_message = log_message.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        print(safe_message)
        self.messages.append(log_message)
    
    def info(self, message: str):
        self.log(message, "INFO")
    
    def warning(self, message: str):
        self.log(message, "WARNING")
    
    def error(self, message: str):
        self.log(message, "ERROR")
    
    def success(self, message: str):
        self.log(message, "SUCCESS")
    
    def save(self):
        """Save log messages to file"""
        with open(self.log_path, 'a', encoding='utf-8') as f:
            for msg in self.messages:
                f.write(msg + '\n')
        self.messages.clear()


# =============================================================================
# STATE MANAGEMENT
# =============================================================================

class ProcessingState:
    """Manages processing state for change detection"""
    
    def __init__(self, state_path: str):
        self.state_path = state_path
        self.state = self._load()
    
    def _load(self) -> Dict:
        """Load state from JSON file"""
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def save(self):
        """Save state to JSON file"""
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2)
    
    def get_shipment_state(self, shipment_key: str) -> Optional[Dict]:
        """Get state for a specific shipment"""
        return self.state.get(shipment_key)
    
    def update_shipment_state(self, shipment_key: str, data: Dict):
        """Update state for a specific shipment"""
        if shipment_key not in self.state:
            self.state[shipment_key] = {}

        if 'file_status' in data:
            self.add_status_history(shipment_key, data['file_status'])

        self.state[shipment_key].update(data)
        self.state[shipment_key]['last_processed'] = datetime.now().strftime(config.TIMESTAMP_FORMAT)

    def add_status_history(self, shipment_key: str, status: str):
        """Record status transitions for a shipment"""
        if shipment_key not in self.state:
            self.state[shipment_key] = {}
        if 'status_history' not in self.state[shipment_key]:
            self.state[shipment_key]['status_history'] = []

        history = self.state[shipment_key]['status_history']
        if not history or history[-1].get('status') != status:
            history.append({
                'status': status,
                'timestamp': datetime.now().strftime(config.TIMESTAMP_FORMAT)
            })

    def add_processed_email(self, shipment_key: str, email_filename: str):
        """Add an email to the processed list for a shipment"""
        if shipment_key not in self.state:
            self.state[shipment_key] = {'emails_processed': []}
        if 'emails_processed' not in self.state[shipment_key]:
            self.state[shipment_key]['emails_processed'] = []
        if email_filename not in self.state[shipment_key]['emails_processed']:
            self.state[shipment_key]['emails_processed'].append(email_filename)
    
    def is_email_processed(self, shipment_key: str, email_filename: str) -> bool:
        """Check if an email has already been processed for a shipment"""
        shipment_state = self.get_shipment_state(shipment_key)
        if not shipment_state:
            return False
        return email_filename in shipment_state.get('emails_processed', [])


# =============================================================================
# CSV READER
# =============================================================================

class ShipmentDatabase:
    """Manages shipment data from CSV"""
    
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.shipments = self._load_csv()
    
    def _load_csv(self) -> List[Dict]:
        """Load shipments from CSV file"""
        shipments = []
        try:
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:  # utf-8-sig handles BOM
                # Use semicolon as delimiter based on CSV format
                reader = csv.DictReader(f, delimiter=';')
                for row in reader:
                    # Normalize header keys (strip whitespace and BOM)
                    normalized_row = {k.strip(): v for k, v in row.items()}
                    shipments.append({
                        'bartrac_ref': normalized_row.get('BARTRAC-REF', '').strip(),
                        'fml_ref': normalized_row.get('FML-REF', '').strip(),
                        'folder_location': normalized_row.get('SHIPPING-FOLDER-LOCATION', '').strip(),
                        'file_location': normalized_row.get('SHIPPING-FILE-LOCATION', '').strip()
                    })
        except Exception as e:
            print(f"Error loading CSV: {e}")
        return shipments
    
    def find_shipment(self, bartrac_ref: Optional[str] = None, fml_ref: Optional[str] = None) -> Optional[Dict]:
        """Find a shipment by BARTRAC and/or FML reference"""
        if bartrac_ref and fml_ref:
            for shipment in self.shipments:
                if shipment['bartrac_ref'] == bartrac_ref and shipment['fml_ref'] == fml_ref:
                    return shipment
        if bartrac_ref:
            for shipment in self.shipments:
                if shipment['bartrac_ref'] == bartrac_ref:
                    return shipment
        if fml_ref:
            for shipment in self.shipments:
                if shipment['fml_ref'] == fml_ref:
                    return shipment
        return None

    def find_shipments_by_fml(self, fml_ref: str) -> List[Dict]:
        """Find all shipments that share the same FML reference"""
        return [shipment for shipment in self.shipments if shipment['fml_ref'] == fml_ref]
    
    def get_all_references(self) -> List[str]:
        """Get all unique references from the database"""
        refs = set()
        for shipment in self.shipments:
            if shipment['bartrac_ref']:
                refs.add(shipment['bartrac_ref'])
            if shipment['fml_ref']:
                refs.add(shipment['fml_ref'])
        return list(refs)

    def create_output_folders(self):
        """Create per-shipment output folders based on BARTRAC references"""
        for shipment in self.shipments:
            bartrac_ref = shipment.get('bartrac_ref')
            if bartrac_ref:
                os.makedirs(os.path.join(config.OUTPUT_PATH, bartrac_ref), exist_ok=True)


# =============================================================================
# REFERENCE EXTRACTOR
# =============================================================================

class ReferenceExtractor:
    """Extracts shipping references from file content"""
    
    @staticmethod
    def extract_references(content: str) -> Tuple[List[str], List[str]]:
        """
        Extract BARTRAC and FML references from content
        Returns: (list of BARTRAC refs, list of FML refs)
        """
        bartrac_refs = list(set(re.findall(config.BARTRAC_PATTERN, content)))
        fml_refs = list(set(re.findall(config.FML_PATTERN, content)))
        return bartrac_refs, fml_refs
    
    @staticmethod
    def extract_email_metadata(content: str) -> Dict:
        """Extract metadata from email markdown content"""
        metadata = {
            'date': '',
            'from': '',
            'subject': '',
            'references': []
        }
        
        # Try to extract date (common formats)
        date_patterns = [
            r'Date:\s*(.+)',
            r'Sent:\s*(.+)',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                metadata['date'] = match.group(1).strip()
                break
        
        # Try to extract sender
        from_patterns = [
            r'From:\s*(.+)',
            r'Sender:\s*(.+)',
        ]
        for pattern in from_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                metadata['from'] = match.group(1).strip()
                break
        
        # Try to extract subject
        subject_patterns = [
            r'Subject:\s*(.+)',
            r'Re:\s*(.+)',
        ]
        for pattern in subject_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                metadata['subject'] = match.group(1).strip()
                break
        
        return metadata
    
    @staticmethod
    def extract_field_value(content: str, field_name: str) -> str:
        """Extract a specific field value from content"""
        patterns = [
            rf'{field_name}:\s*(.+)',
            rf'{field_name}\s*:\s*(.+)',
            rf'\*\*{field_name}\*\*:\s*(.+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ''


# =============================================================================
# FILE PROCESSOR
# =============================================================================

class FileProcessor:
    """Processes and organizes shipping correspondence files"""
    
    def __init__(self, logger: Logger, state: ProcessingState, db: ShipmentDatabase):
        self.logger = logger
        self.state = state
        self.db = db
        self.extractor = ReferenceExtractor()
    
    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate MD5 hash of a file"""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def detect_manual_updates(self, file_path: str, shipment_key: str) -> bool:
        """Detect if a file has been manually updated since last processing"""
        if not os.path.exists(file_path):
            return False
        
        current_hash = self.calculate_file_hash(file_path)
        shipment_state = self.state.get_shipment_state(shipment_key)
        
        if not shipment_state:
            return False
        
        stored_hash = shipment_state.get('file_hash', '')
        if stored_hash and current_hash != stored_hash:
            self.logger.info(f"Manual update detected: {os.path.basename(file_path)}")
            return True
        
        return False

    def _matches_status(self, text: str, status_type: str) -> bool:
        """Check whether text matches a given status category"""
        patterns = STATUS_PATTERNS.get(status_type, [])
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def determine_file_status(self, content: str, metadata: Dict, previous_status: Optional[str] = None) -> str:
        """Determine the master file status from email content and metadata"""
        text = ' '.join([
            content,
            metadata.get('subject', ''),
            metadata.get('from', ''),
        ]).lower()
        if self._matches_status(text, 'action_required'):
            return STATUS_LABELS['action_required']
        if self._matches_status(text, 'completed'):
            # If we are already red, only move off red with a strong completion signal
            if previous_status == STATUS_LABELS['action_required']:
                if self._matches_strong_completion(text):
                    return STATUS_LABELS['completed']
                return previous_status
            return STATUS_LABELS['completed']
        if self._matches_status(text, 'in_progress'):
            if previous_status == STATUS_LABELS['action_required']:
                return previous_status
            return STATUS_LABELS['in_progress']
        if self._matches_status(text, 'na'):
            if previous_status == STATUS_LABELS['action_required']:
                return previous_status
            return STATUS_LABELS['na']
        return previous_status or STATUS_LABELS['in_progress']

    def _matches_strong_completion(self, text: str) -> bool:
        """Check whether text contains a strong completion confirmation phrase"""
        for pattern in STRONG_COMPLETION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _extract_status_from_master(self, content: str) -> str:
        """Extract the existing status line from an existing master file"""
        match = re.search(r'\*\*File Status:\*\*\s*(.+)', content)
        if match:
            return match.group(1).strip()
        return STATUS_LABELS['in_progress']

    def _extract_references(self, content: str, file_path: str) -> Tuple[List[str], List[str]]:
        """Extract references from content with filename fallback"""
        bartrac_refs, fml_refs = self.extractor.extract_references(content)
        filename = os.path.basename(file_path)
        if not bartrac_refs or not fml_refs:
            filename_bartrac_refs, filename_fml_refs = self.extractor.extract_references(filename)
            for ref in filename_bartrac_refs:
                if ref not in bartrac_refs:
                    bartrac_refs.append(ref)
            for ref in filename_fml_refs:
                if ref not in fml_refs:
                    fml_refs.append(ref)
            if filename_bartrac_refs or filename_fml_refs:
                self.logger.info(f"Using filename fallback references for {filename}: {filename_bartrac_refs + filename_fml_refs}")
        return bartrac_refs, fml_refs
    
    def process_file(self, file_path: str) -> Dict:
        """
        Process a single email file
        Returns: processing result dict
        """
        result = {
            'file': os.path.basename(file_path),
            'status': 'pending',
            'shipment_key': None,
            'matched_refs': [],
            'error': None
        }
        
        try:
            # Read file content with a fallback for non-UTF-8 markdown exports
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                self.logger.warning(f"UTF-8 decode failed for {os.path.basename(file_path)}; falling back to cp1252")
                with open(file_path, 'r', encoding='cp1252', errors='replace') as f:
                    content = f.read()

            # Extract references from content, with filename fallback
            bartrac_refs, fml_refs = self._extract_references(content, file_path)
            result['matched_refs'] = bartrac_refs + fml_refs
            
            if not bartrac_refs and not fml_refs:
                result['status'] = 'no_match'
                return result
            
            # Find matching shipment
            shipment = None
            matched_ref = None

            # If we have both BARTRAC and FML refs, prefer an exact CSV match first
            if bartrac_refs and fml_refs:
                for bartrac_ref in bartrac_refs:
                    for fml_ref in fml_refs:
                        shipment = self.db.find_shipment(bartrac_ref=bartrac_ref, fml_ref=fml_ref)
                        if shipment:
                            matched_ref = f"{bartrac_ref}|{fml_ref}"
                            break
                    if shipment:
                        break

            # Fallback to BARTRAC-only match
            if not shipment:
                for ref in bartrac_refs:
                    shipment = self.db.find_shipment(bartrac_ref=ref)
                    if shipment:
                        matched_ref = ref
                        break

            # Fallback to FML-only match, with ambiguity warning if duplicates exist
            if not shipment:
                for ref in fml_refs:
                    candidates = self.db.find_shipments_by_fml(ref)
                    if len(candidates) > 1:
                        self.logger.warning(f"Ambiguous FML reference {ref}: matched {len(candidates)} shipments, using first match")
                    if candidates:
                        shipment = candidates[0]
                        matched_ref = ref
                        break

            if not shipment:
                if bartrac_refs or fml_refs:
                    bartrac_ref = bartrac_refs[0] if bartrac_refs else fml_refs[0]
                    fml_ref = fml_refs[0] if fml_refs else bartrac_refs[0]
                    shipment = {
                        'bartrac_ref': bartrac_ref,
                        'fml_ref': fml_ref,
                        'folder_location': os.path.join(config.OUTPUT_PATH, bartrac_ref),
                        'file_location': f"{fml_ref}-{bartrac_ref}.md"
                    }
                    self.logger.info(f"Fallback shipment created for {bartrac_ref} / {fml_ref}")
                else:
                    result['status'] = 'no_match'
                    return result
            
            # Create shipment key for state tracking
            shipment_key = f"{shipment['bartrac_ref']}_{shipment['fml_ref']}"
            result['shipment_key'] = shipment_key
            
            # Check if already processed
            if self.state.is_email_processed(shipment_key, result['file']):
                result['status'] = 'already_processed'
                return result
            
            # Organize file
            self._organize_file(file_path, shipment, result['file'])
            
            # Update or create master file
            self._update_master_file(shipment, content, result['file'], shipment_key)
            
            # Update state
            self.state.add_processed_email(shipment_key, result['file'])
            self.state.update_shipment_state(shipment_key, {
                'bartrac_ref': shipment['bartrac_ref'],
                'fml_ref': shipment['fml_ref'],
                'folder_location': shipment['folder_location']
            })
            
            result['status'] = 'success'
            
        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)
            self.logger.error(f"Error processing {file_path}: {e}")
        
        return result
    
    def _organize_file(self, source_path: str, shipment: Dict, filename: str):
        """Move file to appropriate shipment folder"""
        bartrac_ref = shipment['bartrac_ref']
        
        # Always use OUTPUT_PATH with BARTRAC_REF folder structure
        # This handles bad CSV data gracefully
        target_folder = os.path.join(config.OUTPUT_PATH, bartrac_ref)
        
        # Create folder if it doesn't exist
        os.makedirs(target_folder, exist_ok=True)
        
        # Move file
        target_path = os.path.join(target_folder, filename)
        
        # Handle duplicate filenames
        if os.path.exists(target_path):
            base, ext = os.path.splitext(filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{base}_{timestamp}{ext}"
            target_path = os.path.join(target_folder, filename)
        
        shutil.move(source_path, target_path)
        self.logger.success(f"Organized: {filename} → {target_folder}")
    
    def _update_master_file(self, shipment: Dict, email_content: str, email_filename: str, shipment_key: str):
        """Create or update master file for shipment"""
        bartrac_ref = shipment['bartrac_ref']
        
        # Always use OUTPUT_PATH with BARTRAC_REF folder structure
        # This handles bad CSV data gracefully
        target_folder = os.path.join(config.OUTPUT_PATH, bartrac_ref)
        
        master_filename = shipment['file_location']
        
        if not master_filename:
            self.logger.warning(f"Missing file location for shipment {bartrac_ref}")
            return
        
        master_path = os.path.join(target_folder, master_filename)
        
        # Extract metadata from email
        metadata = self.extractor.extract_email_metadata(email_content)
        
        if os.path.exists(master_path):
            # Check for manual updates
            if self.detect_manual_updates(master_path, shipment_key):
                self.logger.info(f"Preserving manual edits in {master_filename}")
                # Update hash and continue
                self.state.update_shipment_state(shipment_key, {
                    'file_hash': self.calculate_file_hash(master_path)
                })
            
            # Append to existing master file
            self._append_to_master(master_path, metadata, email_filename, shipment_key, email_content)
        else:
            # Create new master file from template
            self._create_master_file(master_path, shipment, metadata, email_filename, shipment_key, email_content)

    def _create_master_file(self, master_path: str, shipment: Dict, metadata: Dict, email_filename: str, shipment_key: str, email_content: str):
        """Create a new master file from template"""
        template_path = config.TEMPLATE_PATH
        
        if not os.path.exists(template_path):
            self.logger.error(f"Template not found: {template_path}")
            return
        
        # Read template
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Determine file status
        file_status = self.determine_file_status(email_content, metadata, None)

        # Prepare replacements
        replacements = {
            '{{file_ref}}': shipment['fml_ref'],
            '{{client_ref}}': shipment['bartrac_ref'],
            '{{consignee}}': '',
            '{{description}}': '',
            '{{pin_no}}': '',
            '{{serial_no}}': '',
            '{{engine_no}}': '',
            '{{vessel_voy}}': '',
            '{{bill_no}}': '',
            '{{eta}}': '',
            '{{container_no}}': '',
            '{{transporter}}': '',
            '{{fix_number}}': '',
            '{{client_po}}': '',
            '{{quotation_nr}}': '',
            '{{generated_date}}': datetime.now().strftime(config.DATE_FORMAT),
            '{{file_status}}': file_status,
        }
        
        # Replace placeholders
        content = template_content
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)

        # Add first correspondence entry
        correspondence_row = f"| {metadata.get('date', 'N/A')} | {metadata.get('from', 'N/A')} | {metadata.get('subject', 'N/A')} | {email_filename} |"
        content = content.replace('{{correspondence_rows}}', correspondence_row)
        
        # Write master file
        os.makedirs(os.path.dirname(master_path), exist_ok=True)
        with open(master_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Update state with file hash and status
        self.state.update_shipment_state(shipment_key, {
            'file_hash': self.calculate_file_hash(master_path),
            'file_status': file_status
        })
        
        self.logger.success(f"Created master file: {os.path.basename(master_path)}")
    
    def _append_to_master(self, master_path: str, metadata: Dict, email_filename: str, shipment_key: str, email_content: str):
        """Append new correspondence to existing master file"""
        with open(master_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        current_status = self._extract_status_from_master(content)
        new_status = self.determine_file_status(email_content, metadata, current_status)
        
        # Find correspondence log section and append
        correspondence_row = f"| {metadata.get('date', 'N/A')} | {metadata.get('from', 'N/A')} | {metadata.get('subject', 'N/A')} | {email_filename} |"
        
        # Insert before the last empty row or at end of table
        if '{{correspondence_rows}}' in content:
            content = content.replace('{{correspondence_rows}}', correspondence_row)
        else:
            # Find the correspondence table and append
            table_pattern = r'(\|.*\|.*\|.*\|.*\|\n)(\n---)'
            match = re.search(table_pattern, content)
            if match:
                insert_pos = match.end(1)
                content = content[:insert_pos] + correspondence_row + '\n' + content[insert_pos:]
            else:
                # Append at end
                content += f'\n{correspondence_row}'
        
        # Update generated date
        content = re.sub(
            r'\*Generated on:.*?\*',
            f'*Generated on: {datetime.now().strftime(config.DATE_FORMAT)}*',
            content
        )

        # Update file status line if necessary
        if current_status != new_status:
            content = re.sub(
                r'(\*\*File Status:\*\*\s*).+',
                rf'\1{new_status}',
                content
            )

        with open(master_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Update state with file hash and status
        self.state.update_shipment_state(shipment_key, {
            'file_hash': self.calculate_file_hash(master_path),
            'file_status': new_status
        })
        
        self.logger.info(f"Updated master file: {os.path.basename(master_path)}")


# =============================================================================
# SCANNER
# =============================================================================

class StagingScanner:
    """Scans staging folder for new email files"""
    
    def __init__(self, staging_path: str, supported_extensions: List[str]):
        self.staging_path = staging_path
        self.supported_extensions = supported_extensions
    
    def scan(self) -> List[str]:
        """Scan staging folder and return list of email files"""
        files = []
        
        if not os.path.exists(self.staging_path):
            return files
        
        for filename in os.listdir(self.staging_path):
            filepath = os.path.join(self.staging_path, filename)
            if os.path.isfile(filepath):
                _, ext = os.path.splitext(filename)
                if ext.lower() in self.supported_extensions:
                    files.append(filepath)
        
        return sorted(files)


# =============================================================================
# MAIN
# =============================================================================

def run_processing(args):
    """Main processing function"""
    # Initialize components
    logger = Logger(config.LOG_PATH)
    state = ProcessingState(config.STATE_PATH)
    db = ShipmentDatabase(config.CSV_PATH)
    processor = FileProcessor(logger, state, db)
    scanner = StagingScanner(config.STAGING_PATH, config.SUPPORTED_EXTENSIONS)
    
    logger.info("=" * 60)
    logger.info("Shipping Correspondence Processing Started")
    logger.info("=" * 60)
    
    # Ensure directories exist and create per-shipment folders first
    config.ensure_directories()
    db.create_output_folders()

    # Scan for new files
    email_files = scanner.scan()
    logger.info(f"Found {len(email_files)} email files in staging")
    
    if not email_files:
        logger.info("No files to process")
        logger.save()
        return
    
    # Process each file
    results = {
        'success': 0,
        'no_match': 0,
        'already_processed': 0,
        'error': 0
    }
    
    quarantined = []
    
    for file_path in email_files:
        logger.info(f"Processing: {os.path.basename(file_path)}")
        result = processor.process_file(file_path)
        
        if result['status'] == 'success':
            results['success'] += 1
        elif result['status'] == 'no_match':
            results['no_match'] += 1
            quarantined.append(file_path)
        elif result['status'] == 'already_processed':
            results['already_processed'] += 1
        elif result['status'] == 'error':
            results['error'] += 1
    
    # Quarantine unmatched files
    for file_path in quarantined:
        quarantine_path = os.path.join(config.QUARANTINE_PATH, os.path.basename(file_path))
        shutil.move(file_path, quarantine_path)
        logger.warning(f"Quarantined (no match): {os.path.basename(file_path)}")
    
    # Save state
    state.save()
    
    # Summary
    logger.info("=" * 60)
    logger.info("Processing Complete")
    logger.info(f"  Success: {results['success']}")
    logger.info(f"  No Match (Quarantined): {results['no_match']}")
    logger.info(f"  Already Processed: {results['already_processed']}")
    logger.info(f"  Errors: {results['error']}")
    logger.info("=" * 60)
    
    # Save log
    logger.save()


def run_scan(args):
    """Scan mode: detect manual updates without making changes"""
    logger = Logger(config.LOG_PATH)
    state = ProcessingState(config.STATE_PATH)
    db = ShipmentDatabase(config.CSV_PATH)
    processor = FileProcessor(logger, state, db)
    
    logger.info("=" * 60)
    logger.info("Manual Update Scan Started")
    logger.info("=" * 60)
    
    updates_found = 0
    
    for shipment in db.shipments:
        shipment_key = f"{shipment['bartrac_ref']}_{shipment['fml_ref']}"
        folder = shipment['folder_location']
        master_file = shipment['file_location']
        
        if not folder or not master_file:
            continue
        
        master_path = os.path.join(folder, master_file)
        
        if os.path.exists(master_path):
            if processor.detect_manual_updates(master_path, shipment_key):
                updates_found += 1
                logger.info(f"Manual update: {shipment['bartrac_ref']} - {master_file}")
    
    logger.info("=" * 60)
    logger.info(f"Scan Complete: {updates_found} manual updates detected")
    logger.info("=" * 60)
    
    logger.save()


def run_status(args):
    """Status mode: show processing status for all shipments"""
    logger = Logger(config.LOG_PATH)
    state = ProcessingState(config.STATE_PATH)
    db = ShipmentDatabase(config.CSV_PATH)
    
    logger.info("=" * 60)
    logger.info("Shipment Processing Status")
    logger.info("=" * 60)
    
    for shipment in db.shipments:
        shipment_key = f"{shipment['bartrac_ref']}_{shipment['fml_ref']}"
        shipment_state = state.get_shipment_state(shipment_key)
        
        if shipment_state:
            emails_count = len(shipment_state.get('emails_processed', []))
            last_processed = shipment_state.get('last_processed', 'Never')
            file_status = shipment_state.get('file_status', 'Unknown')
            history = shipment_state.get('status_history', [])
            history_summary = ''
            if history:
                history_summary = ' | History: ' + ' -> '.join([entry['status'] for entry in history[-3:]])
            logger.info(f"{shipment['bartrac_ref']} | {shipment['fml_ref']} | Status: {file_status} | Emails: {emails_count} | Last: {last_processed}{history_summary}")
        else:
            logger.info(f"{shipment['bartrac_ref']} | {shipment['fml_ref']} | Not processed")
    
    logger.info("=" * 60)
    logger.save()


def main():
    """Entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description='Process shipping correspondence emails'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Process command
    process_parser = subparsers.add_parser('process', help='Process new emails')
    process_parser.set_defaults(func=run_processing)
    
    # Scan command
    scan_parser = subparsers.add_parser('scan', help='Scan for manual updates')
    scan_parser.set_defaults(func=run_scan)
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show processing status')
    status_parser.set_defaults(func=run_status)
    
    args = parser.parse_args()

    configure_utf8_console()
    
    if args.command is None:
        # Default to process command
        args.command = 'process'
        args.func = run_processing
    
    args.func(args)


if __name__ == '__main__':
    main()