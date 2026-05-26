import os, anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
print("Testing with cache_control (matches simulation)...")
try:
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        system=[
            {
                "type": "text",
                "text": "You are managing an NBA team. Return ONLY valid JSON: {\"effort\": 1.0, \"reasoning\": \"test\"}",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": "What effort level do you choose?"}],
        timeout=15.0,
    )
    print("SUCCESS:", msg.content[0].text[:100])
except Exception as e:
    print(f"FAILED with cache_control: {type(e).__name__}: {e}")

print()
print("Testing WITHOUT cache_control (fallback)...")
try:
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        system="You are managing an NBA team. Return ONLY valid JSON: {\"effort\": 1.0, \"reasoning\": \"test\"}",
        messages=[{"role": "user", "content": "What effort level do you choose?"}],
        timeout=15.0,
    )
    print("SUCCESS:", msg.content[0].text[:100])
except Exception as e:
    print(f"FAILED without cache_control: {type(e).__name__}: {e}")
