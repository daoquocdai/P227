import ast
from pathlib import Path


def test_production_source_does_not_import_standalone_visionv2():
    source_root = Path(__file__).resolve().parents[2] / "src"
    violations = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "visionv2" or name.startswith("visionv2.") for name in names):
                violations.append(str(path.relative_to(source_root)))

    assert violations == []
