# Advanced Prior-Authorization Test Pack

This pack is designed to test extraction and Boolean medical-necessity reasoning, not just keyword matching. Each synthetic chart resembles a multi-page clinical record with demographics, insurance, problem list, medications, visits, diagnostics, and a planned procedure.

## Cases

- Case 1: nested `ALL -> EITHER -> ALL`, expected `MEETS_MEDICAL_NECESSITY`.
- Case 2: `ANY` with an inner `EITHER`, expected `DOES_NOT_MEET_MEDICAL_NECESSITY`.
- Case 3: multiple mandatory `AND` criteria with unknown evidence, expected `INSUFFICIENT_DOCUMENTATION`.

Use `expected_results.json` as the gold label and Boolean trace.
