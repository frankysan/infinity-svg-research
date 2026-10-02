# Current Army issue review

The local visual reviewer has a deliberately narrow **Current Army issues** scope for short-term
triage. Its purpose is to answer which current Army SVG byte streams still have concrete problems
before broader Vyo identity/coverage work resumes.

## Inclusion boundary

An SVG enters this queue when the scanner reports at least one of:

- a hard `classification`;
- a parse error;
- the `missing-external-image` advisory, because the dependency is actually absent.

Other advisory-only findings are excluded from this scope. In particular, subpixel detail, mild palette
fragmentation, and large-path-payload signals remain research/review leads rather than current defects.
They can still be investigated separately without expanding this first-pass queue.

Issue rows are grouped by exact SHA-256. Multiple semantic Army paths backed by identical bytes therefore
consume one review item. The UI retains the complete affected-path list and warns when any current file is
missing or no longer matches the scan hash.

## Research state

`research/army-issue-review.json` is the Git-tracked triage ledger. Each exact source group can be marked:

- `uninvestigated`;
- `research-active`;
- `solution-identified`;
- `candidate-validated`;
- `ready-for-publication`;
- `no-action-required`.

Terminal/decision-like states require a note. This ledger is separate from
`research/vyo-identity-decisions.json`; current-source pathology triage must not silently become a Vyo
identity decision.

## Reviewer input

Generate or reuse a full scanner JSON for the same current Army source tree passed as `--army-root`, then
start the reviewer with `--scan`:

```powershell
python .\tools\scan.py "C:\path\to\current Army SVGs" --json .\output\army-scan.json
python .\tools\vyo_review.py .\research\vyo-full-inventory-v1.json `
  "C:\path\to\army-symbol-build.json" "C:\path\to\symbol-publication.json" `
  --scan .\output\army-scan.json `
  --decisions .\research\vyo-identity-decisions.json `
  --army-root "C:\path\to\current Army SVGs" `
  --vyo-root "C:\path\to\Vyo SVG Vectors" `
  --output .\output\vyo-review `
  --inkscape "C:\Program Files\Inkscape\bin\inkscape.com"
```

When a scan is supplied, **Current Army issues** is the default UI scope. Vyo matches, unresolved identities,
and the full asset list remain available as separate scopes for later work.
