# Morat

Status: **active research**

Research topic: geometric construction recovery

## Motivation

A project-authored manual redraw demonstrates the intended reconstruction mindset but is not itself
provenance evidence. The redraw regularizes the outer badge as exact concentric circles. Its internal
ribbon-like forms are still based on eyeballed Bézier curves, so Morat remains an explicit research
subject rather than a finished reference reconstruction.

## Current hypothesis

Preliminary inspection of the supplied source/redraw pair suggests that several ribbon centerlines and
paired boundaries are close to circular arcs. The preferred next experiment is to test whether the forms
can be reconstructed from a small geometric system rather than independently fitted curves:

1. fit each candidate ribbon centerline to a circle/arc;
2. test paired boundaries for a common center and two radii;
3. prefer constant-width annular sectors where residuals support that interpretation;
4. constrain endpoints with radial guides and supported tangency/intersection relationships;
5. derive adjoining positive and negative regions from the same construction when possible;
6. compare the clean construction against source evidence at vector/native and normal UI sizes.

## Guardrails

- Do not force circular geometry merely because it is aesthetically cleaner.
- Treat project-authored redraw geometry as a hypothesis, not source authority.
- Preserve deliberate asymmetry if the source supports it.
- Prefer a small shared construction over independently tuned Béziers only when the residuals and visual
  evidence justify it.

## Desired outcome

Recover a compact, explainable Morat construction whose radii, centers, widths, and endpoint constraints
can be stated explicitly. If the circular/annular hypothesis fails for a region, record that failure and
retain only the parts that are supported rather than regularizing the whole symbol.
