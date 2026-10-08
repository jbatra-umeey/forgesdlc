"""Package source, documentation, and one verified replay; never include secrets."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = Path(sys.argv[1]).resolve()
blocked = {"__pycache__", ".venv", "gateway-cache", "node_modules"}
records = []
with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in blocked or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.suffix == ".pyc" or path.name == ".env" or path.name.startswith(".env."):
            continue
        if relative.parts[0] == "runs" and (len(relative.parts) < 2 or relative.parts[1] != "interview"):
            continue
        if path.is_symlink():
            raise RuntimeError("refusing to package symlink: " + str(relative))
        name = "ForgeSDLC/" + relative.as_posix()
        data = path.read_bytes()
        records.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        archive.writestr(name, data)
    archive.writestr("ForgeSDLC/CHECKSUMS.json", json.dumps({"files": records}, indent=2))
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
print(json.dumps({"archive": str(destination), "files": len(records), "bytes": destination.stat().st_size}))
