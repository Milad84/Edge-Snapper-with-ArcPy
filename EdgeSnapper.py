# ArcGIS Pro / ArcPy 3.x
# v2.2: A -> B snap (auto tolerance) + overshoot trim; resilient to locks & in_memory issues
import arcpy, os, uuid, traceback

# ---------- YOUR PATHS ----------
FC_A    = r"G:\ATD\ACTIVE TRANS\Vision Zero\GIS\New Vision Zero Polygons_2025\New Vision Zero Polygons.gdb\New_Vision_Zero_Polygon_Test_For_Snapping"
FC_B    = r"G:\ATD\ACTIVE TRANS\Vision Zero\GIS\New Vision Zero Polygons_2025\New Vision Zero Polygons.gdb\Current_Vision_Zero_Test_For_Snapping"
OUT_GDB = r"G:\ATD\ACTIVE TRANS\Vision Zero\GIS\New Vision Zero Polygons_2025\New Vision Zero Polygons.gdb"

A_OUT_NAME        = "New_VZP_Test_Snapped_AtoB"
B_OUT_NAME        = "Current_VZP_Test_Ref_Copy"
OVERLAP_DIAG_BAS  = "A_B_Overlap_DIAG"

# ---------- SETTINGS (feet; WKID 2277) ----------
FORCE_WKID        = 2277       # set None to keep A's CRS
REPAIR_GEOMETRY   = True
MAX_SNAP_FT       = 10.0
NEAR_PCTILE       = 0.95       # 95th pct of A->B vertex dists = tolerance
TEMP_DENSIFY_FT   = None       # if None -> min(2.0, tol/3)  (A only, temporary)
POST_SIMPLIFY_FT  = 0.2        # light vertex thinning after trim
MAKE_OVERLAP_DIAG = True

# ---------- ENV ----------
arcpy.env.overwriteOutput = True
arcpy.env.addOutputsToMap = False  # avoid creating fresh locks

# ---------- HELPERS ----------
def msg(s):
    try: arcpy.AddMessage(s)
    except: pass
    print(s)

def ws_chain():
    """Preferred temp workspaces, in order: in_memory -> scratchGDB -> OUT_GDB."""
    chain = []
    try:
        chain.append("in_memory")
    except Exception:
        pass
    if arcpy.env.scratchGDB:
        chain.append(arcpy.env.scratchGDB)
    chain.append(OUT_GDB)
    return chain

def unique_out(base_name, ws):
    """Return a unique path (never delete existing), to avoid lock errors."""
    cand = os.path.join(ws, base_name) if ws != "in_memory" else base_name
    if not arcpy.Exists(cand):
        return cand
    uid = uuid.uuid4().hex[:6]
    return os.path.join(ws, f"{base_name}_{uid}") if ws != "in_memory" else f"{base_name}_{uid}"

def project_or_copy_fresh(src, target_sr):
    """
    Project/copy to the first workspace that succeeds.
    Returns the CREATED dataset path (from GP result), not just the intended path.
    """
    base = os.path.basename(src) + "_proj"
    for ws in ws_chain():
        try:
            out = unique_out(base, ws)
            if target_sr and arcpy.Describe(src).spatialReference.factoryCode != target_sr.factoryCode:
                res = arcpy.management.Project(src, out, target_sr)
            else:
                res = arcpy.management.CopyFeatures(src, out)
            created = res[0]
            if arcpy.Exists(created):
                return created
        except Exception as e:
            continue
    raise RuntimeError("Could not create a projected/copy workspace dataset for: " + src)

def ensure_output(base_name):
    """Pick a writable output path in OUT_GDB (never delete; auto-suffix if locked)."""
    path = os.path.join(OUT_GDB, base_name)
    if arcpy.Exists(path):
        try:
            arcpy.management.Delete(path)
            return path
        except Exception:
            uid = uuid.uuid4().hex[:6]
            newp = os.path.join(OUT_GDB, f"{base_name}_{uid}")
            msg(f"⚠️  {base_name} is locked; writing to {os.path.basename(newp)} instead.")
            return newp
    return path

def pctile(vals, p):
    vals = sorted(vals)
    if not vals: return None
    k = max(0, min(len(vals)-1, int(round((len(vals)-1)*p))))
    return vals[k]

def erase_safe(in_fc, erase_fc, out_fc):
    """Erase with fallbacks; writes to out_fc."""
    try:
        arcpy.analysis.Erase(in_fc, erase_fc, out_fc)
        return
    except Exception:
        try:
            arcpy.analysis.PairwiseErase(in_fc, erase_fc, out_fc)
            return
        except Exception:
            # Identity fallback
            ws = ws_chain()[0]
            tmp = unique_out("id_tmp", ws)
            arcpy.analysis.Identity(in_fc, erase_fc, tmp, "NO_RELATIONSHIPS")
            fld = next((f.name for f in arcpy.ListFields(tmp) if f.name.upper().startswith("FID_")), None)
            if not fld:
                raise RuntimeError("Identity fallback failed: FID_* field not found.")
            where = f"{arcpy.AddFieldDelimiters(tmp, fld)} = -1"
            arcpy.management.MakeFeatureLayer(tmp, "id_lyr", where)
            arcpy.management.CopyFeatures("id_lyr", out_fc)

# ---------- MAIN ----------
def main():
    try:
        # 0) Prepare / project to a safe temp WS
        target_sr = arcpy.SpatialReference(FORCE_WKID) if FORCE_WKID else None
        msg("Preparing inputs…")
        A_proj = project_or_copy_fresh(FC_A, target_sr)
        B_proj = project_or_copy_fresh(FC_B, target_sr)

        if REPAIR_GEOMETRY:
            arcpy.management.RepairGeometry(A_proj, "DELETE_NULL")
            arcpy.management.RepairGeometry(B_proj, "DELETE_NULL")

        # 1) Build B boundary (temp WS)
        ws = ws_chain()[0]
        B_lines = unique_out("B_boundary_lines", ws)
        arcpy.management.PolygonToLine(B_proj, B_lines, "IGNORE_NEIGHBORS")

        # 2) Auto-pick snap tolerance from A vertex distances to B boundary
        msg("Measuring A→B vertex distances (NEAR)…")
        A_verts = unique_out("A_vertices", ws)
        arcpy.management.FeatureVerticesToPoints(A_proj, A_verts, "ALL")
        arcpy.analysis.Near(A_verts, B_lines)
        dists = [r[0] for r in arcpy.da.SearchCursor(A_verts, ["NEAR_DIST"]) if r[0] is not None]
        if not dists:
            raise RuntimeError("No NEAR distances computed; check geometry.")
        tol = min(MAX_SNAP_FT, max(0.5, pctile(dists, NEAR_PCTILE)))
        msg(f"Auto snap tolerance (p{int(NEAR_PCTILE*100)}): {tol:.2f} ft (cap {MAX_SNAP_FT} ft)")

        # 3) Create FINAL outputs (handle locks gracefully)
        A_OUT = ensure_output(A_OUT_NAME)
        B_OUT = ensure_output(B_OUT_NAME)
        arcpy.management.CopyFeatures(A_proj, A_OUT)
        arcpy.management.CopyFeatures(B_proj, B_OUT)

        # 4) TEMP densify A (tiny) + SNAP A→B
        d_int = TEMP_DENSIFY_FT if TEMP_DENSIFY_FT is not None else min(2.0, tol/3.0)
        if d_int > 0:
            msg(f"Temporary densify A @ ~{d_int:.2f} ft …")
            arcpy.edit.Densify(A_OUT, "DISTANCE", d_int)

        msg(f"Snapping A → B (EDGE + VERTEX) @ {tol:.2f} ft …")
        arcpy.edit.Snap(A_OUT, [[B_OUT, "EDGE", tol], [B_OUT, "VERTEX", tol]])

        # 5) Overshoot trim (remove A ∩ B from A)
        if MAKE_OVERLAP_DIAG:
            OVERLAP_DIAG = ensure_output(OVERLAP_DIAG_BAS)
            msg("Creating overlap diagnostics (A ∩ B)…")
            arcpy.analysis.Intersect([A_OUT, B_OUT], OVERLAP_DIAG, "ALL")

        msg("Trimming A by B to remove overshoot slivers…")
        A_trim = unique_out("A_trim", ws)
        erase_safe(A_OUT, B_OUT, A_trim)
        arcpy.management.Delete(A_OUT)
        arcpy.management.CopyFeatures(A_trim, A_OUT)

        # 6) Light vertex thinning (POINT_REMOVE)
        if POST_SIMPLIFY_FT and POST_SIMPLIFY_FT > 0:
            A_simp = unique_out("A_simp", ws)
            msg(f"Simplifying (POINT_REMOVE) @ {POST_SIMPLIFY_FT:.2f} ft …")
            arcpy.cartography.SimplifyPolygon(
                in_features=A_OUT,
                out_feature_class=A_simp,
                algorithm="POINT_REMOVE",
                tolerance=f"{POST_SIMPLIFY_FT} Feet",
                minimum_area=None,
                error_option="RESOLVE_ERRORS",
                collapsed_point_option="NO_KEEP"
            )
            arcpy.management.Delete(A_OUT)
            arcpy.management.CopyFeatures(A_simp, A_OUT)

        msg("Done.")
        msg(f"A (snapped & overshoot-trimmed) → {A_OUT}")
        msg(f"B (reference copy) → {B_OUT}")
        if MAKE_OVERLAP_DIAG:
            msg(f"Overlap QA → {OVERLAP_DIAG}")

    except arcpy.ExecuteError:
        msg("ArcPy tool error:")
        msg(arcpy.GetMessages(2))
        raise
    except Exception as e:
        msg("Python exception:")
        msg(str(e))
        msg(traceback.format_exc())
        raise
    finally:
        try:
            arcpy.management.ClearWorkspaceCache(OUT_GDB)
        except Exception:
            pass

if __name__ == "__main__":
    main()
