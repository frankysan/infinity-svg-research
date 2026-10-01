# Embedded-raster-heavy cases

Status: **identified**

Scanner v8.6 hard-classified two files.

## Druze

`factions/druze.svg` is about 189 KB with six embedded images accounting for roughly 71% of the file.
The embedded PNGs appear effectively monochrome-alpha; several are disc/ring-like. This suggests a future
reconstruction from vector/gradient/filter primitives, but compositing must be understood before a
transform is attempted.

## Taowu

`units/taowu-1-1.svg` is about 189 KB with two embedded images accounting for roughly 66% of the file.
They are effectively monochrome-alpha, but there is not yet evidence that they reduce to the same simple
primitive model as Druze.
