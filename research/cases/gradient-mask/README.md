# Flattened gradient/mask badge family

Status: **experimental / validated batch**

Classification: `flattened-gradient-mask`

## Family structure

Scanner v8.6 identified 11 semantic files which collapse to six unique byte streams. Typical sources use
83 linear-gradient definitions backed by one two-stop palette, 3 raster masks, 3 filters, 2 clip paths,
roughly 44 multiply circles, and dozens of flattened strips.

The current production experiment uses one fitted linear gradient for the gray outer disc/annulus and
two linear gradients for the accent inner disc. That model is deliberately still provisional.

A Guijia-specific decomposition performed after the v8.9.4 batch showed that the source accent disc is
not well described as merely two overlapping linear gradients. Its source structure has three distinct
roles:

1. a 44-circle multiply stack whose visible contribution is concentrated at the disc boundary;
2. a nominal base accent circle that is almost completely covered by later artwork;
3. a clipped 38-element field (26 polygons plus 12 rotated rectangles) that carries almost all interior
   shading.

The 38-element field reuses the same two accent colours but varies gradient extent across diagonal
strips, producing a genuinely two-dimensional smooth field plus visible exporter banding.

## v8.9.4 batch result

All six unique SHA groups reconstructed successfully and cleared the hard pathology. Candidate sizes are
roughly 5.6–12.5 KB from ~499–506 KB sources (97.5–98.9% reduction). Alpha remained unchanged in the
reported largest renders.

The v8.9.4 model still clears the pathology for all six families, but the Guijia decomposition changes
the interpretation of the remaining work. The boundary stack is a separate problem, while the interior
field itself can also be represented more faithfully.

For Guijia, replacing only the source base circle and 38-element field while retaining the original edge
stack gives these 1600 px full-image results:

- previous two-linear accent model: RGBA RMSE 1.4293, RGB RMSE 1.6504;
- experimental one-linear + two-radial-highlight model: RGBA RMSE 0.7010, RGB RMSE 0.8094.

The new model also remains roughly twice as close after progressively blurring away the source strip
boundaries, which supports the interpretation that it better represents the underlying intended smooth
shading rather than simply fitting exporter banding. This result is not yet promoted into the production
transform: it must first be tested against the other five unique source families.

### Guijia boundary-blend decomposition

The 44-circle structure is not 44 independent shading layers. The circles occur as 22 geometry/gradient
pairs whose centers walk from `(41.27, 41.06)` to `(41.21, 41.11)` at radius `24.69`. The
`mix-blend-mode:multiply` property belongs to their common parent, so the assembled group is composited
with the backdrop once; the opaque circles inside the group mainly form a very narrow swept accent rim.

At 1600 px, removing the whole group changes only about 0.21% of pixels but gives 4.7805 RGBA RMSE
because the affected rim pixels are high contrast. Keeping one circle from each of the 22 blend positions
reduces that to 0.2788 RMSE. Decimating the sweep gives 0.8480 RMSE at six circles and 1.0960 at three
circles. A single fitted, slightly offset/enlarged circle reaches 0.9110 RMSE.

This supports treating the source as an expanded blend/sweep rather than preserving the individual
circles. A one-primitive rim model is therefore the current minimal hypothesis, but it remains
Guijia-specific until the same geometry is checked on the other source families.

### Guijia gray-field decomposition

The gray `r=32.02` field is structurally simpler than the original export suggests. Its dominant layer is
44 flat strips: 34 polygons plus 10 rotated rectangles. The regular rectangles are 1.43 units wide and
rotated `-83.03` degrees, while the palette progresses almost linearly from `#ffffff` to `#dbdddf`. This
is consistent with a single linear gradient flattened into bands.

The separate raster-mask branch is not part of that gradient. It contains a first-party 2181x2173 PNG
representing a blurred offset circle, inverted by an `feColorMatrix`, and applied to a `#040505` circle at
0.75 opacity. Its visible contribution is a narrow directional inner-edge shadow. Removing the gray
strips produces 30.4109 RGBA RMSE at 1600 px; removing only the masked circle produces 0.6369.

Reconstructing the bands from their own direction/end colours gives 1.2748 RGBA RMSE. Adding one
source-derived three-stop radial-opacity shadow lowers that to 1.2300 and reduces the maximum channel
difference from 55 to 48. The same model remains better after progressively blurring away the source
banding, supporting it as a closer representation of the underlying smooth artwork.

### Combined Guijia reconstruction

Combining the experimental accent interior, one-primitive accent rim, structural gray gradient, and
radial gray edge shadow produces a 7,582-byte Scoured SVG from the 505,086-byte source (98.50%
reduction). The candidate contains 3 linear gradients, 3 radial gradients, 6 circles, 0 masks, 0 filters,
0 clip paths, and 0 images; the scanner reports no classification or advisory.

At 1600 px the full-image RGBA RMSE is 1.6792, compared with 5.0752 for the previous compact Guijia
experiment. At 1024 px it is 1.8036. Alpha RMSE remains zero at every validation size. The larger
changed-pixel fraction is expected because smooth gradients deliberately replace the source's visible
flattening bands.

This was the preferred **Guijia-only experimental baseline** before cross-family generalization. The
legacy three-gradient reconstruction remains available unchanged for comparison.

### Cross-family decomposed model

Structural comparison of the six current InfinityDB-published badge families found the same 83-gradient
scaffold, the same 46-circle inner-stack geometry, and effectively the same gradient-coordinate sequence.
The family differences are primarily the two-stop accent palette and foreground artwork.

The authoritative end-to-end raw batch completed successfully for all six unique SHA groups with
gray-shadow fitting enabled. It produced 6 successful groups, no rejects/missing/hash mismatches, and no
scanner classifications, advisories, or signals in any candidate. The shared renderer used exactly two
Inkscape processes for the complete run: one fit shell and one validation shell.

At 1600 px, the decomposed-rim model measured:

- Guijia / Blue Wolf / Longwang: RGBA RMSE 1.6215, shared-weak gray shadow;
- Gecko: 1.8124, fitted-strong gray shadow;
- Juggernauts: 2.0408, shared-weak gray shadow;
- Maghariba / Shakush: 1.6592, shared-weak gray shadow;
- Mechazoid / O-Yoroi: 1.8192, shared-weak gray shadow;
- Scarface / Triphammers: 1.6178, shared-weak gray shadow.

Candidate sizes ranged from 6,893 to 13,784 bytes. These results validate the decomposed shading model
across the raw family set, but do not by themselves establish that every raw edge pixel is authorial.

The three embedded mask images use the same SVG placement across all six families, but their native PNG
widths vary while their heights remain fixed. Gecko's stronger fitted gray crescent therefore remains a
provenance question: it is first-party evidence of the current export, but may partly reflect raster
cropping/export variance. No fitted shadow is automatically accepted as authorial intent.

### Concentric geometry decision

Subsequent review changed the interpretation of the thin accent rim. The explicit source base circle and
inner clip are perfectly concentric at `(41.1, 41.1)` with `r=24.69`; the outer gray circle is likewise
centered at `(41.1, 41.1)` with `r=32.02`. Only the expanded 44-circle exporter stack wanders slightly.

The preferred representative construction therefore removes the fitted offset rim entirely. Shading may
remain asymmetric through gradient focal points, but all accent shading circles must share the exact
inner-circle geometry and all gray shading must preserve the exact outer-circle silhouette. This reduces
the purposeful construction from six gradients/circles to five when the default gray shadow is present.

Raw full-image RMSE becomes worse after removing the rim because the source render contains that swept
edge artifact. The disagreement is highly localized: at 1600 px, excluding only a `+/-0.25` SVG-unit
band around `r=24.69` gives RGBA RMSE of roughly 1.25--1.38 across all six unique families. The project
therefore treats the centered circles as stronger geometry evidence than the expanded-stack boundary.

Earlier capsule, endpoint-circle, and single-resolution rim-fitting experiments remain useful negative
evidence. They either performed worse than the compact fitted rim or overfit one raster size while
degrading the rest of the validation set. The rim is no longer part of the preferred representative
model.

Next questions:

1. run the concentric model end-to-end against all six unique raw source hashes;
2. add an edge-excluded representative-fidelity metric alongside normal full-image comparison;
3. visually review the normalized concentric candidates at vector/native and normal UI sizes;
4. seek independent first-party appearance evidence for Gecko's unusually strong gray crescent;
5. then decide whether the concentric decomposed model should replace the legacy three-gradient baseline.

See `../../reports/gradient-mask-v8.9.4-summary.json` for the old batch baseline,
`../../reports/guijia-inner-field-experiment.json` and
`../../reports/guijia-edge-gray-experiment.json` for the Guijia decomposition,
`../../reports/gradient-mask-decomposed-cross-family.json` for the structural/render study,
`../../reports/gradient-mask-decomposed-2-summary.json` for the authoritative raw six-family batch, and
`../../reports/gradient-mask-concentric-geometry-decision.json` for the concentric geometry decision.
