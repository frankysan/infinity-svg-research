# Vyo-first SVG workflow

Use Vyo as a candidate geometry base, with current Army artwork as first-party design evidence.
Vyo remains a second-party fan-vector source. A reviewed identity does not approve its geometry,
palette, typography, or publication. Preserve the existing Anyat v10/v10.1 research decision.

## Identity and actions

`tools/vyo_identity.py` joins the Vyo inventory, Army acquisition manifest, and InfinityDB publication
manifest. Each row represents one canonical published emblem and retains all authoritative source
paths, hashes, unit IDs, unit slugs, and profile names. Resume/audit references do not establish
current coverage. Exact source hashes can connect names; different profile emblems remain separate.

Name matching, spelling rules, and sectorial routing propose candidates. Explicit visual decisions
live in `research/vyo-identity-decisions.json`. Reviewed decisions name canonical Army profile paths
and source hashes so a different profile or changed input cannot silently inherit a review.

- `reuse`: a structurally usable base with the corresponding device/composition; final fidelity review remains.
- `minor-cleanup`: a usable base needing identified palette, lettering, boundary, variant, or dependency work.
- `reconstruct`: an unusable base or an obsolete device that differs from the current design.

Unreviewed structural actions are provisional. A gradient is a review signal, not an instruction to
flatten it. A transform alone is not a defect. Do not automatically select a newest, smallest, or
matching-name file when the archive has multiple designs.

`missing-vyo.json` contains only explicit, profile-scoped confirmed-absence decisions.
`unresolved-vyo.json` contains the remaining identity work. A name gap is not an absence decision.
`reconstruction-queue.json` includes reviewed defects/redesigns as well as confirmed absences,
unless a documented usable current-Army fallback supplies the geometry.

```powershell
rtk proxy python tools/vyo_identity.py research/vyo-full-inventory-v1.json `
  "C:\path\to\army-symbol-build.json" "C:\path\to\symbol-publication.json" `
  --decisions research/vyo-identity-decisions.json --output output/vyo-identity-v1
```

## Viewports

`tools/viewport_normalize.py` queries each drawing's bounds with Inkscape, converts the returned
CSS pixels through the original physical size/viewBox mapping, and changes only the root `width`,
`height`, and `viewBox` attributes. Styles, path data, transforms, gradients, and other content remain
unchanged. This handles the `(0,11000)`, `(3937,7063)`, and `(10000,17940)` conventions without a
universal Morat rectangle. Non-circular artwork keeps its drawing aspect ratio.

The output width defaults to 100 unitless units; height follows the derived aspect ratio. The
viewBox includes 0.5% padding plus an outward allowance for Inkscape query rounding. These are
candidate framing choices, not a recovered authorial badge margin or an InfinityDB publication size.

Font-dependent text, external references, percentages that depend on the viewport, and other
unsupported viewport dependencies are held back. Resolve fonts and use InfinityDB's existing
publication outlining stage before retrying text-bearing sources. Do not create a second outlining
pipeline here.

```powershell
rtk proxy python tools/viewport_normalize.py "input/svg/Vyo SVG Vectors" output/vyo-viewport-v1 `
  --inkscape "C:\Program Files\Inkscape\bin\inkscape.com"
rtk proxy python tools/viewport_validate.py output/vyo-viewport-v1/report.json `
  --inkscape "C:\Program Files\Inkscape\bin\inkscape.com" --size 128
```

Normalization requires a separate, empty output directory and preserves the originals. Validation
checks source/candidate hashes, compares drawing-area renders, and renders the normalized page for
framing inspection. The original page is often clipped, so comparing original-page and normalized-page
pixels would test different crops. Drawing-render equality establishes unchanged appearance at the
tested size; it does not establish Vyo-to-Army fidelity or publication readiness. At small sizes,
antialiasing can touch the padded page edge without the drawing bounds exceeding the viewport.

## First reviewed findings — 2026-10-01

The current run covers 808 canonical assets: 740 unit emblems, 59 faction emblems serving 60 faction
mappings, and 9 static assets outside this study. It records 15 reviewed identities, 435 name/alias
candidates, and 349 unresolved identities. There are no confirmed-absence decisions yet; coverage
remains incomplete.

Six historical archive-name gaps have usable source bases: Bipandra and Konstantinos use Indigo;
Isobel uses Intel; Zamira uses Kum; Kusanagi uses Moiras; Neema uses Ectros. Bipandra needs its green
palette and lower lettering; Isobel needs different upper Cyrillic lettering. Aelis shares Hatail
construction but has a dark lower central region where Vyo uses orange.

Armand has two archive versions. The 2015 N3 source references a PNG; the 2018 NA2 version is all
vector and supplies the same skull/ring/composition as Army. Prefer that base and review the upper
lettering instead of reconstructing the whole emblem because of the older file's defect.

Noctifier/Noctifers is a real design mismatch: the Vyo rounded stacked glyph differs from current
Army's angular device. Its Vyo base has a `reconstruct` action and `reviewed-design-mismatch` status;
it is not counted as an identity absence. All 65 Combined Army archive drawings were inspected for
a matching current device. The current 14,310-byte Army source has no scanner findings, so the
recorded fallback is to reuse/review that vector. This mismatch alone does not justify a new redraw.

Scarface/Cordelia profile 1 maps to the N3 Scarface badge and profile 3 to the N3 Cordelia badge.
Profile 2 is the separate Turtlemen TAG badge shared with Triphammers and remains unresolved.
The combined unit name must not collapse these three logos into one composition decision.

The viewport batch produced 544 candidates from 565 files. It held back 20 font-dependent SVGs and
the older Armand external-image source. All 544 drawing-area render pairs were pixel-identical at
128 px with Inkscape 1.4.4; no candidates have been promoted to publication.

Full run data and render sheets are generated under ignored `output/` directories. Compact durable
results are in `research/reports/vyo-workflow-v1-summary.json`. Reconstruct confirmed current-design
defects and reviewed absences; continue identity review before treating unresolved rows as missing.
