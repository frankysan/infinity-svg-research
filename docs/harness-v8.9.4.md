# SVG research harness v8.9.4

> **Historical baseline:** this document preserves terminology from the pre-repository harness.
> Where it says `third-party` or uses manifest values such as `human-sphere-third-party`, the current
> repository provenance taxonomy classifies that material as **second-party**. Legacy field names are
> retained here only to describe the v8.9.4 behavior accurately.

Standalone experimental SVG optimization/validation tooling. This is intentionally outside the InfinityDB repository.

## Exact transforms currently implemented

- `off-artboard-content`: removes provably off-artboard top-level content and dependent off-artboard `textPath` nodes.
- `duplicate-fill-stroke-geometry`: merges proven adjacent duplicate fill/stroke path geometry only when the systematic detector threshold is met (at least 8 matching pairs and at least 4,000 bytes of duplicated path data). Isolated duplicate pairs are reported in transform statistics but are not rewritten.

Inputs are never overwritten. A candidate SVG is written under the selected output directory and then render-compared with the source.

## File and directory inputs

Positional inputs may be individual SVG files or directories. Directories are searched recursively for SVG files:

```powershell
python .\optimize.py "C:\path\to\SYMBOLS 20260929-114338" --output-dir .\run
```

For directory inputs, the source directory structure is preserved below the output directory. For example:

```text
units\foo.svg -> run\units\foo\foo.candidate.svg
```

Duplicate source paths are processed once. If multiple distinct inputs would map to the same output path, the harness adds a short deterministic path hash. If the output directory is inside an input directory, that output subtree is excluded from discovery so generated candidates are not recursively reprocessed.

Unchanged SVGs are analyzed but not rendered. By default the console prints only changed/rejected cases plus a summary; add `--verbose` to print every no-change case.

## Rendering modes

The default renderer is `inkscape-shell`. v3+ use **one shared `inkscape --shell` process for the entire run**. Every changed source/candidate pair is opened in sequence and all configured sizes are exported before the shell exits. This avoids paying the Windows Inkscape startup cost once per case.

The shared shell can be restarted periodically for long runs:

```powershell
python .\optimize.py source1.svg source2.svg --shell-restart-every 100
```

`0` (the default) means no periodic restart.

The previous one-process-per-export behavior remains available for debugging/reference:

```powershell
python .\optimize.py source.svg --renderer inkscape-one-shot
```

In shell mode, the Inkscape version is obtained with the `inkscape-version` shell action inside the already-running process, so no separate startup is required. In one-shot mode the version is not probed by default; use `--probe-version` when needed.

To select a specific Inkscape build:

```powershell
python .\optimize.py source.svg --inkscape "C:\path\to\inkscape.com" --output-dir .\run
```

Default validation sizes are 64, 128, 256, and 1024 px. Exact transforms are accepted only when every rendered RGBA pixel is identical at every configured size.

The schema-v4 manifest records the original input arguments, discovery provenance/output key for each source, run-level shared-renderer timing/process information, restart batches, Inkscape version source, source/candidate hashes, transform statistics, and per-case comparison metrics. Shared-shell render time is intentionally reported at run/batch scope rather than misleadingly attributed to individual cases.


## Duplicate fill/stroke gating

The duplicate fill/stroke optimizer is deliberately gated by the same evidence threshold used by scanner v7. The corpus run found an isolated two-pair case (Qishi StateEmpire TAG Pilots) whose rewrite differed by only a handful of one-channel antialiasing pixels at larger render sizes. That case is therefore not treated as the systematic Illustrator export pathology.

The transform requires both:

- at least 8 exact fill/stroke geometry pairs; and
- at least 4,000 bytes of duplicated path data.

This preserves the validated Trinitarians rewrite while preventing opportunistic rewriting of weak duplicate signals. Render validation remains mandatory even after the detector gate passes.

## Approximate palette-repair experiment

`palette_repair.py` is intentionally separate from `optimize.py`. It experiments on
SVGs classified by the scanner as `palette-fragmented-trace`; no output from this
command is auto-accepted as production-safe.

The first experiment infers the traced palette from flat-fill paths, then snaps mapped intermediate colours
to the nearest endpoint wherever they are reused in fill/stroke paint declarations. It does **not** merge or simplify geometry. This isolates
the visual cost of palette repair before any geometry reconstruction is attempted.

```powershell
python .\palette_repair.py "C:\path\to\SYMBOLS snapshot" --output-dir .\palette-run --inkscape "C:\path\to\inkscape.com"
```

Default render comparison sizes are 64, 128, 256, 512, 1024, and 1600 px. The
manifest records detection evidence, inferred endpoints, changed paths/colours, and
source-to-candidate pixel deltas. Every candidate has verdict
`experimental-review-required` regardless of measured error.

Weaker `palette-fragmentation` advisory cases (for example Qapu-like signals) are
excluded by default. Add `--include-advisory` only when explicitly exploring them.

## Approximate same-colour consolidation experiment

`palette_consolidate.py` is the second approximate stage. It starts from the same palette-snapped intermediate, then looks for conservative boolean-union opportunities without allowing Inkscape to rewrite the whole document.

Candidate groups must be consecutive sibling closed paths with identical effective flat fill, no stroke, full opacity, the default nonzero fill rule, no path-local transform/effect, and bounding-box-connected geometry. Each group is copied into a tiny temporary SVG and unioned by Inkscape. The compact union `d` is extracted with Scour and spliced back into the original snapped SVG only when applying that one group makes the complete serialized SVG smaller.

This avoids a failed first approach where exporting the whole unioned document through Inkscape reduced path count but substantially increased path-data size because Inkscape rewrote and split curves during boolean operations.

```powershell
python .\palette_consolidate.py "C:\path\to\SYMBOLS snapshot" --output-dir .\palette-consolidation-run --inkscape "C:\path\to\inkscape.com"
```

The manifest reports every planned union group, the union path-data size, independently measured serialized-byte saving, accepted/rejected-by-size status, and three render comparisons:

- source -> palette-snapped;
- palette-snapped -> consolidated (geometry-only delta);
- source -> consolidated (total approximate delta).

A consolidated candidate is emitted only when at least one group is byte-beneficial. It is still always `experimental-review-required`; byte reduction is not treated as visual acceptance. Temporary probe SVGs are deleted by default; use `--keep-probes` for debugging.

Approximate scripts preserve whether the source originally had an XML declaration so serialization overhead does not masquerade as a size regression or saving.

## Reference-guided boundary reconstruction experiment

`reference_reconstruct.py` is a restorative experiment for flat two-colour symbols when an external raster reference exists. It is intentionally separate from the exact optimizer and from the palette-only experiments.

The current mode uses the reference alpha silhouette as a base region and the second dominant reference colour as an overlay region, traces both masks into `evenodd` paths, and sweeps contour simplification tolerances. For every geometry it emits both a **source-palette** variant (restored geometry with the Army SVG endpoint colours) and a **reference-palette** variant (restored geometry with the reference PNG colours).

```powershell
python .\reference_reconstruct.py `
  "C:\path\to\shaolin-warrior-monks-1-1.svg" `
  "C:\path\to\HumanSphere\Yu_Jing_-_Shaolin_Warrior_Monks_v2_-_-N3-_-Vyo-.png" `
  --inkscape "C:\path\to\inkscape.com" `
  --output-dir .\shaolin-reference-run
```

This stage requires OpenCV (`opencv-python-headless`). It never auto-accepts a candidate. Human Sphere may contain older revisions, so reference matches are evidence for review, not authority over the current Army artwork.

## Human Sphere PNG to Army SVG matching

`human_sphere_match.py` inventories the downloaded Human Sphere PNG corpus and the Army SVG corpus, groups exact PNG duplicates, normalizes filenames, and generates a short candidate list per SVG using token/filename evidence. It avoids a naive full all-pairs image comparison.

Fast lexical pass:

```powershell
python .\human_sphere_match.py `
  "C:\path\to\SYMBOLS 20260929-114338" `
  "C:\path\to\human-sphere-download" `
  --output-dir .\human-sphere-match
```

Optional visual reranking of the lexical shortlist:

```powershell
python .\human_sphere_match.py `
  "C:\path\to\SYMBOLS 20260929-114338" `
  "C:\path\to\human-sphere-download" `
  --output-dir .\human-sphere-match-visual `
  --visual `
  --inkscape "C:\path\to\inkscape.com"
```

Outputs include `png-inventory.json`, `svg-inventory.json`, `matches.json`, and `top-matches.csv`. Matching is deliberately candidate ranking only: historical/version mismatches must be reviewed before a PNG is used for restoration.

## Windows subprocess output encoding

v8.1 explicitly decodes Inkscape subprocess output as UTF-8 with replacement for malformed diagnostic bytes. This avoids Windows `cp1252` `UnicodeDecodeError` failures in Python's background pipe-reader threads when Inkscape emits UTF-8 or otherwise non-CP1252 console output. The same hardening is applied to all Inkscape subprocess call sites in the harness.

## Human Sphere authority / independence review

Human Sphere is explicitly treated as a **third-party, non-authoritative source**. A PNG being present in the archive, matching a filename, or rendering nearly identically to an Army SVG does not establish that it is canonical or independent evidence. In particular, PNG names that mirror Army profile slugs (for example `*-1-1.png`) may simply be derivative/current renders and are assigned low independent evidentiary value.

`human_sphere_review.py` consumes an existing `matches.json` without rerunning Inkscape. Supplying a scanner report lets it focus on the SVGs already flagged for structural investigation:

```powershell
python .\human_sphere_review.py .\human-sphere-match-visual\matches.json `
  --scan .\scan-v7.json `
  --output-dir .\human-sphere-review
```

Outputs:

- `review.json`: full candidate review with source-authority policy and heuristic provenance hints;
- `review.csv`: compact review table;
- `restoration-leads.csv`: historical/non-derivative candidates worth manual investigation, never automatic restoration inputs;
- `derivative-like-top-matches.csv`: visually strong Army-style PNG matches that are useful for equivalence checks but should not be counted as independent corroboration.

Filename provenance labels (`historical-n3-marker`, `army-style-render-name`, `corvus-belli-origin-path-hint`, etc.) are heuristics only. A Corvus Belli-looking path inside a Human Sphere archive must be verified independently before it is treated as first-party provenance.

`reference_reconstruct.py` now records `--reference-source-kind` in its manifest. The default is `human-sphere-third-party`; this provenance metadata never changes the experiment's `automatic_acceptance: false` behavior.


### v8.3 provenance tightening: Vyo/fan-vector markers

The completed Human Sphere corpus exposed an important provenance trap. Many historical-looking unit-logo PNG filenames end in `-Vyo-`. A Corvus Belli forum thread in the **FanArt** section documents Vyo's long-running high-resolution unit-emblem/vector project; Vyo explicitly describes building vectors and later notes that the official Army app made the project largely superfluous once Army exposed SVG assets. Therefore a `-Vyo-` filename is treated as a strong **fan-vector provenance warning**, not as first-party historical evidence.

`human_sphere_review.py` now labels these candidates `vyo-fan-vector-marker`, assigns `fan-reference-only`, excludes them from `restoration-leads.csv`, and writes them separately to `fan-derived-reference-leads.csv`. They remain useful for visual comparison and for locating which historical design was being represented, but they do not independently corroborate the intended geometry.

The review now also writes `investigation-leads.csv`. This is the broad queue for provenance hunting. It is deliberately distinct from `restoration-leads.csv`, which is kept conservative.

Verified provenance can be supplied explicitly with `--provenance-ledger` using `provenance-ledger.example.json`. A ledger entry can key a PNG by SHA-256 and/or relative path and record `source_authority`, `independence`, `provenance_status`, `source_url`, and a note. Only entries explicitly marked with `provenance_status: verified` and `source_authority: first-party-current` or `first-party-historical` are promoted above the filename heuristics.

Example:

```powershell
python .\human_sphere_review.py .\human-sphere-match-visual\matches.json `
  --scan .\scan-v7.json `
  --provenance-ledger .\provenance-ledger.json `
  --output-dir .\human-sphere-review
```

This keeps source authority a separately auditable fact instead of something inferred from visual similarity or Human Sphere filenames.

## v8.4 historical first-party Army provenance probe

`historical_army_probe.py` moves provenance hunting away from Human Sphere and back to old first-party Infinity Army asset URLs. The bundled `historical-army-assets.json` currently records high-confidence legacy Yu Jing logo IDs for the four palette-fragmented units with useful historical matches:

- Zhanshi -> Yu Jing legacy logo 1;
- Shaolin Warrior Monks -> legacy logo 13;
- Zhanshi Yisheng -> legacy logo 14;
- Chaiyi Yaokong -> legacy logo 19.

The identity evidence is kept distinct from the asset URL evidence. Old Army-generated lists directly expose first-party PNG URLs for Shaolin, Yisheng, and Chaiyi; Zhanshi's logo ID is independently corroborated by multiple old Army-list reproductions. The historical SVG URLs are generated from the documented Army SVG endpoint pattern and are explicitly marked as inferred until an archived capture proves that exact URL existed.

Plan-only run (no network):

```powershell
python .\historical_army_probe.py --output-dir .\historical-army-probe
```

Probe the first-party URLs as served today and query Wayback for dated captures, then compare any validated assets with the current Army SVGs:

```powershell
python .\historical_army_probe.py `
  --fetch-direct `
  --wayback `
  --svg-root "C:\path\to\SYMBOLS 20260929-114338" `
  --inkscape "E:\path\to\inkscape.com" `
  --output-dir .\historical-army-probe
```

Outputs:

- `probe-results.json`: complete plan, transport/CDX results, hashes, format validation, provenance state, and optional visual comparisons;
- `probe-results.csv`: compact audit table;
- `verified-first-party-assets.json`: only successfully validated first-party retrievals;
- `assets/<unit>/...`: retrieved bytes, kept separate from the current Army inputs.

A **direct current fetch from an old Army URL is not treated as proof that the returned bytes are historical**. It is recorded as a verified current first-party retrieval. A successfully validated Wayback capture of the original first-party URL is recorded as `first-party-historical`, with the archive timestamp and digest. Neither case automatically accepts a restoration candidate.

This is deliberately independent of the Human Sphere provenance ledger: a fan/community PNG can help identify what to search for, but it cannot promote itself to first-party evidence. Once a historical first-party asset is recovered, `reference_reconstruct.py --reference-source-kind first-party-historical` can use that asset in a separate review-required reconstruction experiment.


## v8.5 first-party render reconstruction and historical-resolution guardrails

The first historical Army probe recovered genuine first-party PNG captures for Zhanshi,
Shaolin Warrior Monks, and Chaiyi Yaokong, but the recovered files are list icons with
only a 14x14 non-transparent content region inside a 20x14 PNG canvas. They are therefore
strong provenance evidence and useful **icon-scale guardrails**, but they do not contain
enough spatial information to establish high-resolution vector boundaries. No historical
SVG capture was recovered for these targets in the tested Wayback windows. Zhanshi
Yisheng currently has no verified historical capture in the probe output.

`historical_probe_analyze.py` makes that distinction explicit:

```powershell
python .\historical_probe_analyze.py .\historical-army-probe\probe-results.json `
  --svg-root "C:\path\to\SYMBOLS 20260929-114338" `
  --output-dir .\historical-evidence-analysis
```

It reports whether a current first-party SVG retrieval matches the local Army input,
whether historical/current PNG bytes are identical, the effective alpha-bounded raster
resolution, and the strongest geometry role justified by the recovered asset. A verified
historical 14x14 icon is labelled `coarse-first-party-icon-guardrail-only`, never as a
high-resolution restoration source.

`source_reconstruct.py` is the preferred next boundary-reconstruction experiment for
`palette-fragmented-trace` symbols. Instead of taking geometry from Human Sphere or any
other third-party reference, it renders the **current first-party Army SVG itself** at high
resolution, infers the primary flat-colour axis, preserves significant off-axis accent
colours visible in the render, traces the resulting flat masks, and sweeps contour
simplification tolerances. This keeps the current first-party rendered appearance as the
geometry source while removing trace/export fragmentation.

```powershell
python .\source_reconstruct.py .\shaolin-warrior-monks-1-1.svg `
  --target shaolin-warrior-monks `
  --historical-probe .\historical-army-probe\probe-results.json `
  --inkscape "E:\path\to\inkscape.com" `
  --output-dir .\shaolin-source-reconstruction
```

The default comparison sizes are 64, 128, 256, 512, 1024, and 1600 px. If a verified
historical first-party PNG is available, its native effective resolution is rendered as an
additional comparison size and reported separately as a coarse guardrail. It does not
participate in the normal multi-resolution RMSE summary.

The palette extractor starts with the dominant path-fill interpolation axis but also scans
the rendered opaque pixels for significant colours far from that axis. This is required for
legitimate accents represented by non-path geometry; for example, GUD-N's yellow star is
preserved even though that colour was not visible to the path-only palette detector.

Every source-reconstructed candidate remains `automatic_acceptance: false`. The method is
approximate because rasterization, colour classification, contour extraction, and contour
simplification all move boundaries. Human Sphere may still be used as a separate visual
comparison, but it is not used to define candidate geometry in this experiment.
## v8.6 payload audit integration and duplicate grouping

A full 1,101-SVG payload audit exposed three useful review classes that element-count-only
heuristics can miss. The main `scan.py` remains the single scanner; the temporary companion
payload scan is treated as threshold-validation data rather than a second maintained tool.

The scanner now records SHA-256 for every source and groups byte-identical SVGs in the JSON
report. `summary.exact_duplicate_groups` gives the number of groups, `duplicate_groups` lists
the group hashes/paths, and each file row includes `exact_duplicate_group_size`. This matters
for research runs because multiple semantic Army assets may be literally identical and should
not consume separate investigation effort. The audited snapshot contained 212 exact duplicate
groups; the 17 payload-audit hits collapsed to 11 unique byte streams.

The existing structural classes already cover the important hard cases:

- Wolfgang-scale vector payloads are classified as `micro-contour-explosion` when contour
  evidence is present, or `oversized-path-data` as the conservative fallback. The measured
  Wolfgang payload was about 1.17 MB of path data, ~99.8% of the SVG.
- Druze/Taowu-style files with >=100 KB of embedded raster data occupying >=40% of the SVG
  are classified as `embedded-raster-heavy`.
- Guijia-family Illustrator gradient/mask exports keep the stronger
  `flattened-gradient-mask` classification rather than being collapsed into the generic raster
  class.
- Ruby Monday keeps the stronger blend-stack classification.

A new advisory-only `large-path-payload` threshold surfaces medium-sized vector outliers that
do not justify a pathology label: at least 100,000 bytes of vector path data, at least 90% of
the SVG size, a largest individual path of at least 20,000 bytes, no gradients, and no embedded
images. Against the 1,101-file payload audit this added only Denma Connolly beyond the already
classified Wolfgang duplicate. It is intentionally an advisory, not an automatic rewrite cue.

The scanner regression tests can be run with:

```powershell
python -m unittest -v test_scan.py
```

They cover Denma-scale advisory gating, Wolfgang-scale oversized path classification,
Druze-style raster-heavy classification, and deterministic exact-duplicate grouping.

## v8.7 recovered-research experiments

The previous SVG research thread established two approximate repair strategies strongly enough
to preserve them as reproducible harness experiments. They remain deliberately separate from
`optimize.py`: neither transform is exact, and neither is eligible for automatic acceptance.

### Confirmed blend stacks -> `<use>` reconstruction

`blend_use_reconstruct.py` targets SVGs classified as `flattened-blend-stack`. It reuses the
same conservative stack detector as `scan.py`, keeps the first generated step as the source
group, replaces later translated copies with `<use>` elements, then removes simple unused
Illustrator class rules and unreachable gradients. The output is always render-compared unless
`--no-render` is requested explicitly.

This formalizes the earlier Ruby Monday experiment: the raw source contained three 35-step
RUBY stacks and three 53-step Monday stacks. The standalone experiment reduced the file from
1,875,476 to 96,886 bytes, gradients from 1,383 to 39, and replaced 258 generated blend steps.
At 1600 px the measured RGB RMSE was about 2.86/255 with 1.54% changed pixels, concentrated
mostly around Illustrator text-edge rounding/antialiasing. Those historical numbers are a
reference point, not acceptance thresholds for future files.

```powershell
python .\blend_use_reconstruct.py `
  "C:\path\to\kazuraba-ruby-monday-1-1.svg" `
  --inkscape "C:\path\to\inkscape.com" `
  --output-dir .\ruby-blend-use
```

The transform refuses non-`flattened-blend-stack` inputs unless `--force` is supplied. It also
rejects confirmed stacks whose step groups carry attributes other than IDs; that conservative
restriction avoids silently losing group-level paint/transform semantics.

### Micro-contour pruning and recovered one-pass simplification

`micro_contour_prune.py` formalizes the Wolfgang experiment. It removes closed compound-path
subpaths whose conservative maximum span is at most 0.1 SVG units by default. v8.7 initially
refused paths containing later relative `m` movetos, which skipped 56 of Wolfgang's 71 paths
and therefore removed nothing. v8.8 fixes that safely: any path that actually loses a subpath
is rewritten to explicit absolute path commands before the deleted contours are omitted. This
removes dependence on predecessor subpaths while preserving open contours.

The corrected v8.8 pruning stage has now been revalidated against the **actual raw Wolfgang
source** from `SYMBOLS 20260929-114338`. At `--max-span 0.1` it processed 19,140 closed
contours and removed 13,795 of them. The final raw-source prune + one-simplify + Scour run
reduced 1,175,564 bytes to 233,209 bytes (80.16%) and measured 4.652896/255 RGBA RMSE at
1200 px, essentially reproducing the earlier 4.652/255 result. Alpha RMSE was zero at every
validation size. A spatial diff check found zero changed pixels inside radius 480 px of the
1200 px render: all differences were confined to the distressed outer lettering; the central
emblem geometry was unchanged.

A rescan of the 233,209-byte candidate no longer classifies it as
`micro-contour-explosion`. It retains only the expected `subpixel-detail-heavy` advisory:
5,342 closed subpaths remain, including 711 micro-subpaths (13.3%), versus 14,901 micro-
subpaths (77.9%) in the raw source. Wolfgang is therefore considered resolved at the research
level. The byte-identical Reinforcements Wolfgang source can reuse the same validated result
under its semantic filename.

The recovered history also established that exactly one Inkscape `path-simplify` pass was
applied only to the 41 distressed-lettering paths changed by pruning, followed by Scour. v8.8
now exposes that sequence explicitly with `--simplify-once --scour`; it is still opt-in and
always `experimental-review-required`. On the actual raw Wolfgang source the recovered pipeline produced the 233,209-byte candidate
reported above, with 4.652896/255 RGBA RMSE at 1200 px. A second simplify pass remains
intentionally unsupported because the earlier experiment visibly damaged the distressed lettering.

Pruning only:

```powershell
python .\micro_contour_prune.py `
  "C:\path\to\wolfgang-amadeus-wolff-1-1.svg" `
  --max-span 0.1 `
  --inkscape "C:\path\to\inkscape.com" `
  --output-dir .\wolfgang-prune
```

Recovered prune + one simplify + Scour experiment:

```powershell
python .\micro_contour_prune.py `
  "C:\path\to\wolfgang-amadeus-wolff-1-1.svg" `
  --max-span 0.1 `
  --simplify-once `
  --scour `
  --inkscape "C:\path\to\inkscape.com" `
  --output-dir .\wolfgang-prune-simplify
```

Default validation sizes are 64, 128, 256, 512, 1024, and 1200 px. The generated manifest
records each stage, contour-removal counts, selected simplification paths, final byte reduction,
and render metrics. The verdict is always `experimental-review-required`.

### Focused regression tests

```powershell
python -m unittest -v test_scan.py test_research_transforms.py
```

The added tests verify absolute-subpath pruning, safe rebasing/canonicalization of later relative
movetos (including implicit lineto pairs), confirmed translated blend-stack replacement, CSS
cleanup, and unreachable-gradient cleanup.

## v8.9 Guijia-family gradient/mask reconstruction

`gradient_mask_reconstruct.py` targets the `flattened-gradient-mask` exporter pathology rather
than generic SVG minification. The raw Guijia source contains approximately 43 grayscale strips,
a masked outer disc, a 44-circle multiply stack, and 38 clipped diagonal strips. The compact
replacement is intentionally review-only and preserves all foreground artwork.

The reconstruction target is **three gradients total**:

- one fitted gray-disc linear gradient replacing the grayscale strip/mask construction,
- one accent base gradient using the recovered historical coordinates
  `x1=21.46 y1=26.37 x2=61.60 y2=56.47`, and
- one differently angled transparent accent highlight gradient.

The accent colors are recovered from the dominant resolved source palette; Guijia resolves to
`#ffb669 -> #ff6b00`. The highlight uses the pale source stop (`#ffb669` for Guijia) fading to
transparent. On a 1024 px foreground-free render of the actual raw Guijia source, the recovered
base gradient alone measures about 3.916 RGB RMSE inside the accent disc; the second gradient
reduces that to **3.389 RGB RMSE**, reproducing the earlier ~3.38 two-gradient experiment.

The fitted gray disc uses `#d9dcde -> #ffffff` at approximately -82.8 degrees. This deliberately
smooths the original banded/flattened export rather than reproducing the thin stripe boundaries.
The outer flat badge circle and all gear/text/central-mark foreground geometry are retained.

Unused Illustrator class rules and unreachable masks, filters, clip paths, raster images, and
legacy gradients are pruned after reconstruction. Optional Scour remains a final serialization
stage. Automatic acceptance remains disabled.

```powershell
python .\gradient_mask_reconstruct.py `
  "C:\path\to\guijia-squadrons-2-1.svg" `
  --scour `
  --inkscape "C:\path\to\inkscape.com" `
  --output-dir .\guijia-gradient-mask
```

Blue Wolf, Guijia, and Longwang are byte-identical in the audited raw snapshot, so one successful
Guijia run validates that three-file source-hash family. Scarface/Triphammers,
Maghariba/Shakush, Mechazoid/O-Yoroi, Gecko, and Juggernauts remain separate source hashes and
must be validated independently before the fitted reconstruction parameters are generalized.

## v8.9.1 raw polygon compatibility

The scaffold matcher accepts `path`, `polygon`, and `rect` stripe geometry, covering both raw
Corvus Belli Illustrator exports and processed/Scoured equivalents.

## v8.9.2 relationship-based scaffold matching

The raw scaffold is not assumed to be six consecutive direct children. Matching uses clip/mask
references, concentric radii, the >=20-circle multiply stack, the separately drawn inner disc,
and the clipped stripe fields. Unrelated wrapper/intervening groups are preserved. `--diagnose`
prints the structural evidence used by the matcher.

## v8.9.3 CSS property resolution and corrected fidelity target

Raw Corvus Belli files encode `clip-path`, `mask`, and `mix-blend-mode` through generated CSS
classes. v8.9.3 resolves those class rules before structural matching; this fixes the false
negative where diagnostics previously reported empty multiply/masked/clipped group lists despite
the correct geometry being present.

The reconstruction target is also corrected from the earlier mistaken one-gradient interpretation.
The fidelity-first target is one gray gradient plus **two accent gradients at different angles**.
The second accent gradient is a small structural increase relative to the original 40+ flattened
accent layers and is retained because it measurably improves fidelity.


## v8.9.4 cross-family batch validation

The reconstruction code now uses neutral **accent** terminology. Accent colors are always recovered
from the source SVG's dominant resolved two-stop gradient palette instead of assuming Guijia orange.
This allows the same structural experiment to be tested against families such as Scarface/Triphammers,
whose current published copy uses `#7fd4c1 -> #39a572`, without changing the reconstruction code.

`gradient_mask_batch.py` reads an existing scan JSON, selects only
`flattened-gradient-mask` files, groups exact duplicates by SHA-256, verifies the raw files still
match that scan, and runs one representative per unique byte stream. It writes per-case manifests
plus consolidated `batch-report.json` and `batch-report.csv`. Failed structural matches are recorded
as rejected cases rather than stopping the rest of the experiment.

```powershell
python .\gradient_mask_batch.py `
  "C:\Users\Franky\Documents\GitHub\InfinityDB\data\raw\symbols\SYMBOLS 20260929-114338" `
  .\scan-v8.6.json `
  --scour `
  --output-dir .\gradient-mask-v8.9.4
```

The audited v8.6 report contains 11 semantic `flattened-gradient-mask` files but only six unique
source hashes, so a complete batch requires six reconstruction/render runs rather than eleven.
Automatic acceptance remains disabled; the batch report is a research comparison surface, not an
optimizer approval mechanism.
