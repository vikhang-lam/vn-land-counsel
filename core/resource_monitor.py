"""Low-overhead CPU/RAM/GPU sampling used only by debug telemetry."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import os
from threading import Event, Lock, Thread
from typing import Any


@dataclass(slots=True)
class RunningMetric:
    unit: str
    count: int = 0
    minimum: float = float("inf")
    maximum: float = float("-inf")
    total: float = 0.0

    def add(self, value: float) -> None:
        numeric = float(value)
        self.count += 1
        self.minimum = min(self.minimum, numeric)
        self.maximum = max(self.maximum, numeric)
        self.total += numeric

    @property
    def average(self) -> float:
        return self.total / self.count if self.count else 0.0


class ResourceSampler:
    """Sample host resources without making monitoring a runtime dependency."""

    def __init__(self, interval_seconds: float | None = None) -> None:
        if interval_seconds is None:
            try:
                interval_seconds = float(
                    os.getenv("PIPELINE_DEBUG_RESOURCE_INTERVAL", "2.0")
                )
            except ValueError:
                interval_seconds = 2.0
        self.interval_seconds = max(0.5, float(interval_seconds))
        self.metrics: OrderedDict[str, RunningMetric] = OrderedDict()
        self.notes: list[str] = []
        self._stop_event = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._psutil: Any = None
        self._process: Any = None
        self._pynvml: Any = None
        self._gpu_handles: list[Any] = []

    def start(self) -> None:
        if self._thread is not None:
            return
        self._initialize_backends()
        self._thread = Thread(
            target=self._run,
            name="pipeline-resource-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_seconds + 1.0))
            self._thread = None
        if self._pynvml is not None:
            try:
                self._pynvml.nvmlShutdown()
            except Exception:
                pass

    def summary_rows(self) -> list[tuple[str, str, str, str, str]]:
        with self._lock:
            return [
                (
                    label,
                    _format_value(metric.minimum, metric.unit),
                    _format_value(metric.average, metric.unit),
                    _format_value(metric.maximum, metric.unit),
                    str(metric.count),
                )
                for label, metric in self.metrics.items()
                if metric.count
            ]

    def add_sample(self, label: str, value: float, unit: str) -> None:
        """Add one sample; public mainly to keep aggregation easy to test."""
        with self._lock:
            metric = self.metrics.setdefault(label, RunningMetric(unit=unit))
            metric.add(value)

    def _initialize_backends(self) -> None:
        try:
            import psutil

            self._psutil = psutil
            self._process = psutil.Process(os.getpid())
            # First non-blocking percentages only prime psutil's counters.
            psutil.cpu_percent(interval=None)
            self._process.cpu_percent(interval=None)
        except Exception as error:
            self.notes.append(f"CPU/RAM monitor N/A: {error}")

        try:
            import pynvml

            pynvml.nvmlInit()
            self._pynvml = pynvml
            self._gpu_handles = [
                pynvml.nvmlDeviceGetHandleByIndex(index)
                for index in range(pynvml.nvmlDeviceGetCount())
            ]
            if not self._gpu_handles:
                self.notes.append("GPU monitor N/A: không phát hiện NVIDIA GPU.")
        except Exception as error:
            self._pynvml = None
            self._gpu_handles = []
            self.notes.append(f"GPU monitor N/A: {error}")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._sample_once()
            if self._stop_event.wait(self.interval_seconds):
                break

    def _sample_once(self) -> None:
        if self._psutil is not None and self._process is not None:
            try:
                virtual_memory = self._psutil.virtual_memory()
                self.add_sample(
                    "CPU hệ thống",
                    self._psutil.cpu_percent(interval=None),
                    "%",
                )
                self.add_sample(
                    "CPU tiến trình Python (1 core=100%)",
                    self._process.cpu_percent(interval=None),
                    "%",
                )
                self.add_sample(
                    "RAM hệ thống đã dùng",
                    virtual_memory.used / (1024.0**3),
                    "GiB",
                )
                self.add_sample(
                    "RAM tiến trình Python",
                    self._process.memory_info().rss / (1024.0**3),
                    "GiB",
                )
            except Exception as error:
                self._note_once(f"CPU/RAM sampling stopped: {error}")
                self._psutil = None
                self._process = None

        if self._pynvml is not None:
            for index, handle in enumerate(self._gpu_handles):
                try:
                    utilization = self._pynvml.nvmlDeviceGetUtilizationRates(handle)
                    memory = self._pynvml.nvmlDeviceGetMemoryInfo(handle)
                    self.add_sample(f"GPU {index} utilization", utilization.gpu, "%")
                    self.add_sample(
                        f"GPU {index} VRAM used",
                        memory.used / (1024.0**3),
                        "GiB",
                    )
                except Exception as error:
                    self._note_once(f"GPU {index} sampling stopped: {error}")

    def _note_once(self, note: str) -> None:
        with self._lock:
            if note not in self.notes:
                self.notes.append(note)


def _format_value(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.1f}%"
    return f"{value:.1f} {unit}"
