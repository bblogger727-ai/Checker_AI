"""
OCR Text Cleaner Service

Post-processing cleanup for OCR output to:
1. Remove any remaining strikethrough/cancelled text patterns
2. Validate table number consistency
3. Clean up common OCR artifacts
"""

import re


def clean_ocr_text(text: str) -> str:
    """
    Clean OCR output text by removing potential strikethrough artifacts
    and normalizing content.
    
    Args:
        text: Raw OCR output text
    
    Returns:
        Cleaned text with strikethrough artifacts removed
    """
    if not text:
        return ""
    
    # Pattern 1: Text surrounded by tildes (common markdown strikethrough)
    # e.g., "~~cancelled text~~"
    text = re.sub(r'~~[^~]+~~', '', text)
    
    # Pattern 2: Text surrounded by double dashes
    # e.g., "--cancelled--"
    text = re.sub(r'--[^-]+--', '', text)
    
    # Pattern 3: Text in parentheses marked as cancelled/crossed
    # e.g., "(cancelled: 500)" or "(crossed out: text)"
    text = re.sub(r'\((?:cancelled|crossed out|struck|deleted)[:\s]*[^)]*\)', '', text, flags=re.IGNORECASE)
    
    # Pattern 4: Words followed by strikethrough markers
    # e.g., "word [crossed]" or "500 [cancelled]"
    text = re.sub(r'\s*\[(?:crossed|cancelled|struck|deleted)\]', '', text, flags=re.IGNORECASE)
    
    # Pattern 5: Explicit strikethrough HTML tags (if any)
    text = re.sub(r'<s>.*?</s>', '', text, flags=re.DOTALL)
    text = re.sub(r'<strike>.*?</strike>', '', text, flags=re.DOTALL)
    text = re.sub(r'<del>.*?</del>', '', text, flags=re.DOTALL)
    
    # Clean up multiple spaces/newlines
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Remove empty table cells that might result from cleaning
    text = re.sub(r'\|\s*\|', '|', text)
    
    return text.strip()


def validate_table_numbers(text: str) -> dict:
    """
    Analyze tables in text for potential number inconsistencies.
    
    Args:
        text: OCR text containing tables
    
    Returns:
        Dictionary with validation results and warnings
    """
    warnings = []
    
    # Find markdown tables
    table_pattern = r'\|[^\n]+\|'
    table_lines = re.findall(table_pattern, text)
    
    if table_lines:
        for i, line in enumerate(table_lines):
            # Skip header separator lines
            if re.match(r'\|[-:\s|]+\|', line):
                continue
            
            # Extract numbers from the line
            numbers = re.findall(r'[\d,]+\.?\d*', line)
            
            # Check for suspicious patterns (e.g., very large numbers that might be errors)
            for num in numbers:
                clean_num = num.replace(',', '')
                try:
                    value = float(clean_num)
                    # Flag unusually large numbers that might be OCR errors
                    if value > 10000000:
                        warnings.append(f"Line {i+1}: Potentially erroneous large number: {num}")
                except ValueError:
                    pass
    
    return {
        "valid": len(warnings) == 0,
        "warnings": warnings,
        "table_lines_found": len(table_lines)
    }


def clean_and_validate(text: str) -> dict:
    """
    Clean OCR text and validate for issues.
    
    Args:
        text: Raw OCR text
    
    Returns:
        Dictionary with cleaned text and validation results
    """
    cleaned = clean_ocr_text(text)
    validation = validate_table_numbers(cleaned)
    
    return {
        "cleaned_text": cleaned,
        "validation": validation,
        "original_length": len(text),
        "cleaned_length": len(cleaned),
        "chars_removed": len(text) - len(cleaned)
    }
