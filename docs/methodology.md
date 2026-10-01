# Research methodology

## Objective

Reduce pathological SVG complexity without confusing compression with restoration. Every experiment
starts from a source identity (path + SHA-256), a structural diagnosis, and a validation plan.

## Workflow

1. **Inventory and scan** the corpus without modifying inputs.
2. **Classify** only when evidence meets an explicit detector contract; otherwise emit an advisory.
3. **Deduplicate by SHA-256** before expensive experiments so identical source streams are investigated
   once while semantic filenames remain recorded.
4. **Form a structural hypothesis** about the exporter pathology. Avoid transformations based solely on
   file size or element count.
5. **Implement the smallest transformation** that tests that hypothesis.
6. **Render at multiple resolutions** with Inkscape and compare RGBA pixels.
7. **Rescan the candidate** to determine whether the targeted pathology was actually removed.
8. **Record the result**, including rejected approaches. Approximate transformations remain review-only
   until explicitly accepted.

## Exact versus approximate transformations

Exact transformations belong in the normal optimizer only when the candidate is pixel-identical at all
configured validation sizes. `off-artboard-content` and the systematically gated
`duplicate-fill-stroke-geometry` transform use this model.

Restorative or structural reconstructions may intentionally change antialiasing or exporter artifacts.
They live in separate commands and must record their approximation and render metrics. Examples include
blend-stack reconstruction, micro-contour pruning/simplification, palette reconstruction, and
flattened-gradient-mask reconstruction.

## Fidelity measurements

The harness records at least:

- changed pixel count/fraction;
- maximum per-channel difference;
- RGBA RMSE;
- premultiplied RGBA RMSE;
- white-background RGB RMSE;
- alpha RMSE;
- comparison images at several raster sizes.

A single scalar does not determine acceptance. Spatial distribution matters: a small number of
high-contrast edge pixels can dominate RMSE while the interior is effectively identical. Conversely, a
low average error can conceal systematic geometry damage.

## Research status vocabulary

- **identified** — structural pathology is sufficiently understood to classify.
- **experimental** — a transformation exists but remains review-required.
- **validated** — the transformation has been exercised against the actual source and measured.
- **resolved** — the preferred transformation is accepted for that case/family.
- **deferred** — understood enough to track, but not worth further work yet.
