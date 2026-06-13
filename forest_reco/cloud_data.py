"""Download and unpack optional data bundles for Streamlit Cloud."""
from __future__ import annotations

import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def _target_path(data_dir: Path, member_name: str) -> Path | None:
    parts = [p for p in Path(member_name).parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if parts[0] == "wooyoung":
        parts = parts[1:]
    if parts and parts[0] == "data":
        parts = parts[1:]
    if not parts:
        return None
    return data_dir.joinpath(*parts)


def ensure_data_bundle(data_dir: str | Path, url: str) -> dict:
    """Ensure a zip data bundle from *url* is extracted into *data_dir*.

    The bundle may contain files directly at its root, under ``data/``, or under
    ``wooyoung/data/``. A marker file prevents repeated downloads on reruns.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    marker = data_dir / ".data_bundle.json"
    if marker.exists():
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
            if meta.get("url") == url:
                return meta
        except Exception:
            pass

    with tempfile.TemporaryDirectory() as td:
        bundle = Path(td) / "forest_reco_data.zip"
        urllib.request.urlretrieve(url, bundle)
        with zipfile.ZipFile(bundle) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                target = _target_path(data_dir, member.filename)
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    meta = {"url": url}
    marker.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
