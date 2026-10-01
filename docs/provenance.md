# Provenance policy

## First-party inputs

Current Corvus Belli/Infinity Army assets are the primary source for geometry and appearance. Every
experiment should record source URL/path, acquisition snapshot when known, SHA-256, and byte size.

Raw source assets are deliberately excluded from this Git repository. Reproduction therefore requires a
locally acquired source corpus with matching hashes.

## Historical and third-party references

Historical first-party assets can be useful guardrails, but very small historical raster assets are not
sufficient to define canonical geometry.

Human Sphere is a third-party, non-authoritative reference. Filename or visual similarity may help locate
historical artwork, but it must not silently override current first-party artwork.

Fan-produced vectors must be explicitly identified as such and never represented as official geometry.

## Generated candidates

Generated SVGs, comparison PNGs, and full run manifests are experiment outputs and are not committed by
default. Compact summaries containing hashes, metrics, and decisions belong under `research/reports/`.
