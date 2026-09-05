#!/usr/bin/env python3
"""Standalone LLM connection test.

Tests SSL certificate configuration and LLM gateway connectivity without
starting all LandScout services.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

print("=" * 70)
print("LandScout LLM Connection Test")
print("=" * 70)
print()

# Check environment variables
print("1️⃣  Environment Variables:")
print(f"   SSL_CERT_FILE: {os.getenv('SSL_CERT_FILE', 'NOT SET')}")
print(f"   REQUESTS_CA_BUNDLE: {os.getenv('REQUESTS_CA_BUNDLE', 'NOT SET')}")
print(f"   PYTHONPATH: {os.getenv('PYTHONPATH', 'NOT SET')}")
print()

# Check certifi
print("2️⃣  Certificate Bundle:")
try:
    import certifi
    cert_path = certifi.where()
    print(f"   certifi path: {cert_path}")
    print(f"   exists: {Path(cert_path).exists()}")
except ImportError:
    print("   ❌ certifi not installed")
    sys.exit(1)
print()

# Load config
print("3️⃣  Loading Configuration:")
try:
    from agents.common.config import LLM_BASE_URL, LLM_MODEL, LLM_KEY_HELPER
    print(f"   LLM_BASE_URL: {LLM_BASE_URL}")
    print(f"   LLM_MODEL: {LLM_MODEL}")
    print(f"   LLM_KEY_HELPER: {LLM_KEY_HELPER}")
except Exception as e:
    print(f"   ❌ Failed to load config: {e}")
    sys.exit(1)
print()

# Test LLM connection
print("4️⃣  Testing LLM Connection:")
try:
    from agents.common.llm import build_llm
    
    print("   Building LLM client...")
    llm = build_llm()
    
    print("   Sending test message...")
    # Use CrewAI's LLM.call() method - temperature is already set on the LLM object
    messages = [{"role": "user", "content": "Say 'Hello' in one word only."}]
    
    response = llm.call(messages=messages)
    
    print(f"   ✅ SUCCESS!")
    print(f"   Response: {response}")
    print()
    print("=" * 70)
    print("✅ All tests passed! LLM connection is working.")
    print("=" * 70)
    
except Exception as e:
    print(f"   ❌ FAILED: {type(e).__name__}: {e}")
    print()
    print("=" * 70)
    print("❌ LLM connection test failed")
    print("=" * 70)
    print()
    print("Troubleshooting:")
    print("1. Check that SSL_CERT_FILE points to a valid certificate bundle")
    print("2. Verify devbar auth is working: /Applications/devbar.app/Contents/MacOS/devbar auth claude")
    print("3. Check network connectivity to the gateway")
    print("4. Try disabling SSL verification temporarily (NOT for production):")
    print("   export HTTPX_VERIFY=false")
    print()
    import traceback
    traceback.print_exc()
    sys.exit(1)
