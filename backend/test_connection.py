"""
Diagnostic script to test Polymarket connection and find correct settings.
Run: python test_connection.py
"""

import os
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from eth_account import Account

def test_connection():
    private_key = os.getenv("PRIVATE_KEY", "")
    funder = os.getenv("FUNDER_ADDRESS", "")
    sig_type = int(os.getenv("SIGNATURE_TYPE", "0"))

    if not private_key:
        print("ERROR: No PRIVATE_KEY in .env file")
        return

    # Get EOA address from private key
    if not private_key.startswith("0x"):
        private_key_with_prefix = "0x" + private_key
    else:
        private_key_with_prefix = private_key
        private_key = private_key[2:]  # Remove 0x for ClobClient

    try:
        account = Account.from_key(private_key_with_prefix)
        eoa_address = account.address
    except Exception as e:
        print(f"ERROR: Invalid private key format: {e}")
        return

    print("=" * 60)
    print("POLYMARKET CONNECTION DIAGNOSTIC")
    print("=" * 60)
    print(f"EOA Address (from private key): {eoa_address}")
    print(f"Funder Address (from .env):     {funder or 'Not set'}")
    print(f"Signature Type (from .env):     {sig_type}")
    print("=" * 60)

    # Test each signature type
    for test_sig_type in [0, 1, 2]:
        sig_name = {0: "EOA", 1: "Poly Proxy", 2: "Gnosis Safe"}[test_sig_type]
        print(f"\n--- Testing Signature Type {test_sig_type} ({sig_name}) ---")

        try:
            # For sig type 1, we need funder
            test_funder = funder if test_sig_type == 1 else None

            client = ClobClient(
                host="https://clob.polymarket.com",
                key=private_key,
                chain_id=137,  # Polygon mainnet
                signature_type=test_sig_type,
                funder=test_funder,
            )

            # Try to derive credentials
            print(f"  Deriving API credentials...")
            creds = client.create_or_derive_api_creds()

            if hasattr(creds, 'api_key'):
                api_key = creds.api_key
            elif isinstance(creds, dict):
                api_key = creds.get('apiKey', 'unknown')
            else:
                api_key = str(creds)[:30]

            print(f"  ✓ Credentials derived: {api_key[:20]}...")

            # Try to get open orders (simple API call to test)
            client.set_api_creds(creds)
            print(f"  Testing API call...")

            try:
                orders = client.get_orders()
                print(f"  ✓ API call successful! Found {len(orders) if orders else 0} orders")
                print(f"\n  ★★★ SIGNATURE TYPE {test_sig_type} ({sig_name}) WORKS! ★★★")
                print(f"  Use these settings in .env:")
                print(f"    SIGNATURE_TYPE={test_sig_type}")
                if test_funder:
                    print(f"    FUNDER_ADDRESS={test_funder}")
                return
            except Exception as api_error:
                print(f"  ✗ API call failed: {api_error}")

        except Exception as e:
            print(f"  ✗ Failed: {e}")

    print("\n" + "=" * 60)
    print("NONE OF THE SIGNATURE TYPES WORKED")
    print("=" * 60)
    print("\nPossible issues:")
    print("1. Your PRIVATE_KEY doesn't match your Polymarket account")
    print("2. For Poly Proxy (type 1), you need FUNDER_ADDRESS set")
    print("3. Your account may need to be activated on Polymarket first")
    print("\nTo find your funder address:")
    print("1. Go to polymarket.com and log in")
    print("2. Go to Settings or Wallet section")
    print("3. Find your 'Proxy Wallet' or 'Trading Address'")
    print("4. That's your FUNDER_ADDRESS")

if __name__ == "__main__":
    test_connection()
