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

Next questions:

1. does the linear + two-radial model generalize across all six unique badge families using source-derived
   palette and geometry;
2. what compact primitive best represents the separate 44-circle boundary/shadow stack;
3. can the gray annulus receive the same layer-decomposition treatment instead of being fit as a single
   gradient.

See `../../reports/gradient-mask-v8.9.4-summary.json` for the batch baseline and
`../../reports/guijia-inner-field-experiment.json` for the Guijia decomposition.
