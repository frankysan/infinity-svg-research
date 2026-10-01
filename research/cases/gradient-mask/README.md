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
The family differences are primarily the two-stop accent palette and foreground artwork. This supports a
shared six-element replacement model:

1. one gray linear field;
2. one gray radial edge shadow;
3. one accent rim circle;
4. one accent linear base field;
5. two accent radial highlights.

An offline experiment against the **raw-source 1600 px renders archived by the v8.9.4 batch** improved
all six source families substantially. With shared geometry, RGBA RMSE fell to roughly 1.57–2.00 for five
families. Gecko improved from 7.13 to 4.01 but remained an outlier because its first-party gray-mask
crescent is much stronger than the others.

The three embedded mask images use the same SVG placement across all six families, but their native PNG
widths vary while their heights remain fixed. The gray-mask widths range from 2167 to 2194 pixels, with
Gecko at 2194x2173. This is evidence that some family-to-family mask variation may come from raster export
or cropping rather than intended geometry, so exact raster-mask differences must not automatically be
promoted as authorial intent.

A shifted one-ramp radial gradient fitted to Gecko's current Army render reduces its 1600 px full-image
RGBA RMSE to about 1.82 and the outer gray-boundary RMSE to about 2.97. The fit can be recovered with a
deterministic NumPy-only coordinate search; no SciPy dependency is required. However, whether the
unusually strong Gecko crescent is intentional remains unresolved pending an independent first-party
appearance reference.

The new decomposed-model CLI therefore remains explicitly experimental. It uses the shared weak shadow
when measured source-render evidence is weak and only fits a stronger shifted radial shadow when the
neutral gray-ring alpha contribution exceeds a conservative threshold. No fitted result is automatically
accepted.

Raw Guijia end-to-end validation of the generalized implementation produced a 7,910-byte Scoured SVG
from the 505,086-byte source, no scanner findings, zero alpha RMSE, and 1.62155 RGBA RMSE at 1600 px.
The other five unique raw sources still need an end-to-end batch run before the decomposed model can
replace the legacy three-gradient baseline.

Next questions:

1. run the decomposed model end-to-end against all six unique raw source hashes;
2. inspect any family whose fitted shadow or fidelity is materially different from the shared pattern;
3. seek independent first-party appearance evidence for Gecko before deciding whether its strong gray
   crescent represents authorial intent or exporter variance;
4. only after that review, decide whether the decomposed model should become the default reconstruction.

See `../../reports/gradient-mask-v8.9.4-summary.json` for the old batch baseline,
`../../reports/guijia-inner-field-experiment.json` and
`../../reports/guijia-edge-gray-experiment.json` for the Guijia decomposition, and
`../../reports/gradient-mask-decomposed-cross-family.json` for the cross-family structural/render study.
