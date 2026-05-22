import os, ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
src = str(PROJECT / "Structural Deformation Research System/src")
count = 0
for root, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    count += len([f for f in files if f.endswith(".py")])
print(f"SDRS src: {count} .py files")

tests = str(PROJECT / "Structural Deformation Research System/tests")
tcount = 0
total_tests = 0
for root, dirs, files in os.walk(tests):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in files:
        if f.endswith(".py"):
            tcount += 1
            try:
                tree = ast.parse(open(os.path.join(root, f)).read())
                total_tests += len(
                    [
                        n
                        for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.name.startswith("test_")
                    ]
                )
            except Exception as exc:
                import sys
                print(f"WARNING: _count_project: parse error: {exc}", file=sys.stderr)
print(f"SDRS tests: {tcount} files, {total_tests} test functions")

# Count across entire project
harv_src = str(PROJECT / "structural-risk-harvester/src")
harv_tests = str(PROJECT / "structural-risk-harvester/tests")
nlp_src = str(PROJECT / "Workbench/src/nlp")
for label, path in [
    ("Harvester src", harv_src),
    ("Harvester tests", harv_tests),
    ("NLP src", nlp_src),
]:
    py_count = 0
    test_count = 0
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    py_count += 1
                    try:
                        tree = ast.parse(open(os.path.join(root, f)).read())
                        test_count += len(
                            [
                                n
                                for n in ast.walk(tree)
                                if isinstance(n, ast.FunctionDef)
                                and n.name.startswith("test_")
                            ]
                        )
                    except Exception:
                        pass
    print(f"{label}: {py_count} files, {test_count} test functions")
