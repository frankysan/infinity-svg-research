# Kazuraba Ruby Monday

Status: **validated**

Classification: `flattened-blend-stack`

Path: `units/kazuraba-ruby-monday-1-1.svg`

## Diagnosis

The source is 1,875,476 bytes with 1,380 paths, 1,383 linear gradients, and repeated translated blend
stacks. Most gradients belong to a handful of repeated palette families. The generated blend members are
structurally reusable rather than independent artwork.

## Reconstruction

`blend_use_reconstruct.py` replaces qualifying translated stack members with a base group plus `<use>`
clones and prunes definitions made unreachable by the rewrite.

A historical hand experiment reached 96,886 bytes. The recovered generalized implementation produced
about 108 KB and measured approximately 2.86/255 RGBA RMSE at 1600 px. Residual differences are mostly
rounding/antialiasing around text edges.

The result is intentionally review-required because it is not pixel-exact.
