# Research methodology

## Objective

Produce clean, minimal SVGs that represent the supported authorial intent of the source artwork. The
project distinguishes structural fidelity from accidental pixel identity: an exporter artifact is not
preserved merely because it contributes pixels to the original render.

Every experiment starts from a source identity, provenance record, structural diagnosis, and validation
plan. See [`design-goals.md`](design-goals.md) and [`provenance.md`](provenance.md).

## Workflow

1. **Inventory and scan** the corpus without modifying inputs.
2. **Establish provenance** for the sources that may inform the reconstruction.
3. **Classify** only when evidence meets an explicit detector contract; otherwise emit an advisory.
4. **Deduplicate by SHA-256** before expensive experiments so identical source streams are investigated
   once while semantic filenames remain recorded.
5. **Form a structural hypothesis** about the exporter pathology. Avoid transformations based solely on
   file size or element count.
6. **Identify the intended visual construction** using the strongest available provenance evidence.
7. **Implement the smallest well-supported transformation** that tests that hypothesis.
8. **Render at multiple resolutions** with Inkscape and compare RGBA pixels and spatial error patterns.
9. **Review authorial features** such as silhouette, proportions, palette, identifying marks, major
   gradients, texture, and composition; numeric image metrics are evidence, not the acceptance rule.
10. **Rescan the candidate** to determine whether the targeted pathology was actually removed.
11. **Record the result**, including rejected approaches, source evidence, uncertainty, and why the
    preferred candidate best balances representation and minimality.

## Exact versus representative transformations

Some transformations can be proven exact. They belong in the normal optimizer when the candidate is
pixel-identical at all configured validation sizes and the structural change is understood.
`off-artboard-content` and the systematically gated `duplicate-fill-stroke-geometry` transform use this
model.

Other transformations are **representative reconstructions**. They intentionally replace accidental
export structure with a cleaner construction and may change antialiasing, trace noise, flattened blend
artifacts, or other incidental details. These transformations remain review-required until the case is
accepted as representative of the source intent.

Examples include blend-stack reconstruction, micro-contour pruning/simplification, palette
reconstruction, and flattened-gradient-mask reconstruction.

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
high-contrast edge pixels can dominate RMSE while the interior is effectively equivalent. Conversely, a
low average error can conceal systematic damage to a logo, letterform, silhouette, or other identifying
feature.

Pixel comparison should therefore answer **where and how the reconstruction differs**, while provenance
and visual review answer whether those differences preserve authorial intent.

## Minimality review

When several candidates are representative, prefer the structurally simpler one. When a small increase
in complexity gives a meaningful fidelity improvement, prefer the higher-fidelity candidate.

The gradient-mask work is a useful example: replacing dozens of flattened elements with three purposeful
gradients is still minimal even if an even smaller two-gradient construction is possible, when the third
gradient materially improves the intended shading.

## Research status vocabulary

- **identified** — structural pathology is sufficiently understood to classify.
- **experimental** — a transformation exists but remains review-required.
- **validated** — the transformation has been exercised against the actual source and measured.
- **resolved** — the preferred representative transformation is accepted for that case/family.
- **deferred** — understood enough to track, but not worth further work yet.
