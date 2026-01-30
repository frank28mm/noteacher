from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

_LOCK = threading.Lock()


@dataclass
class _Counter:
    value: float = 0.0


@dataclass
class _Histogram:
    buckets: List[float]
    counts: List[int]
    sum: float = 0.0


_COUNTERS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], _Counter] = {}
_HISTS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], _Histogram] = {}


def _labels_tuple(labels: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return ()
    items = [
        (str(k), str(v)) for k, v in labels.items() if k is not None and v is not None
    ]
    return tuple(sorted(items))


def inc_counter(
    name: str, *, labels: Optional[Dict[str, str]] = None, value: float = 1.0
) -> None:
    key = (str(name), _labels_tuple(labels))
    with _LOCK:
        c = _COUNTERS.get(key)
        if c is None:
            c = _Counter(0.0)
            _COUNTERS[key] = c
        c.value += float(value)


def observe_histogram(
    name: str,
    *,
    value: float,
    buckets: Iterable[float],
    labels: Optional[Dict[str, str]] = None,
) -> None:
    bs = sorted(set(float(b) for b in buckets))
    key = (str(name), _labels_tuple(labels))
    with _LOCK:
        h = _HISTS.get(key)
        if h is None or h.buckets != bs:
            h = _Histogram(buckets=bs, counts=[0 for _ in bs], sum=0.0)
            _HISTS[key] = h
        h.sum += float(value)
        for i, b in enumerate(h.buckets):
            if value <= b:
                h.counts[i] += 1


class Timer:
    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self._start)


def render_prometheus() -> str:
    lines: List[str] = []
    with _LOCK:
        for (name, labels), c in sorted(_COUNTERS.items(), key=lambda x: x[0][0]):
            label_str = _fmt_labels(labels)
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name}{label_str} {c.value:.0f}")
        for (name, labels), h in sorted(_HISTS.items(), key=lambda x: x[0][0]):
            lines.append(f"# TYPE {name} histogram")
            total = 0
            for b, cnt in zip(h.buckets, h.counts):
                total += int(cnt)
                lb = dict(labels)
                lb = dict(lb or {})
                lb["le"] = str(b)
                lines.append(
                    f"{name}_bucket{_fmt_labels(tuple(sorted(lb.items())))} {total}"
                )
            lb_inf = dict(labels)
            lb_inf = dict(lb_inf or {})
            lb_inf["le"] = "+Inf"
            lines.append(
                f"{name}_bucket{_fmt_labels(tuple(sorted(lb_inf.items())))} {total}"
            )
            lines.append(f"{name}_count{_fmt_labels(labels)} {total}")
            lines.append(f"{name}_sum{_fmt_labels(labels)} {h.sum:.6f}")
    return "\n".join(lines) + "\n"


def _fmt_labels(labels: Tuple[Tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    parts = []
    for k, v in labels:
        vv = str(v).replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'{k}="{vv}"')
    return "{" + ",".join(parts) + "}"
