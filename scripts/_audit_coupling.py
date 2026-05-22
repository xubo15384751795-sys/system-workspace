#!/usr/bin/env python3
"""Engineering audit script."""
import os, ast, collections

src = "Structural Deformation Research System/src"

internal_imports = collections.Counter()
external_imports = collections.Counter()
mod_deps = collections.defaultdict(set)
mod_files = collections.defaultdict(int)

for root, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in files:
        if f.endswith(".py") and f != "__init__.py":
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, src)
            parts = rel.split("/")
            mod_name = parts[0] if len(parts) > 1 else "root"
            mod_files[mod_name] += 1
            try:
                tree = ast.parse(open(fp).read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            name = alias.name.split(".")[0]
                            if name == "src":
                                internal_imports[alias.name] += 1
                            else:
                                external_imports[name] += 1
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith("src"):
                            internal_imports[node.module] += 1
                            target_mod = node.module.split(".")[1] if len(node.module.split(".")) > 1 else "root"
                            if target_mod != mod_name:
                                mod_deps[mod_name].add(target_mod)
                        elif node.module:
                            external_imports[node.module.split(".")[0]] += 1
            except Exception as exc:
                import sys
                print(f"WARNING: _audit_coupling: parse error in {py_file}: {exc}", file=sys.stderr)

print("=== Module File Counts ===")
for mod, count in sorted(mod_files.items(), key=lambda x: -x[1]):
    print(f"  {mod}: {count} files")

print("\n=== Module -> Depends On ===")
for mod in sorted(mod_deps.keys()):
    deps = sorted(mod_deps[mod])
    if deps:
        print(f"  {mod}: {', '.join(deps)}")

print("\n=== Top Internal Imports ===")
for mod, count in internal_imports.most_common(15):
    print(f"  {mod}: {count}x")

print("\n=== Top External Imports ===")
for mod, count in external_imports.most_common(15):
    print(f"  {mod}: {count}x")
