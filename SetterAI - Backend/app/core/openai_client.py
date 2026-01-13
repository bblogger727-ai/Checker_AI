"""
OpenAI Client for SetterAI

Shared configuration for paper generation and solution creation.
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found. Please set it in .env file.")

client = OpenAI(api_key=OPENAI_API_KEY)
