# Design goals

## Goal

Produce SVG images that are **clean, minimal, and representative** of the source artwork.

The project is not a lossless compressor and does not treat pixel identity as the definition of success.
The intended output is a compact, maintainable vector representation that preserves the artwork's
**authorial intent** while removing accidental complexity introduced by export pipelines, tracing,
raster masks, redundant geometry, and similar artifacts.

## Clean

A clean SVG should express the visible artwork directly and predictably.

Prefer:

- meaningful vector geometry over embedded raster masks when the same visual construction can be
  represented directly;
- simple gradients, fills, strokes, clipping, and reuse over flattened stacks of near-identical
  elements;
- reachable definitions and references only;
- deterministic, standards-compliant SVG without broken or unnecessary external dependencies;
- geometry that corresponds to visible design rather than hidden editor debris or off-artboard content.

Clean does **not** mean flattening every SVG into the same stylistic vocabulary. A complex construction
may be correct when that complexity is part of the artwork rather than an exporter artifact.

## Minimal

Use the least structural complexity that preserves the intended design to an acceptable degree.

Minimality is not byte-golf and is not an absolute element-count target. A small increase in complexity
is preferred when it produces a meaningful fidelity gain. For example, three well-chosen gradients can
be preferable to two if the extra gradient materially better represents the original shading, while
still replacing dozens of flattened blend or stripe elements.

Evaluate minimality in terms of:

- number of meaningful graphical primitives;
- duplicated geometry;
- unnecessary definitions, IDs, classes, masks, and filters;
- embedded raster payloads;
- path/contour complexity;
- maintainability and intelligibility of the resulting SVG;
- file size as a consequence, not the sole objective.

## Representative

A representative reconstruction retains **authorial intent**, not every pixel produced by a particular
exporter or rasterizer.

Important characteristics normally include:

- silhouette and proportions;
- composition and relative placement of major elements;
- distinctive symbols, lettering, and identifying marks;
- intended palette and major tonal relationships;
- meaningful gradients, highlights, shadows, and transparency;
- deliberate distressing, texture, or asymmetry when it is part of the artwork;
- the overall visual reading at the sizes for which the asset is used.

The following may be changed or removed when evidence shows they are incidental to the intended design:

- redundant blend-stack approximations;
- subpixel contours introduced by tracing or expansion;
- raster-mask scaffolding that merely approximates a simple vector effect;
- antialiasing differences caused by equivalent vector constructions;
- invisible, off-artboard, unreachable, or editor-generated content;
- needless precision or duplicated definitions.

A reconstruction must not invent new visual content merely because it looks plausible. When source
evidence is insufficient to establish authorial intent, record the uncertainty and keep the case
experimental or deferred.

## Optimization priority

When goals compete, use this order:

1. preserve authorial intent;
2. preserve identifying geometry and composition;
3. prefer first-party provenance and well-supported reconstruction evidence;
4. remove accidental/exporter complexity;
5. minimize structural complexity;
6. reduce bytes.

This means the smallest candidate is not automatically the preferred candidate. The preferred result is
the simplest candidate that best represents the supported source intent.
