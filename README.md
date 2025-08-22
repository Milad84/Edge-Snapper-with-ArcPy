

## A reproducible ArcGIS Pro + ArcPy workflow to align two polygon datasets (A and B) along shared street boundaries so touching edges share vertices, with no overshoots, undershoots, and with minimal vertex counts.

---

## Table of Contents

- [Overview](#overview)
- [Screenshots](#screenshots)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Parameters](#parameters)
- [Outputs](#outputs)
- [Validation and QA](#validation-and-qa)
- [Troubleshooting](#troubleshooting)
- [Performance Notes](#performance-notes)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)
- [Appendix: File Pointers](#appendix-file-pointers)

---

## Overview

Goal: make layer A share B's edge wherever they should touch.

Approach:

- Compute a data-driven snap tolerance from A->B vertex distances.
- Apply a tiny, temporary densify on A so curves can follow B.
- Snap A to B (EDGE and VERTEX). B remains unchanged.
- Trim overshoots by erasing A intersect B from A (removes the small triangular spikes).
- Run POINT_REMOVE to drop near-collinear vertices and keep geometry lean.

Result: A's boundary coincides with B's along shared edges, with minimal vertices and no overshoots.

---

## Screenshots

### Before running the script
<img width="770" height="633" alt="image" src="https://github.com/user-attachments/assets/f15ae42d-9272-4c13-a63c-240f2babc7b3" />

### After running the script
<img width="745" height="658" alt="image" src="https://github.com/user-attachments/assets/a16136b4-fc17-4c0f-ade0-7c8ae54cee5a" />


---

## Requirements

- ArcGIS Pro 3.x with ArcPy available.
- License access to tools used: Near, Polygon To Line, Feature Vertices To Points, Snap (edit), Simplify Polygon. For trimming, the script attempts Erase, then Pairwise Erase, then an Identity fallback.
- Inputs in a file geodatabase (.gdb).
- Working in a feet-based CRS is recommended. The scripts default to WKID 2277 (NAD_1983_StatePlane_Texas_Central_FIPS_4203_Feet).

---

## Quick Start

1. Place your two inputs in a GDB:
   - A: `New_Vision_Zero_Polygon_Test_For_Snapping`
   - B: `Current_Vision_Zero_Test_For_Snapping`
2. Open ArcGIS Pro and the Python window (or a Notebook).
3. Open `scripts/snap_align_v2_2.py` and edit the three paths at the top:
   - `FC_A` (feature class A)
   - `FC_B` (feature class B)
   - `OUT_GDB` (target geodatabase for outputs)
4. Run the script. Refresh the GDB in the Catalog pane and add the outputs to the map. The script does not auto-add outputs to avoid creating locks.

Optional (run from Pro's Python environment):

## How It Works

- Auto tolerance:
  - Build B's boundary with Polygon To Line.
  - Measure A's vertices to that boundary with Near.
  - Choose the 95th percentile distance, capped by `MAX_SNAP_FT`.
- Temporary densify on A only:
  - Spacing `min(2.0 ft, tolerance/3)` so A can follow B's curvature; this is later thinned away.
- Snap:
  - `arcpy.edit.Snap` on A with targets `[B EDGE, B VERTEX]` using the same tolerance.
- Overshoot trim:
  - Remove areas where A still overlaps B using Erase. If Erase is unavailable, try Pairwise Erase; otherwise fall back to Identity selection.
- Vertex thinning:
  - `arcpy.cartography.SimplifyPolygon` with `POINT_REMOVE` (default `0.2 ft`) to keep boundaries clean without materially moving edges.
- Lock safety:
  - Intermediates prefer `in_memory`, then `scratchGDB`, then `OUT_GDB`.
  - If an output name is locked, the script writes a suffixed variant and prints the exact path.

---


## Parameters

All parameters live near the top of `scripts/snap_align_v2_2.py`.

| Name | Purpose | Default | Notes |
| --- | --- | --- | --- |
| `FORCE_WKID` | Target CRS | `2277` | Set `None` to keep A's CRS; feet recommended. |
| `MAX_SNAP_FT` | Cap for auto tolerance | `10.0` | Prevents large moves. |
| `NEAR_PCTILE` | Percentile for A->B distances | `0.95` | Try `0.98` if offsets are larger. |
| `TEMP_DENSIFY_FT` | Temporary densify on A | `None` | Uses `min(2.0, tol/3)` if `None`. |
| `POST_SIMPLIFY_FT` | Vertex thinning after trim | `0.2 ft` | Use `0.3-0.5 ft` to drop more points. |
| `MAKE_OVERLAP_DIAG` | Save A intersect B for QA | `True` | Turn off when confident. |

---


## Outputs

- `New_VZP_Test_Snapped_AtoB` - final A (snapped to B, overshoots trimmed, vertex-thinned).
- `Current_VZP_Test_Ref_Copy` - copy of B (unchanged).
- `A_B_Overlap_DIAG` - optional QA layer (A intersect B before trimming).

If an output name is locked, the script writes to a suffixed name (for example `New_VZP_Test_Snapped_AtoB_ab12`) and prints the exact path.

---


## Validation and QA

- Visual: A (no fill, thick outline) vs B (contrasting outline). Check cul-de-sacs, T-junctions, and curb bulbs.
- QA layer: if `MAKE_OVERLAP_DIAG=True`, `A_B_Overlap_DIAG` should be empty or minimal.
- Optional topology: on merged data, validate rules such as Must Not Overlap (Area) and Must Not Have Gaps (Area) as your schema requires.

---


## Troubleshooting

- "table is being edited" or other locks:
  - Close attribute tables, stop edit sessions, and remove layers from the map. The script also auto-suffixes outputs to sidestep locks.
- Nothing moved:
  - Increase `MAX_SNAP_FT` to 12-15 or raise `NEAR_PCTILE` to 0.98. Ensure no selection filters the features being processed.
- Too many vertices:
  - Increase `POST_SIMPLIFY_FT` to 0.3-0.5 ft. Keep the temporary densify tiny.
- Outputs not visible in the map:
  - By design, `addOutputsToMap=False`. Refresh the GDB and add the feature classes manually (or set that env var to `True`).

---


## Performance Notes

- Local SSD paths are faster than network shares.
- Complexity scales with feature and vertex counts; a reasonable `POST_SIMPLIFY_FT` keeps final geometry light.
- If B is extremely detailed, consider a visually lossless generalization of B before processing to speed up Near and Snap.

---


## Known Limitations

- B is treated as authoritative; the script does not modify B's geometry.
- Attribute reconciliation between A and B is out of scope (geometry-only).
- Where A and B truly disagree on topology (for example, missing roads), snapping will not invent consensus; manual review is advised.

---


## Contributing

Issues and pull requests are welcome. Please include:

- a short description of the change,
- sample data or screenshots,
- ArcGIS Pro version and license level.

---




