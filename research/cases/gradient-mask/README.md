# Flattened gradient/mask badge family

Status: **experimental / validated batch**

Classification: `flattened-gradient-mask`

## Family structure

Scanner v8.6 identified 11 semantic files which collapse to six unique byte streams. Typical sources use
83 linear-gradient definitions backed by one two-stop palette, 3 raster masks, 3 filters, 2 clip paths,
roughly 44 multiply circles, and dozens of flattened strips.

The current compact reconstruction uses:

1. one fitted linear gradient for the gray outer disc/annulus;
2. one linear base gradient for the accent inner disc;
3. one differently angled transparent highlight gradient for the accent disc;
4. original foreground artwork preserved unchanged.

Using two accent gradients is intentional: the structural cost is tiny compared with the flattened
export, and it measurably improves fidelity over forcing the accent disc into one gradient.

## v8.9.4 batch result

All six unique SHA groups reconstructed successfully and cleared the hard pathology. Candidate sizes are
roughly 5.6–12.5 KB from ~499–506 KB sources (97.5–98.9% reduction). Alpha remained unchanged in the
reported largest renders.

The remaining aggregate error is not primarily an interior-gradient problem. Analysis after the batch
showed accent-disc interior RMSE around 1.18–3.59 across the six families; the dominant outliers are at
the inner-disc boundary produced in the source by many slightly offset multiply circles. Restoring the
original circular clip paths did not improve RMSE.

Next question: find a compact approximation of the effective inner-disc edge stack without recreating
the original 40+ circle export.

See `../../reports/gradient-mask-v8.9.4-summary.json` for per-hash metrics.
