# MediShield Demo Guide

This is the proof layer for the current system.

## What The Demo Shows

- Final risk score
- Status: Safe / Suspicious / High Risk
- Confidence level
- Human-readable explanation
- Failure visualization
- Clean JSON output

## Run It

```bash
python demo.py --images sample1.jpg sample2.jpg sample3.jpg
```

Optional JSON export:

```bash
python demo.py --images sample1.jpg sample2.jpg sample3.jpg --output demo_result.json
```

## Before vs After Story

### Before

- OCR output was hard to read as raw text
- Conflicts were hidden inside logs
- Judges had to guess why a sample was marked suspicious
- There was no clean one-shot demo

### After

- The system returns a structured result
- OCR failures are summarized by field
- Conflict images are shown explicitly
- Risk score and explanation are printed together
- The final output is easy to show in a demo

## What To Show Judges

1. Clean input images
2. Final risk score
3. Explanation list
4. Failure visualization
5. Clean JSON response

That keeps the story simple:

> MediShield does not just read medicine labels. It explains what failed, where it failed, and how confident the system is.
