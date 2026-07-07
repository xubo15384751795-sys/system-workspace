from src.runtime.assembly import _load_config, build_system, create_system_api, run_once


if __name__ == "__main__":
    loaded = _load_config()
    snapshot, artifacts = run_once(loaded, use_mock=True)
    print(snapshot)
    print("Artifacts:", artifacts)
