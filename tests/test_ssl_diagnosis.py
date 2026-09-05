#!/usr/bin/env python3
"""Test SSL connection to Salesforce gateway with and without verification."""

import httpx
import certifi
import os

# Get the gateway URL from env
url = "https://eng-ai-model-gateway.sfproxy.devx-preprod.aws-esvc1-useast2.aws.sfdc.cl/v1/chat/completions"

print("=" * 70)
print("SSL Diagnostic Test")
print("=" * 70)
print()

print(f"Testing connection to: {url}")
print()

# Test 1: With SSL verification (should fail)
print("1️⃣  Test WITH SSL verification (using certifi):")
try:
    client = httpx.Client(verify=certifi.where(), timeout=10.0)
    response = client.get(url)
    print(f"   ✅ SUCCESS: {response.status_code}")
except Exception as e:
    print(f"   ❌ FAILED (expected): {type(e).__name__}: {str(e)[:100]}")
print()

# Test 2: Without SSL verification (should work if it's just a cert issue)
print("2️⃣  Test WITHOUT SSL verification (insecure - testing only):")
try:
    client = httpx.Client(verify=False, timeout=10.0)
    response = client.get(url)
    print(f"   ✅ SUCCESS: {response.status_code}")
    print(f"   This confirms the issue is SSL certificate verification,")
    print(f"   NOT a network or gateway connectivity problem.")
except Exception as e:
    print(f"   ❌ FAILED: {type(e).__name__}: {str(e)[:100]}")
    print(f"   This suggests a deeper network or gateway issue.")
print()

print("=" * 70)
print("Diagnosis:")
print("=" * 70)
print()
print("If test 1 failed but test 2 succeeded, the problem is:")
print("   The Salesforce gateway uses an internal CA certificate")
print("   that is not in the standard certifi bundle.")
print()
print("Solutions:")
print("   1. Ask your Salesforce admin for the internal CA certificate")
print("   2. Add it to your certificate bundle")
print("   3. Or configure your system to trust the Salesforce CA")
print()
