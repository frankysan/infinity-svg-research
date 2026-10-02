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


## Local visual reviewer

`tools/vyo_review.py` provides a localhost-only review queue for the identity ledger. It renders Army
and Vyo sources through Inkscape drawing bounds into cached square PNGs so historical page metadata
does not affect side-by-side, overlay, or blink comparisons. Review writes remain profile-scoped and
update `research/vyo-identity-decisions.json`; the normal identity outputs are regenerated only after
the proposed decision passes the existing hash/provenance validation.

```powershell
python tools/vyo_review.py research/vyo-full-inventory-v1.json `
  "C:\path\to\army-symbol-build.json" "C:\path\to\symbol-publication.json" `
  --decisions research/vyo-identity-decisions.json `
  --army-root "C:\path\to\Army SVG sources" `
  --vyo-root "C:\path\to\Vyo SVG Vectors" `
  --output output/vyo-review `
  --inkscape "C:\Program Files\Inkscape\bin\inkscape.com"
```

The interface supports queue search/filtering, multiple candidate selection, side-by-side, opacity
overlay, and blink comparison. `reuse`, `minor-cleanup`, and design-mismatch decisions require an
evidence note; cleanup/mismatch also require explicit reasons. Confirmed absence is deliberately
guarded by a separate confirmation and cannot select a Vyo source. Subject-scoped alias rules remain
read-only hints in the reviewer: only exact Army profile review rules are created or replaced.

## Viewports

`tools/viewport_normalize.py` queries each drawing's bounds with Inkscape, converts the returned
CSS pixels through the original physical size/viewBox mapping, removes the root `width` and `height`,
and sets `viewBox` and `preserveAspectRatio="xMidYMid meet"`. Styles, path data, transforms, gradients, and other content remain
unchanged. This handles the `(0,11000)`, `(3937,7063)`, and `(10000,17940)` conventions without a
universal Morat rectangle. Non-circular artwork keeps its drawing aspect ratio.

The output has no fixed display size. Its viewBox provides the intrinsic aspect ratio; the consuming
page or app supplies the display dimensions. Proportional fitting keeps the whole drawing visible
when the container has a different shape, with space around it rather than stretching or cropping.
These behaviors follow the SVG [viewBox](https://developer.mozilla.org/en-US/docs/Web/SVG/Reference/Attribute/viewBox)
and [preserveAspectRatio](https://developer.mozilla.org/en-US/docs/Web/SVG/Reference/Attribute/preserveAspectRatio) rules.
The viewBox includes 0.5% padding plus an outward allowance for Inkscape query rounding. These are
candidate framing choices, not a recovered authorial badge margin or an InfinityDB publication size.

Font-dependent text, external references, percentages that depend on the viewport, and other
unsupported viewport dependencies are held back. Resolve fonts and use InfinityDB's existing
publication outlining stage before retrying text-bearing sources. Do not create a second outlining
pipeline here.

```powershell
rtk proxy python tools/viewport_normalize.py "input/svg/Vyo SVG Vectors" output/vyo-viewport-v2 `
  --inkscape "C:\Program Files\Inkscape\bin\inkscape.com"
rtk proxy python tools/viewport_validate.py output/vyo-viewport-v2/report.json `
  --inkscape "C:\Program Files\Inkscape\bin\inkscape.com" --size 128
```

Normalization requires a separate, empty output directory and preserves the originals. Validation
checks source/candidate hashes, compares drawing-area renders, and renders the normalized page for
framing inspection. The original page is often clipped, so comparing original-page and normalized-page
pixels would test different crops. Drawing-render equality establishes unchanged appearance at the
tested size; it does not establish Vyo-to-Army fidelity or publication readiness. At small sizes,
antialiasing can touch the padded page edge without the drawing bounds exceeding the viewport.

For images in a responsive page, let CSS supply the width and keep height automatic:

```html
<img class="emblem" src="symbols/emblem.svg" alt="Unit emblem">
<style>
  .emblem { display: block; width: 100%; height: auto; }
</style>
```

For an inline SVG in a slot with both dimensions specified, set its CSS width and height to fill the
slot. `xMidYMid meet` scales the drawing uniformly and centers it. Root size removal leaves child
shape sizes unchanged so strokes, paths, and other artwork continue to scale together.

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

## Responsive sizing continuation — v2

The first batch used a fixed unitless width of 100. The v2 batch removes both root size attributes
from all 544 candidates and explicitly preserves proportional fitting. The derived viewBoxes are
identical to v1. The normalizer no longer accepts `--width`; render output sizes belong to the
renderer or consuming page.

All 544 original/candidate drawing render pairs match at 128 px. Six varied samples also match at
512 px. Headless Chrome passed 48 layout checks: image widths of 32, 128, and 512 px with automatic
height, and inline SVGs in square, wide, and tall containers. Those checks cover intrinsic ratios,
uniform scaling, centering, and drawing bounds inside the container. The same 21 dependency cases
remain held back. See `research/reports/vyo-responsive-sizing-v2-summary.json` and
`final/vyo-workflow-v2.zip` for this continuation.
