import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory


def freeze_panel(root, design):
    if design["stage"] != "panel-candidate":
        raise ValueError("Screening and confirmation must produce a candidate panel before freezing")
    manifest = {
        "study_id": root.name,
        "panel": design["panel"],
        "control": design["control"],
        "item_hashes": design["item_hashes"],
        "samples_per_item_per_day": design["samples_per_item_per_day"],
        "predicted_sensitivity": design["predicted_sensitivity"],
    }
    if "upstream_revision" in design:
        manifest["upstream_revision"] = design["upstream_revision"]
    data = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    destination = root / "panel"
    if destination.exists():
        _, saved_digest = read_panel(root)
        if saved_digest != digest:
            raise ValueError("A different panel is already frozen for this study")
        return saved_digest
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as temporary:
        folder = Path(temporary) / "panel"
        folder.mkdir()
        (folder / "panel.json").write_bytes(data)
        (folder / "panel.lock").write_text(digest + "\n")
        folder.rename(destination)
    return digest


def read_panel(root):
    folder = root / "panel"
    data = (folder / "panel.json").read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != (folder / "panel.lock").read_text().strip():
        raise ValueError("The frozen panel fails its SHA-256 check")
    manifest = json.loads(data)
    if manifest["study_id"] != root.name:
        raise ValueError("The frozen panel belongs to a different study")
    return manifest, digest


def verified_items(manifest, pool):
    ids = manifest["panel"]
    control = manifest["control"]
    hashes = manifest["item_hashes"]
    if len(set(ids)) != len(ids) or set(ids) != set(hashes):
        raise ValueError("The frozen panel has inconsistent question IDs")
    families = {}
    for family, items in pool.items():
        for item in items:
            item_id = item["id"]
            if item_id in hashes:
                if item["metadata"]["item_hash"] != hashes[item_id]:
                    raise ValueError("A question in the frozen panel has changed")
                families[item_id] = family
    if set(families) != set(ids):
        raise ValueError("A frozen question is missing from the source pool")
    if len(set(control)) < 2 or set(control) != {item for item in ids if families[item] == "gpqa"}:
        raise ValueError("The frozen control is inconsistent with the shared question subset")
    return families
