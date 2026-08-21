import ast
from pathlib import Path


def test_services_do_not_import_sda_vision():
    services = Path("src/services")
    violations = []
    for path in services.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sda_vision"):
                violations.append(str(path))
            if isinstance(node, ast.Import):
                violations.extend(str(path) for alias in node.names
                                  if alias.name.startswith("sda_vision"))
    assert violations == []
