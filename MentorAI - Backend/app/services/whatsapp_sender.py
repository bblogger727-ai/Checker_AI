"""
WhatsApp Sender Service

Generates WhatsApp links for sending reports.
For full automation, WhatsApp Business API would be needed.
"""

import os
import urllib.parse
from typing import Optional


def generate_whatsapp_link(
    phone: str,
    student_name: str,
    pdf_path: Optional[str] = None
) -> str:
    """
    Generate a wa.me link for sending message via WhatsApp.
    
    The mentor can click this link to open WhatsApp with pre-filled message.
    For PDF attachment, we'd need to host the file somewhere accessible.
    
    Args:
        phone: Phone number with country code (e.g., +919876543210)
        student_name: Student's name
        pdf_path: Path to report PDF (for reference)
    
    Returns:
        wa.me URL that opens WhatsApp chat
    """
    
    # Clean phone number (remove spaces, dashes, etc.)
    clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")
    if not clean_phone.startswith("+"):
        clean_phone = "+91" + clean_phone  # Default to India
    
    # Remove the + for wa.me URL
    phone_for_url = clean_phone.lstrip("+")
    
    # Create message
    message = f"""Hi {student_name}! 📚

Your weekly progress report is ready!

The report includes:
✅ Your exam performance analysis
✅ Areas for improvement we discussed
✅ Personalized recommendations
✅ Action items for this week

Please check your email for the detailed PDF report.

If you haven't received it, let me know and I'll resend it.

Keep up the great work! 💪

- Your Mentor"""
    
    # URL encode the message
    encoded_message = urllib.parse.quote(message)
    
    # Generate wa.me link
    wa_link = f"https://wa.me/{phone_for_url}?text={encoded_message}"
    
    return wa_link


def format_phone_indian(phone: str) -> str:
    """Format phone number for Indian numbers."""
    clean = "".join(c for c in phone if c.isdigit())
    
    if len(clean) == 10:
        return f"+91{clean}"
    elif len(clean) == 12 and clean.startswith("91"):
        return f"+{clean}"
    elif len(clean) == 11 and clean.startswith("0"):
        return f"+91{clean[1:]}"
    else:
        return f"+{clean}" if not clean.startswith("+") else clean
