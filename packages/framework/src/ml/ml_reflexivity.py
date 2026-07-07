from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.core.interfaces import ReflexivityDetectorInterface


@dataclass
class DTWReflexivityDetector(ReflexivityDetectorInterface):
    channel_threshold: float = 0.6

    def check(self, event_log: pd.DataFrame, proxy_history: pd.DataFrame, run_date: str) -> dict[str, bool]:
        _ = run_date
        if proxy_history.empty:
            return {"credit": False, "liquidity": False, "policy": False}

        channels = {
            "credit": self._channel_signal(proxy_history, ["D", "M"]),
            "liquidity": self._channel_signal(proxy_history, ["K", "X"]),
            "policy": self._policy_signal(event_log),
        }
        return {name: signal >= self.channel_threshold for name, signal in channels.items()}

    def _channel_signal(self, proxy_history: pd.DataFrame, cols: list[str]) -> float:
        scores = []
        for col in cols:
            if col not in proxy_history.columns:
                continue
            series = pd.to_numeric(proxy_history[col], errors="coerce").dropna()
            if len(series) < 2:
                continue
            delta = np.diff(series.to_numpy(dtype=float))
            scores.append(float(np.mean(np.abs(delta))))
        if not scores:
            return 0.0
        return float(np.mean(scores))

    def _policy_signal(self, event_log: pd.DataFrame) -> float:
        if event_log.empty or "channel" not in event_log.columns:
            return 0.0
        policy_events = (event_log["channel"].astype(str).str.lower() == "policy").sum()
        return min(1.0, float(policy_events) / 5.0)
