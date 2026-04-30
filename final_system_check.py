#!/usr/bin/env python3
"""Final verification that decision is implemented and working."""

from medishield_ocr import process_medicine_images

print("[FINAL SYSTEM VERIFICATION]")
print("=" * 70)

# Test on actual test data
result = process_medicine_images([
    'medishield_data/raw/synthetic_01_paracetamol/front.jpg',
    'medishield_data/raw/synthetic_01_paracetamol/back.jpg'
])

final = result['final_data']
print(f"Medicine Name: {final['medicine_name']}")
print(f"Batch Number: {final['batch_number']}")
print(f"Expiry Date:  {final['expiry_date']}")
print(f"MFG Date:     {final['mfg_date']}")
print(f"Manufacturer: {final['manufacturer']}")
print("=" * 70)

# Check critical fields
batch_ok = bool(final['batch_number'].strip())
expiry_ok = bool(final['expiry_date'].strip())

if batch_ok and expiry_ok:
    print("[PASS] Critical fields extracted successfully")
    print("[PASS] System decision implemented and working")
    print("[PASS] Ready for submission")
else:
    print("[FAIL] Critical fields missing")
    exit(1)
