"""
OpenAI client for MentorAI report generation.
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("[MentorAI] Warning: OPENAI_API_KEY not set", flush=True)
    client = None
else:
    client = OpenAI(api_key=OPENAI_API_KEY)
