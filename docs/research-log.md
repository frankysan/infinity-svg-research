# Research log

This file records recovered research history that predates the Git repository. It is intentionally a
summary of known evidence, not a synthetic commit history.

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

Status: **resolved**.

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
