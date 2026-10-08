"""Narrow demo policy; explicitly NOT an adversarial Python sandbox."""
import ast
import hashlib
from pathlib import Path


class PolicyError(ValueError):
    pass


def validate_candidate(path, source):
    if path != "subscription.py":
        raise PolicyError("only subscription.py may be modified by the coding role")
    if not isinstance(source, str) or len(source.encode()) > 50000:
        raise PolicyError("candidate exceeds size limit")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise PolicyError("candidate is not valid Python") from exc
    allowed = {"json", "sqlite3", "time", "uuid", "typing", "dataclasses", "datetime", "hashlib"}
    forbidden = {"eval", "exec", "open", "compile", "__import__", "getattr", "setattr", "breakpoint"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(item.name not in allowed for item in node.names):
                raise PolicyError("candidate imports a disallowed module")
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in allowed:
                raise PolicyError("candidate imports a disallowed module")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden:
            raise PolicyError("candidate uses a disallowed builtin")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr != "__init__":
            raise PolicyError("candidate uses dunder introspection")
    return source


def contained(root, relative):
    base = Path(root).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or target == base:
        raise PolicyError("path escapes workspace")
    return target


def evidence_digest(repo):
    files = sorted(path for path in Path(repo).rglob("*") if path.is_file()
                   and ".git" not in path.parts and "__pycache__" not in path.parts
                   and path.suffix not in {".db", ".pyc"})
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(repo)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_approval(approval, commit, digest):
    if approval.get("commit") != commit or approval.get("digest") != digest:
        raise PolicyError("approval does not bind to the current candidate and evidence")
    if approval.get("decision") != "approved":
        raise PolicyError("approval required")
