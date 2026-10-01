# Research log

This file records recovered research history that predates the Git repository. It is intentionally a
summary of known evidence, not a synthetic commit history.

## Vyo-first continuation — 2026-10-01

Implemented the identity, action, viewport, and missing-list workflow proposed in the supplied ChatGPT
continuation context. The 808-emblem Army publication manifest now has a reproducible identity ledger
with preserved profile references and 15 reviewed identities. Six historical archive-name gaps resolve
to shared or adaptable emblem bases; Armand's newer NA2 vector avoids the older N3 image dependency.
Noctifier/Noctifers has a current-design mismatch, and Scarface/Cordelia retains three separate profiles.

The viewport batch derived bounds independently for each source rather than applying one Morat
rectangle. It produced 544 metadata-only candidates and held back 20 text-dependent files plus the
older Armand image reference. All 544 original/candidate drawing-area renders were pixel-identical at
128 px. The ledger still has 349 unresolved identities and no confirmed-absence decisions; neither
these candidates nor the reviewed bases have been approved for publication. See
[`vyo-workflow.md`](vyo-workflow.md) and the compact Vyo workflow report for source hashes and details.

## Corpus baseline — scanner v8.6

Snapshot: `SYMBOLS 20260929-114338`.

- 1,101 SVG files scanned.
- 81 files flagged by at least one hard classification or advisory.
- 0 parse errors.
- 212 exact duplicate groups.
- Hard classes: 1 duplicate-fill/stroke, 2 embedded-raster-heavy, 1 flattened blend stack,
  11 flattened-gradient-mask semantic files, 2 micro-contour-explosion semantic files,
  1 off-artboard-content, and 6 palette-fragmented-trace.
- Advisories: 1 large-path-payload, 3 missing-external-image, 28 palette-fragmentation,
  and 28 subpixel-detail-heavy.

## Trinitarians — duplicate fill/stroke

`units/trinitarians-1-1.svg` contains 47 exact fill/stroke geometry pairs and roughly 30.6 KB duplicated
path data. The conservative merge was pixel-identical in the research experiment and became an exact
transform gated by the scanner thresholds.

Status: **resolved**.

## Kazuraba Ruby Monday — flattened blend stack

Source size: 1,875,476 bytes. The source contains 1,383 linear gradients and multiple long translated
blend stacks. Replacing generated stack members with reusable `<use>` geometry reduced the experiment to
roughly 100 KB while retaining close rendering. The generalized transformer measured about 2.86/255 RGBA
RMSE at 1600 px in the recovered run.

Status: **validated**; still review-required because it is not pixel-exact.

## Wolfgang Amadeus Wolff — micro-contour explosion

The two semantic filenames are exact duplicates. The source contains about 19,140 closed subpaths, most
of them tiny contours. The recovered preferred pipeline:

1. prune closed contours with span <= 0.1 SVG units;
2. simplify the 41 affected distressed-lettering paths exactly once with Inkscape `path-simplify`;
3. run Scour;
4. render-validate.

Actual raw-source validation reduced 1,175,564 to 233,209 bytes (80.16%). It removed 13,795 closed
contours and measured 4.652896/255 RGBA RMSE at 1200 px with unchanged alpha. At 1200 px there were zero
changed pixels inside radius 480 px; the differences were confined to distressed outer lettering. The
hard classifier no longer triggered, leaving only the expected `subpixel-detail-heavy` advisory.

Pathology status: **resolved**.

### Wolfgang typography reconstruction follow-up

The resolved micro-contour transform is intentionally narrower than a full authorial reconstruction of
the lettering. Its validation showed that the changed pixels were confined to the distressed outer text,
which raises a separate hypothesis: much of the remaining outline complexity may represent traced or
expanded typography rather than deliberately hand-shaped contours.

Wolfgang is therefore an active typography research subject. The next investigation should recover the
literal text and layout, identify the underlying font family, check for an existing distressed/grunge
variant, and otherwise test clean semantic text with deliberate distress reconstructed separately. The
research representation may retain `<text>` elements; publication outlining must continue to use the
existing InfinityDB symbol pipeline rather than a duplicate implementation in this repository.

Typography reconstruction status: **active research**.

## Morat geometric reconstruction

The project-authored redraw began as a methodology reference rather than provenance evidence. Source
analysis subsequently recovered the internal ribbons as a compact circular system: a common nominal
`5.67` ribbon width, shared circle families, source-supported intersections, derived red/negative regions,
and a local G1-continuous two-circle transition where the source departs briefly from the main path5
circle before converging back onto it. A whole-ribbon ellipse was tested and rejected because it damaged
otherwise-supported downstream geometry.

The final representation is intentionally split. **v9 is the geometric research master**, preserving the
primitive construction for inspection. **v10 is the cleaned publication candidate**, keeping the v9
geometry fixed while boolean-unioning contiguous white regions and removing four non-authorial junction
micro-holes. The v10 cleanup improves the affected local source comparison even though full-image raw
RMSE rises slightly from antialiasing differences introduced by stroke-to-filled-region conversion.

The retained source-fitted path7 start is accepted: previously tested exact-intersection/cardinal-top
normalizations were visually and numerically worse. Further geometry work is gated on a specific visual
defect or materially stronger first-party evidence rather than continued global fitting.

Status: **resolved reconstruction**.

### Morat publication-topology follow-up

Manual review of the faction symbol and six reconstructed unit symbols found a recurring problem that
circle recovery alone does not solve: path intersections can become blobs, adjacent color regions can
leave visible gaps, and exporter-era positive/negative paths can remain almost identical overlays.

The preferred Morat publication model now follows the manually refined faction emblem: retain a separate
geometric master, derive clean canonical intersections and foreground boundary ownership, and place
oversized flat-color underlays behind those cutouts. Anyat, Daturazi, Suryats, Rodok, Zerat, and Yaogat
should receive a new publication-topology pass using this model while preserving their evidence-supported
geometric masters.

This conclusion is deliberately limited to the Morat family. It is not assumed to describe unrelated
Infinity symbol families.

Treitak Anyat is the current restored-intent reference case. The reconstruction work established the
stronger family invariant that intended corners are sharp single-vertex intersections and visible curves
are smooth and contiguous everywhere between those corners. Tiny exporter-rounding arcs, bridge
segments, drifted endpoints, and curvature bumps are not retained merely because they improve agreement
with damaged exporter pixels.

The current Anyat reference is **v10 geometric / v10.1 publication**. Its final large-red cleanup replaces
the remaining exporter-style segmentation with two clean spans: one uninterrupted smooth white-cut edge
to the top sharp corner, and one smooth lower edge without an internal non-smooth vertex. The small-red
lower edge is likewise a single smooth circular span. Publication colors remain oversized underlays
behind canonical foreground cuts.

Status: **active Morat-family publication-topology migration; Anyat reference established**.

## Flattened gradient/mask badge family

Eleven semantic files collapse to six unique SHA-256 streams. The recovered minimal model uses three
linear gradients: one for the gray outer disc/annulus and two differently angled gradients for the accent
inner disc. The second accent gradient is retained because fidelity is the priority and the structural
cost is negligible compared with the original 40+ layer scaffold.

The v8.9.4 batch successfully reconstructed all six unique streams, removed masks/filters/embedded raster
payloads and the hard classification, and reduced each source by roughly 97.5–98.9%. Fidelity varies by
family. Current investigation indicates that most remaining error is concentrated at the inner-disc
boundary created by the original stack of slightly offset multiply circles; the interiors are already
close. Reintroducing the original circular clip paths did not improve fidelity.

Status: **experimental / validated batch**, not yet resolved.

### Guijia inner-field decomposition

Follow-up analysis separated the accent disc into the 44-circle multiply edge stack, a nearly redundant
base circle, and the 38-element clipped interior field. Removing only the base circle while leaving the
38-element field changes the 1024 px full render by only 0.424 RGBA RMSE; removing the multiply stack
changes only about 0.26% of pixels but produces large local edge differences.

The interior field is genuinely two-dimensional. Replacing only that field while preserving the original
edge stack improved from 1.4293 RGBA RMSE for the previous two-linear model to 0.7010 for an experimental
one-linear plus two-radial-highlight model at 1600 px. Blurring away the exported strip boundaries keeps
roughly the same twofold advantage, so the improvement is not dependent on reproducing the flattening
artifacts. The production transformer remains unchanged pending tests on the other five unique source
families.

### Guijia edge and gray decomposition

The 44-circle accent boundary was subsequently identified as an expanded 22-position blend/sweep. The
parent group is multiplied with the backdrop once; the repeated opaque circles mainly create a narrow
directional rim. A single fitted circle approximates that effect at 0.9110 RGBA RMSE at 1600 px, while
one circle retained from each source blend position gives 0.2788.

The gray field is 44 nearly uniform bands aligned at about -83.03 degrees with a monotonic
`#ffffff`-to-`#dbdddf` palette, strongly supporting one intended linear gradient. Its separate embedded
mask is a blurred offset circle used to create a subtle directional inner-edge shadow. A structural
linear gradient plus a three-stop radial-opacity shadow gives 1.2300 RGBA RMSE for the gray reconstruction
at 1600 px.

Combining those results with the improved accent interior yields a 7,582-byte Scoured Guijia candidate
with 1.6792 full-image RGBA RMSE at 1600 px, zero alpha error, and no scanner findings. This is the new
Guijia-only experimental baseline; it has not yet been generalized into the production transform.


### Cross-family decomposed-model experiment

Comparison of the six current published badge SVGs found a common exporter scaffold: 83 gradients,
3 masks, 3 filters, 2 clip paths, 3 embedded images, and the same inner-circle geometry sequence. Five
families use the same gradient coordinate serialization; Scarface differs only by one mathematically
equivalent transform spelling. Accent palettes differ as expected.

The authoritative raw-source batch completed successfully for all six unique SHA-256 groups with
gray-shadow fitting enabled. It recorded 6 successful groups, 0 rejects, 0 missing/hash-mismatch groups,
and no candidate scanner classifications, advisories, or signals. Candidate sizes ranged from 6,893 to
13,784 bytes. At 1600 px, RGBA RMSE measured 1.6215 (Guijia/Blue Wolf/Longwang), 1.8124 (Gecko),
2.0408 (Juggernauts), 1.6592 (Maghariba/Shakush), 1.8192 (Mechazoid/O-Yoroi), and 1.6178
(Scarface/Triphammers). Gecko alone selected the fitted-strong gray shadow; the other five used the
shared-weak shadow.

The shared-shell renderer handled the complete fit+validation run with exactly two Inkscape process
startups: one shell for all six source/no-shadow fit pairs and one for all six final validation pairs.

The mask placement metadata is shared, but the embedded PNG native widths vary between families while
the heights stay fixed. This makes exact mask-strength differences provenance-sensitive: they are
first-party evidence of the current export, but may reflect raster cropping/export variance rather than
authorial intent. All fitted results therefore remain review-required.

### Concentric geometry decision

Follow-up review changed the interpretation of the thin accent rim. The explicit source base circle and
inner clip are perfectly concentric at `(41.1, 41.1)` with `r=24.69`; the gray circle is likewise centered
at `(41.1, 41.1)` with `r=32.02`. Only the expanded 44-circle exporter stack wanders slightly.

The representative model therefore removes the fitted offset rim and preserves the exact concentric
circle geometry. Shading gradients may have offset focal points, but they must not alter the principal
silhouettes. This intentionally worsens full-image RMSE against the pathological raw source because the
source pixels include the swept edge artifact. Excluding only a +/-0.25 SVG-unit band around the inner
circle boundary leaves about 1.25--1.38 RGBA RMSE at 1600 px across all six families, showing that the
remaining disagreement is overwhelmingly localized to the rejected exporter edge.

The concentric model still requires a new end-to-end six-family batch run. Validation should report both
normal full-image metrics and an edge-excluded representative-fidelity metric so the known exporter rim
does not pull the reconstructed geometry away from the stronger explicit circle evidence.

## Palette-fragmented traces

Six hard-classified cases were identified. Palette snapping can produce low colour error but does not
repair the fragmented geometry, so recolouring alone is not considered a solution. Source-render-guided
boundary reconstruction exists as an experiment; historical/second-party rasters are guardrails only.

Status: **identified / deferred**.

## Embedded-raster-heavy cases

Druze and Taowu are the two hard-classified cases. Druze's embedded PNGs appear effectively
monochrome-alpha and several resemble disc/ring primitives, suggesting a possible vector reconstruction.
Taowu requires more inspection before any equivalent assumption is made.

Status: **identified**.

## Missing external images

Blackjacks: the missing JPEG was shown to be fully covered by vector artwork; removing the missing
reference produced zero rendered pixel change. Kaeltar Specialists still requires case-specific testing.

Status: mixed; track per source.
