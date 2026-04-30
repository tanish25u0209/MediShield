# Dataset Acquisition Strategy (PHASE 1)

## Immediate Goal
Obtain 10-15 high-quality pharmaceutical product images at **800×800px or higher** with:
- Sharp, readable batch numbers
- Visible expiry dates
- Full packaging visible (not thumbnails)

## Data Sources (Priority Order)

### OPTION 1: Public Pharmaceutical Datasets (FASTEST)
**Kaggle Datasets:**
- `imtkaggle/indian-medicines` 
- `pzimmerman/amazon-fresh-medicines`
- `krishnaik06/pharma-supply-Chain-dataset`

Commands:
```bash
kaggle datasets download imtkaggle/indian-medicines
kaggle datasets download pzimmerman/amazon-fresh-medicines
```

**Status**: Requires Kaggle API setup (10 mins) but gives 100+ samples instantly

---

### OPTION 2: E-Commerce Screenshots (QUICK DIY)
**Sources** (with good product images):
1. Snapdeal.com (Indian pharmacy)
2. Amazon India (Pharmacy section)
3. NetMeds.com 
4. Pharmeasy.in
5. 1mg.com

**How to collect**:
```
1. Search for "common medicines" (paracetamol, aspirin, vitamin B, etc.)
2. Right-click product → Save Image
3. Resize to 800×800px minimum
4. Save with descriptive names (e.g., "paracetamol_500mg_front.jpg")
```

**Expected yield**: 15 samples in 30 mins

---

### OPTION 3: Manufacturer Direct Images (HIGH QUALITY)
**Approach**: 
- Download product images from official pharmaceutical websites
- Examples: Cipla, Sun Pharma, Abbott India, Novartis India

**Links**:
- https://www.cipla.com/products
- https://www.sunpharma.com/products
- https://www.abbott.com/en-in

**Expected yield**: 10-20 high-resolution images

---

### OPTION 4: Create Synthetic Dataset (FALLBACK)
If natural images unavailable in 1 hour:
```python
# Generate realistic medicine labels using PIL
# Create 15 variations with:
# - Different medicine names
# - Readable batch numbers (BAT/2024/001, etc.)
# - Expiry dates (5-10 years out)
# - Manufacturer names
# - Professional appearance
```

---

## PHASE 1 WORKFLOW (DO THIS NOW)

### Step 1: Try Kaggle (5 mins)
```bash
kaggle datasets search medicine --max-rows=10
kaggle datasets download imtkaggle/indian-medicines -p ./medishield_data/raw/
```

**If succeeds**: Jump to Step 3
**If fails** (no API key): Jump to Step 2

### Step 2: Manual Collection (30 mins)
Use browser to download images from netmeds.com or amazon.in:
1. Chrome DevTools → Network tab to find image URLs
2. Screenshot → Resize to 800×800px
3. Save to `medishield_data/raw/`
4. Collect 10-15 samples

### Step 3: Organize into Dataset Structure
```
medishield_data/
├── raw/
│   ├── paracetamol_500mg/
│   │   ├── front.jpg
│   │   ├── back.jpg
│   │   └── strip.jpg
│   ├── aspirin_100mg/
│   │   ├── front.jpg
│   │   └── back.jpg
│   └── ... (10-15 more products)
└── metadata.json
```

### Step 4: Validate Image Quality
For each image, verify:
```
✓ Resolution >= 800×800px
✓ Text readable when zoomed 100%
✓ Batch number visible
✓ Expiry date visible
✓ No blurring/pixelation
```

### Step 5: Create Ground Truth Labels
For each medicine, manually annotate:
```json
{
  "product_id": "paracetamol_500mg",
  "medicine_name": "Paracetamol 500mg",
  "batch_number": "BAT/2024/00145",
  "expiry_date": "12/2026",
  "mfg_date": "06/2024",
  "manufacturer": "ABC Pharmaceuticals",
  "packaging_form": "tablet"
}
```

---

## TIME ESTIMATE
- **Option 1 (Kaggle)**: 5-10 mins if API ready, else +20 mins setup
- **Option 2 (E-commerce)**: 30 mins
- **Option 3 (Manufacturer)**: 20 mins
- **Option 4 (Synthetic)**: 45 mins

**RECOMMENDED**: Try Option 1 (Kaggle) → Fall back to Option 2 (E-commerce) → Option 4 (Synthetic) if needed

---

## Success Criteria (PHASE 1 COMPLETE)
✓ 10-15 images downloaded
✓ Images at 800×800px+ resolution
✓ Text readable (batch, expiry, name)
✓ Organized in `medishield_data/raw/` structure
✓ Ground truth labels prepared
✓ Old and new OCR can both achieve 50-70%+ detection on this data

---

## Then Proceed to PHASE 2
Only after ✓ ALL above:
1. Run `baseline_test.py` with new dataset
2. Compare old vs region-based OCR
3. Measure real improvement (or lack thereof)
4. Decide if region architecture is worth keeping
