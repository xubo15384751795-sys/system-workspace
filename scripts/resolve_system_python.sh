#!/usr/bin/env bash
# Resolve the single Python interpreter supported by this workspace.
#
# The resolver is intentionally small and side-effect free.  It accepts an
# explicit PYTHON override (useful for CI), otherwise prefers the workspace
# environment created by ``uv sync``.  That matters because the managed uv
# interpreter and the workspace environment have different site-packages: a
# launchd process that bypasses ``.venv`` can silently miss declared fallback
# providers (for example yfinance).  If the workspace has not been synced yet,
# fall back to uv's managed 3.13 interpreter and conventional local paths.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

validate_candidate() {
  local candidate="$1"
  if [[ ! -x "${candidate}" ]]; then
    return 1
  fi
  if ! "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)' >/dev/null 2>&1; then
    return 1
  fi
  printf '%s\n' "${candidate}"
  return 0
}

if [[ -n "${PYTHON:-}" ]]; then
  override="${PYTHON}"
  if [[ "${override}" != */* ]]; then
    override="$(command -v "${override}" 2>/dev/null || true)"
  fi
  if validate_candidate "${override}"; then
    exit 0
  fi
  echo "[python] PYTHON override is not Python 3.13: ${PYTHON}" >&2
  exit 78
fi

# ``uv sync --locked --all-packages`` installs the workspace's locked runtime
# dependencies into this environment.  Prefer it before the bare managed
# interpreter so scheduled and interactive paths resolve the same packages.
if validate_candidate "${ROOT}/.venv/bin/python"; then
  exit 0
fi

uv_cmd="${UV:-}"
if [[ -z "${uv_cmd}" ]]; then
  uv_cmd="$(command -v uv 2>/dev/null || true)"
fi
if [[ -z "${uv_cmd}" && -x "/Users/a1/.local/bin/uv" ]]; then
  uv_cmd="/Users/a1/.local/bin/uv"
fi
if [[ -n "${uv_cmd}" ]]; then
  managed="$("${uv_cmd}" python find 3.13 2>/dev/null || true)"
  if validate_candidate "${managed}"; then
    exit 0
  fi
fi

for candidate in \
  "/Users/a1/.local/share/uv/python/cpython-3.13-macos-aarch64-none/bin/python3.13" \
  "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
  "/opt/homebrew/bin/python3.13" \
  "/usr/local/bin/python3.13"; do
  if validate_candidate "${candidate}"; then
    exit 0
  fi
done

cat >&2 <<EOF
[python] Python 3.13 is required but was not found.
[python] Install it with uv, then retry: uv python install 3.13
[python] Workspace: ${ROOT}
EOF
exit 78
