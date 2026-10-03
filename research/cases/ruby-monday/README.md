# Kazuraba Ruby Monday

Status: **candidate validated**

Classification: `flattened-blend-stack`

Path: `units/kazuraba-ruby-monday-1-1.svg`

## Diagnosis

The source is 1,875,476 bytes with 1,380 paths, 1,383 linear gradients, and repeated translated blend
stacks. Most gradients belong to a handful of repeated palette families. The generated blend members are
structurally reusable rather than independent artwork.

The six confirmed stacks are three 35-step RUBY stacks and three 53-step Monday stacks. Follow-up
analysis of the raw source found that their expanded steps are not mathematically exact translations:
Illustrator independently rounded path coordinates, producing normalized geometry and per-glyph anchor
differences of up to 0.01 SVG units. Reproducing those tiny variations would preserve exporter
quantization rather than recover the underlying blend construction.

Close visual review also identified two details that needed to be separated from that quantization. First,
the RUBY front face deliberately carries a named Illustrator `6 lpi 10%` pattern at 14% opacity with
`mix-blend-mode: overlay`; the subtle horizontal stripes are therefore present in the raw Army source and
are not introduced by the reconstruction. Monday has no equivalent pattern overlay. Second, the original
first-step reconstruction used the back of each extrusion as its reusable geometry master. Because of the
per-step coordinate rounding, that moved the more visually important front bevel boundary.

## Reconstruction

`blend_use_reconstruct.py` replaces qualifying translated stack members with a canonical group plus
`<use>` clones and prunes definitions made unreachable by the rewrite.

The canonical group is now selected by resolved paint translation: the stack member whose gradient
translation is closest to `(0, 0)` becomes the master. All six Ruby Monday stacks select their final/front
member (`34` for RUBY and `52` for Monday), each with an identity paint translation. This preserves the
authored front boundary exactly and reconstructs the extrusion away from it rather than reconstructing
toward it from the rounded back endpoint.

At 1600 px this changes the source/candidate result from 2.860819 to **0.525454 RGBA RMSE**, reduces the
changed-pixel fraction from 1.5376% to **0.5602%**, and retains zero alpha error. In a crop around RUBY,
RMSE falls from about 7.14 to **1.34**. The remaining disagreement is small edge quantization inside the
expanded blend rather than a missing paint layer.

The compact serialization continues to use SVG2 `href` and `<use x/y>` for pure translations. Preserving
the canonical front endpoint retains more distinct source gradient definitions than the previous
back-endpoint master, so the candidate is 99,377 bytes rather than 96,769 bytes. The approximately 2.6 KB
cost is accepted because it materially improves fidelity while still reducing the raw source by about
94.7%.

The forward `<use>` references created when the canonical member is the last stack child render correctly
in Inkscape 1.4 and Chromium 144. Standard Scour 0.38.2 remains unsafe for this candidate because it
collapses visually significant inherited gradients.

A final seam review found that the darkest RUBY and Monday stacks paint their zero-translation endpoint
under an exactly coincident opaque face. Rasterizers anti-alias both edges independently, producing a
visible shared-edge fringe even though the darker endpoint is fully hidden. The preferred fix does not
alter authored path geometry: when a later sibling is provably an exact, fully opaque occluder, the
canonical endpoint is retained inside a local `<defs>` node as the `<use>` master but is no longer painted
itself. Only two of Ruby Monday's six stacks meet that conservative condition.

Manual visual review preferred this endpoint-suppressed result over both the coincident-edge candidate and
a broader clipping experiment. The final candidate is 99,403 bytes (94.70% smaller than the raw source).
Its raw-source RMSE is intentionally slightly higher than the coincident-edge candidate because the raw
source itself contains the rejected double-antialiasing seam; alpha remains identical.

See `research/reports/ruby-monday-20261003-summary.json` for the source-paint evidence, endpoint-selection,
seam-suppression decision, and multi-resolution render metrics.

The candidate is visually validated but remains representative rather than pixel-exact.
