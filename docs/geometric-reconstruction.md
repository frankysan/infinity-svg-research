# Geometric reconstruction principles

## Purpose

Many Infinity symbols appear to have been designed from simple geometric constructions and then exported
through tooling that introduces unnecessary path complexity, small alignment errors, flattened repeats,
or raster-derived irregularity.

For those symbols, the reconstruction target is not a cleaner trace of the exported outline. The target
is the simplest well-supported **construction** that preserves the design's authorial intent.

This document records project conventions and project-authored reference cases. The reference redraws are
research artifacts, not first- or second-party provenance.

## Core rule

**Prefer intentional geometric regularity over export irregularity when the source evidence supports it.**

Typical signals include:

- repeated elements sharing a common center;
- equal or deliberately related radii;
- exact circles or circular arcs hidden inside nearly circular Bézier paths;
- regular rotational spacing;
- reflection symmetry;
- repeated congruent sectors;
- deliberate 45-, 90-, or other fixed-angle relationships;
- constant-width curved bands;
- clean tangencies and intersections.

The rule is evidentiary, not stylistic. Do not regularize an intentionally asymmetric design simply
because a symmetric version would be easier to construct.

## Geometry before shading

Base geometry and lighting are separate layers of intent.

A circle intended to be centered should remain centered even when a highlight, shadow, radial-gradient
focus, or other lighting effect is offset. Validation should not move or deform the base geometry merely
to reduce pixel error caused by flattened shading or antialiasing artifacts.

The gradient-mask badge work is the current example: the explicit source base/clip circles are perfectly
concentric, while the expanded edge stack wanders. The project therefore keeps the exact circles and
treats the wandering edge as export structure rather than allowing a fitted rim to redefine the
silhouette.

## Project-authored reference cases

The following manual redraws were supplied by the project author as examples of the intended
reconstruction mindset. They are not committed as authoritative source assets.

### Combined Army

The redraw replaces an irregular path-heavy export with an exact outer circle and a deliberately regular
central rotor-like construction. The useful lesson is rotational repetition: where one arm/sector can be
constructed and repeated at fixed angular intervals, independently traced copies are usually the wrong
abstraction.

### Onyx

The redraw exposes a strongly primitive-based construction: concentric circles, horizontal/vertical
rectangles, and deliberate 45-degree elements. It demonstrates that a geometrically simple symbol may
serialize to more bytes in an editor file while still being structurally cleaner and more intelligible.

### Shasvastii

The redraw uses explicit circular-arc commands with stable radii, including prominent 300-unit and
137.5-unit arc families in the 1000-unit construction. It is a strong example of replacing visually
similar free-form curves with shared-radius circular geometry.

### Exrah

The redraw uses concentric outer circles and a strongly four-fold internal construction. Repeated
elements are best understood as one motif rotated in 90-degree steps rather than unrelated path
fragments.

### Morat

The Morat redraw is intentionally **not** treated as a finished reference construction. Its outer badge
already uses three exact concentric circles, but several internal curved ribbons remain eyeballed Bézier
paths.

Preliminary inspection suggests that multiple ribbon centerlines and some paired edges are close to
circular arcs. The next hypothesis to test is therefore:

1. fit each ribbon's intended centerline to a circle/arc;
2. test whether paired edges can share that center with two radii;
3. prefer constant-width annular sectors when the residuals support them;
4. constrain endpoints through radial guides, tangencies, or exact intersections where supported;
5. derive adjacent negative/positive regions from the same construction instead of fitting each boundary
   independently.

Do not promote those curves to circular construction until the source evidence and fit residuals support
the hypothesis. The current redraw is a useful indication of direction, not proof.

## Typography as construction

Outlined or distressed lettering can also hide a simpler authored construction. A path-heavy export is
not automatically evidence that each notch, chip, or contour was drawn independently. Where the source
supports it, treat typography as a recoverable system consisting of the text content, typeface, layout,
and deliberate modifications.

Useful signals include:

- repeated occurrences of the same glyph converging on the same low-frequency silhouette;
- consistent baselines, cap heights, x-heights, stem widths, counters, and spacing;
- letterforms that match a known typeface or family after small trace/export noise is ignored;
- repeated distress motifs that can be separated from the underlying glyph geometry;
- a clean font plus a distinct mask/overlay explaining the visible damage more simply than thousands of
  independent contour fragments.

For a typography reconstruction:

1. recover the literal text and its layout before simplifying glyph outlines;
2. identify the exact or best-supported font family and check for official distressed, grunge, stencil,
   or other relevant variants;
3. reconstruct the research/master asset as semantic `<text>` with supported size, tracking, alignment,
   baseline, rotation, or curved placement;
4. when the font itself is clean, model deliberate scratches, chips, gaps, or erosion as a separate
   compact treatment rather than baking incidental trace noise into every glyph;
5. validate the underlying letterforms and the distress treatment separately so one does not hide errors
   in the other.

The research project stops at the semantic reconstruction. InfinityDB already has the publication
pipeline that converts text to final path geometry, so this repository must not add a second text-to-path
implementation. A research candidate may intentionally retain `<text>` because that makes the recovered
font and layout auditable even when the downstream published asset will contain paths.

### Wolfgang Amadeus Wolff

Wolfgang is the first explicit typography research subject. Its `micro-contour-explosion` pathology is
already resolved by contour pruning plus one simplify pass, but the validated differences are confined
to the distressed outer lettering. That makes the existing cleanup a valid pathology transform without
proving that the remaining outlined lettering is the final authorial reconstruction.

The next typography experiment should identify the underlying font and text layout, determine whether a
matching distressed font variant exists, and otherwise test a clean font plus a separately reconstructed
distress layer. This work must preserve deliberate typographic character while rejecting incidental
trace/export noise.

## Symmetry in the current gradient-mask family

The badge scaffold itself is strongly geometric and should remain concentric.

Among the supplied foreground examples, Blue Wolf and Maghariba are explicit exceptions to a simple
polar-symmetry expectation. The other designs in this particular set show much stronger polar symmetry.
That observation may guide analysis, but it must not become an automatic rewrite rule.

A future symmetry analyzer should therefore report hypotheses such as:

- likely rotational order (`n`-fold symmetry);
- likely reflection axes;
- repeated-sector correspondence;
- common circle/arc centers and radii;
- angular-spacing residuals;
- constant-width-band residuals.

These outputs should be advisories for reconstruction work, never automatic proof that a symbol should be
regularized.

## Validation consequences

Pixel RMSE remains useful for detecting unintended visual damage, but geometric reconstruction may
deliberately disagree with exporter-generated edge pixels.

For strongly geometric cases, validation should therefore consider:

1. provenance evidence for the intended construction;
2. exact geometric invariants such as center, radius, angle, and repeat order;
3. visual comparison at vector/native and normal UI sizes;
4. spatially localized pixel errors;
5. metrics that can exclude a documented exporter-artifact boundary when justified;
6. structural complexity and intelligibility of the result.

A lower full-image RMSE is not sufficient reason to replace an exact supported circle with a slightly
offset fitted circle.
