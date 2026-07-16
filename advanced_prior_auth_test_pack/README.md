# Advanced Prior-Authorization Test Pack

This pack is designed to test extraction and Boolean medical-necessity reasoning, not just keyword matching. Each synthetic chart resembles a multi-page clinical record with demographics, insurance, problem list, medications, visits, diagnostics, and a planned procedure.

## Cases

- Case 1: nested `ALL -> EITHER -> ALL`, expected `MEETS_MEDICAL_NECESSITY`.
- Case 2: `ANY` with an inner `EITHER`, expected `DOES_NOT_MEET_MEDICAL_NECESSITY`.
- Case 3: multiple mandatory `AND` criteria with unknown evidence, expected `INSUFFICIENT_DOCUMENTATION`.

Use `expected_results.json` as the gold label and Boolean trace.

## Florida Blue / BCBS regression set

The payer-specific baseline lives in `charts/bcbs/` and `charts/patients_bcbs/`.
Use `expected_results_bcbs.json` for the exact policy/chart pairings and expected results:

- Varicose-vein ablation: `MET`.
- Carotid angioplasty/stenting: `NOT_MET` because the required anatomic contraindication to
  carotid endarterectomy is explicitly absent.
- Intracranial mechanical thrombectomy: `INSUFFICIENT_EVIDENCE` because salvageable brain
  tissue is not documented.
- Pacemaker chart paired with the varicose-vein policy: `POLICY_NOT_APPLICABLE`; no criteria
  should be evaluated.

The three synthetic BCBS charts can be regenerated with:

```bash
python advanced_prior_auth_test_pack/generate_bcbs_patients.py
```
