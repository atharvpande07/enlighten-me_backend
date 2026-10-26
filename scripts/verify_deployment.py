"""Deployment Verification & Health Diagnostic CLI
Usage: python scripts/verify_deployment.py [BASE_URL]
Example: python scripts/verify_deployment.py http://127.0.0.1:8000
"""

import sys
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def run_diagnostics(base_url: str):
    print(f"\n>> Running Enlighten Me Deployment Diagnostics against: {base_url}\n")
    passed = 0
    total = 0

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        # Check 1: Root Discovery Ping
        total += 1
        try:
            res = client.get("/")
            if res.status_code == 200 and res.json().get("status") == "online":
                print("  [PASS] Root Discovery Endpoint (/) is online")
                passed += 1
            else:
                print(f"  [FAIL] Root endpoint returned status {res.status_code}")
        except Exception as e:
            print(f"  [FAIL] Could not connect to root endpoint: {e}")

        # Check 2: Health Diagnostic Endpoint
        total += 1
        try:
            res = client.get("/api/v1/health")
            data = res.json()
            if (
                res.status_code == 200
                and data.get("status") == "ok"
                and data.get("timeout_seconds") == 120
            ):
                print(
                    f"  [PASS] Health Diagnostic (/api/v1/health) verified (v{data.get('version')}, "
                    f"Max Audio: {data.get('max_audio_mb')}MB, Timeout: {data.get('timeout_seconds')}s)"
                )
                passed += 1
            else:
                print(f"  [FAIL] Health check unexpected response: {data}")
        except Exception as e:
            print(f"  [FAIL] Health check failed: {e}")

        # Check 3: Security Guard (401 Unauthorized for Unauthenticated Lecture Process)
        total += 1
        try:
            res = client.post(
                "/api/v1/lectures/process",
                data={"duration_seconds": 1800},
                files={"audio_file": ("test.m4a", b"fake audio", "audio/mp4")},
            )
            if res.status_code == 401:
                print("  [PASS] JWT Security Dependency properly rejects unauthenticated uploads (401)")
                passed += 1
            else:
                print(f"  [FAIL] Expected 401 from protected endpoint, received: {res.status_code}")
        except Exception as e:
            print(f"  [FAIL] Security guard test failed: {e}")

        # Check 4: Webhook Security Guard (401 for Missing Webhook Secret)
        total += 1
        try:
            res = client.post(
                "/api/v1/webhooks/revenuecat",
                json={"api_version": "1.0", "event": {"type": "TEST", "app_user_id": "test"}},
            )
            if res.status_code == 401:
                print("  [PASS] Webhook Security Dependency properly rejects unauthenticated calls (401)")
                passed += 1
            else:
                print(f"  [FAIL] Expected 401 from webhook endpoint, received: {res.status_code}")
        except Exception as e:
            print(f"  [FAIL] Webhook guard test failed: {e}")

    print(f"\n-- Diagnostics Summary: {passed}/{total} Checks Passed --\n")
    return passed == total


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    success = run_diagnostics(target)
    sys.exit(0 if success else 1)
