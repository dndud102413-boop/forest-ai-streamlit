"""Download and unpack optional data bundles for Streamlit Cloud."""
from __future__ import annotations

import json
import shutil
import tempfile
import urllib.parse
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


def _normalize_url(url: str) -> str:
    """Make release-asset URLs safe even when pasted with Korean text/spaces."""
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme == "file":
        return url.strip()
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/%")
    query = urllib.parse.quote(urllib.parse.unquote(parsed.query), safe="=&?/%:+,")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, parsed.fragment))


def _required_files_exist(data_dir: Path, required_files: tuple[str, ...] | None) -> bool:
    if not required_files:
        return True
    return all((data_dir / name).exists() for name in required_files)


def ensure_data_bundle(data_dir: str | Path, url: str) -> dict:
    """Ensure a zip data bundle from *url* is extracted into *data_dir*.

    The bundle may contain files directly at its root, under ``data/``, or under
    ``wooyoung/data/``. A marker file prevents repeated downloads on reruns.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    required_files = (
        "gangwon_forest_light.gpkg",
        "gangwon_dem.tif",
        "gangwon_site_light.gpkg",
        "gangwon_precip_2020_2024.tif",
        "stations.csv",
        "derived/stations_verified.csv",
    )
    marker = data_dir / ".data_bundle.json"
    if marker.exists():
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
            if meta.get("url") == url and _required_files_exist(data_dir, required_files):
                return meta
        except Exception:
            pass

    safe_url = _normalize_url(url)
    with tempfile.TemporaryDirectory() as td:
        bundle = Path(td) / "forest_reco_data.zip"
        req = urllib.request.Request(
            safe_url,
            headers={"User-Agent": "forest-ai-streamlit/1.0"},
        )
        with urllib.request.urlopen(req, timeout=180) as response, bundle.open("wb") as dst:
            shutil.copyfileobj(response, dst)
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

    missing = [name for name in required_files if not (data_dir / name).exists()]
    if missing:
        raise FileNotFoundError("Data bundle is missing required files: " + ", ".join(missing))

    meta = {"url": url}
    marker.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
