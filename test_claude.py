import os
import sys

try:
    from anthropic import Anthropic
except ImportError:
    print("Error: The 'anthropic' package is not installed. Please run: pip install anthropic")
    sys.exit(1)

def test_claude_credits():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: Please set the ANTHROPIC_API_KEY environment variable.")
        print("Run: export ANTHROPIC_API_KEY='your-api-key'")
        return

    client = Anthropic(api_key=api_key)
    
    try:
        print("Sending request to Claude...")
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Return 'Yes' if you can read this, and nothing else."}
            ]
        )
        print(f"\nResponse: {response.content[0].text}")
        print("\nSuccess! Your API credits are working.")
    except Exception as e:
        print(f"\nError occurred:\n{e}")
        error_msg = str(e).lower()
        if "credit" in error_msg or "balance" in error_msg or "payment" in error_msg or "402" in error_msg:
            print("\nIt looks like your credits are still not active or haven't propagated yet.")
        
if __name__ == "__main__":
    test_claude_credits()
