"""Local axial views, at lung window, built from the segmentation on its native CT grid."""
import json
from pathlib import Path
import re
import tempfile
import threading

_IMAGES = threading.RLock()


def _axis(plane, xy):
    """Axial Feret diameter in mm, including the physical boundaries of edge voxels."""
    import numpy as np
    from scipy.spatial import ConvexHull
    ys = np.flatnonzero(plane.any(axis=1))
    if not len(ys):
        return 0.
    rows = plane[ys]
    left, right = rows.argmax(axis=1), plane.shape[1] - rows[:, ::-1].argmax(axis=1)
    corners = np.vstack([np.column_stack((x, y)) for x in (left, right) for y in (ys, ys+1)]) * xy
    hull = corners[ConvexHull(corners).vertices]
    # Rotating calipers: maximum distance between antipodal convex-hull vertices.
    j = 1
    farthest = 0.
    for i, a in enumerate(hull):
        b = hull[(i+1) % len(hull)]
        dx, dy = b-a
        def area(point):
            x, y = point-a
            return dx*y-dy*x
        while area(hull[(j+1) % len(hull)]) > area(hull[j]):
            j = (j+1) % len(hull)
        for point in (hull[j], hull[(j+1) % len(hull)]):
            farthest = max(farthest, float(((a-point)**2).sum()), float(((b-point)**2).sum()))
    return farthest ** .5


def _directory(root, case_id):
    if not re.fullmatch(r'[0-9a-f]{64}', case_id):
        raise ValueError("case_not_found")
    return Path(root) / "screening_views" / case_id


def metadata(root, case_id):
    try:
        return json.loads((_directory(root, case_id)/"views.json").read_bytes())
    except (OSError, ValueError):
        return {}


def save_views(root, case_id, image, mask):
    import numpy as np
    import SimpleITK as sitk
    from PIL import Image
    from scipy import ndimage
    from radai_lung_4d import componentes
    target = _directory(root, case_id)
    with _IMAGES:
        saved = metadata(root, case_id)
        if saved:
            return saved
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            work = Path(tmp)/"views"
            work.mkdir()
            pixels = sitk.GetArrayViewFromImage(image)
            xy = np.array(image.GetSpacing()[:2])
            settings = {}
            zs = set()
            for n, _, _, part in componentes(mask, image):
                ident = "N%03d" % n
                low = int(part.caixa[0].start)
                axes = [_axis(p, xy) for p in part._sub]
                best = int(np.argmax(axes))
                # All original axial slices, inclusive, on which this nodule has pixels.
                slices = [low+k for k,a in enumerate(axes) if a>0]
                zs.update(slices)
                settings[ident] = dict(long_axis_mm=float(axes[best]), axial_index=low+best,
                                       first_slice=slices[0], last_slice=slices[-1])
            for z in sorted(zs):
                plane = np.asarray(mask[z], dtype=bool)
                boundary = plane & ~ndimage.binary_erosion(plane)
                # W=1500, L=-600. No burned-in labels or patient metadata added.
                grey = np.clip((pixels[z].astype(np.float32)+1350.)*(255./1500.), 0, 255).astype("uint8")
                rgb = np.repeat(grey[:, :, None], 3, axis=2)
                rgb[boundary] = (255, 189, 60)
                im = Image.fromarray(rgb)
                width, height = im.size
                size_mm = np.asarray([width, height])*xy
                scale = min(768./max(size_mm), 1./min(xy))
                size = tuple(max(1, int(round(x))) for x in size_mm*scale)
                im = im.resize(size, Image.Resampling.LANCZOS)
                im.save(work/("%d.png" % z))
                if any(v["axial_index"] == z for v in settings.values()):
                    thumb = im.copy()
                    thumb.thumbnail((160,160), Image.Resampling.LANCZOS)
                    thumb.save(work/("%d-thumb.png" % z))
            (work/"views.json").write_text(json.dumps(settings, allow_nan=False), encoding="utf8")
            work.rename(target)
        return settings


def ensure_case(runtime, case_id):
    info = metadata(runtime.store.directory, case_id)
    if info:
        return info
    case = runtime.store.get("cases", case_id)
    if not case or case.get("segmentation_state") != "positivo":
        raise ValueError("case_not_found")
    import radai_lung_receipts as receipts
    series, signature = case["series"], case["signature"]
    runtime.core.pasta_valida(series.get("pasta"),runtime.cfg)
    # Never reconstruct previews via new inference, from changed inputs or synced snapshots.
    from hashlib import sha256
    if sha256((series["uid"]+signature).encode()).hexdigest() != case_id:
        raise ValueError("selection_expired")
    with _IMAGES:
        info = metadata(runtime.store.directory, case_id)
        if info:
            return info
        receipt = receipts.ler(series, signature)
        masks = receipt and receipts.ler_mascaras(series, receipt)
        if not masks or masks[0] is None:
            raise ValueError("preview_unavailable")
        with runtime.core._serie(series, signature) as (_, image, _):
            return save_views(runtime.store.directory, case_id, image, masks[0])


def frame(runtime, case_id, lesion, z=None, small=False):
    info = ensure_case(runtime, case_id).get(lesion)
    if not info:
        raise ValueError("case_not_found")
    z = info["axial_index"] if z is None or small else z
    if type(z) is not int or not info["first_slice"] <= z <= info["last_slice"]:
        raise ValueError("invalid_slice")
    path = _directory(runtime.store.directory, case_id)/("%d%s.png" % (z, "-thumb" if small else ""))
    if not path.is_file():
        raise ValueError("preview_unavailable")
    return path
