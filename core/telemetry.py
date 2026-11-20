"""Run-scoped debug telemetry for pipeline latency and retries.

The collector is deliberately independent from prompts and model contracts. It
uses context variables so one evaluation run cannot leak counters into another
run, and it becomes a no-op unless ``PIPELINE_DEBUG`` is enabled by the caller.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter
from typing import Callable, Iterator, ParamSpec, TypeVar
import re

from core.resource_monitor import ResourceSampler


@dataclass(slots=True)
class StageMetric:
    invocations: int = 0
    elapsed_seconds: float = 0.0
    llm_requests: int = 0
    transport_retries: int = 0
    logical_retries: int = 0
    errors: int = 0

    @property
    def retries(self) -> int:
        return self.transport_retries + self.logical_retries


@dataclass(slots=True)
class PipelineTelemetry:
    started_at: float = field(default_factory=perf_counter)
    stages: OrderedDict[str, StageMetric] = field(default_factory=OrderedDict)
    llm_components: OrderedDict[str, StageMetric] = field(default_factory=OrderedDict)
    retry_details: OrderedDict[str, int] = field(default_factory=OrderedDict)
    diagnostic_counters: OrderedDict[str, float] = field(
        default_factory=OrderedDict
    )
    diagnostic_durations: OrderedDict[str, float] = field(
        default_factory=OrderedDict
    )
    diagnostic_events: OrderedDict[str, OrderedDict[str, int]] = field(
        default_factory=OrderedDict
    )
    _stage_stack: list[str] = field(default_factory=list)
    _component_stack: list[str] = field(default_factory=list)
    _printed: bool = False
    resource_sampler: ResourceSampler | None = None

    def metric(self, stage_name: str) -> StageMetric:
        normalized = stage_name.strip() or "Unscoped"
        if normalized not in self.stages:
            self.stages[normalized] = StageMetric()
        return self.stages[normalized]

    @property
    def active_stage(self) -> str:
        return self._stage_stack[-1] if self._stage_stack else "Unscoped"

    @contextmanager
    def stage(self, stage_name: str) -> Iterator[None]:
        metric = self.metric(stage_name)
        metric.invocations += 1
        self._stage_stack.append(stage_name)
        started = perf_counter()
        try:
            yield
        except BaseException:
            metric.errors += 1
            raise
        finally:
            metric.elapsed_seconds += perf_counter() - started
            self._stage_stack.pop()

    def record_llm_attempt(self, *, retry: bool) -> None:
        metric = self.metric(self.active_stage)
        component = (
            self.llm_components.setdefault(self._component_stack[-1], StageMetric())
            if self._component_stack
            else None
        )
        if retry:
            metric.transport_retries += 1
            if component is not None:
                component.transport_retries += 1
            self._increment_retry_detail("HTTP/LLM transport")
        else:
            metric.llm_requests += 1

    @contextmanager
    def llm_component(self, component_name: str) -> Iterator[None]:
        metric = self.llm_components.setdefault(component_name, StageMetric())
        metric.invocations += 1
        metric.llm_requests += 1
        self._component_stack.append(component_name)
        started = perf_counter()
        try:
            yield
        except BaseException:
            metric.errors += 1
            raise
        finally:
            metric.elapsed_seconds += perf_counter() - started
            self._component_stack.pop()

    def record_retry(self, label: str, *, stage_name: str | None = None) -> None:
        metric = self.metric(stage_name or self.active_stage)
        metric.logical_retries += 1
        self._increment_retry_detail(label.strip() or "Pipeline retry")

    def _increment_retry_detail(self, label: str) -> None:
        self.retry_details[label] = self.retry_details.get(label, 0) + 1

    def record_counter(self, name: str, amount: float = 1.0) -> None:
        """Accumulate one run-scoped diagnostic counter."""

        normalized = name.strip() or "unnamed_counter"
        self.diagnostic_counters[normalized] = (
            self.diagnostic_counters.get(normalized, 0.0) + float(amount)
        )

    def record_duration(self, name: str, seconds: float) -> None:
        """Accumulate wall time for work below the coarse pipeline stages."""

        normalized = name.strip() or "unnamed_duration"
        self.diagnostic_durations[normalized] = (
            self.diagnostic_durations.get(normalized, 0.0)
            + max(0.0, float(seconds))
        )

    def record_event(self, category: str, label: str) -> None:
        """Count categorical outcomes such as verifier retry reason codes."""

        normalized_category = category.strip() or "event"
        normalized_label = label.strip() or "UNKNOWN"
        labels = self.diagnostic_events.setdefault(
            normalized_category,
            OrderedDict(),
        )
        labels[normalized_label] = labels.get(normalized_label, 0) + 1

    def elapsed_seconds(self) -> float:
        return perf_counter() - self.started_at

    def render_summary(self) -> str:
        total = self.elapsed_seconds()
        headers = ("Phần xử lý", "Lượt", "Thời gian", "% tổng", "LLM", "Retry", "Lỗi")
        rows: list[tuple[str, str, str, str, str, str, str]] = []
        for name, metric in self.stages.items():
            percent = (metric.elapsed_seconds / total * 100.0) if total > 0 else 0.0
            rows.append(
                (
                    name,
                    str(metric.invocations),
                    _format_duration(metric.elapsed_seconds),
                    f"{percent:.1f}%",
                    str(metric.llm_requests),
                    str(metric.retries),
                    str(metric.errors),
                )
            )

        total_llm = sum(item.llm_requests for item in self.stages.values())
        total_retries = sum(item.retries for item in self.stages.values())
        total_errors = sum(item.errors for item in self.stages.values())
        rows.append(
            (
                "TỔNG THỜI GIAN THỰC",
                "-",
                _format_duration(total),
                "100.0%",
                str(total_llm),
                str(total_retries),
                str(total_errors),
            )
        )
        sections = [_render_table(headers, rows)]

        if self.resource_sampler is not None:
            resource_rows = self.resource_sampler.summary_rows()
            if resource_rows:
                sections.extend(
                    (
                        "",
                        "TÀI NGUYÊN HỆ THỐNG (LẤY MẪU ĐỊNH KỲ)",
                        _render_table(
                            ("Tài nguyên", "Min", "Trung bình", "Max", "Số mẫu"),
                            resource_rows,
                        ),
                    )
                )
            if self.resource_sampler.notes:
                sections.extend(
                    ("", "Ghi chú tài nguyên: " + " | ".join(self.resource_sampler.notes))
                )

        if self.llm_components:
            component_rows = [
                (
                    name,
                    str(metric.llm_requests),
                    _format_duration(metric.elapsed_seconds),
                    str(metric.transport_retries),
                    str(metric.errors),
                )
                for name, metric in self.llm_components.items()
            ]
            sections.extend(
                (
                    "",
                    "CHI TIẾT THỜI GIAN LLM THEO ROLE",
                    _render_table(
                        ("Role", "Số request", "Thời gian", "HTTP retry", "Lỗi"),
                        component_rows,
                    ),
                )
            )

        if self.retry_details:
            retry_rows = [(label, str(count)) for label, count in self.retry_details.items()]
            sections.extend(
                (
                    "",
                    "CHI TIẾT RETRY",
                    _render_table(("Loại retry", "Số lần"), retry_rows),
                )
            )
        else:
            sections.extend(("", "CHI TIẾT RETRY: không có retry."))

        if self.diagnostic_counters:
            counter_rows = [
                (name, _format_counter(value))
                for name, value in self.diagnostic_counters.items()
            ]
            sections.extend(
                (
                    "",
                    "CHẨN ĐOÁN PIPELINE",
                    _render_table(("Chỉ số", "Giá trị"), counter_rows),
                )
            )
        if self.diagnostic_durations:
            duration_rows = [
                (name, _format_duration(value))
                for name, value in self.diagnostic_durations.items()
            ]
            sections.extend(
                (
                    "",
                    "THỜI GIAN CHẨN ĐOÁN",
                    _render_table(("Công việc", "Tổng thời gian"), duration_rows),
                )
            )
        if self.diagnostic_events:
            event_rows = [
                (category, label, str(count))
                for category, labels in self.diagnostic_events.items()
                for label, count in labels.items()
            ]
            sections.extend(
                (
                    "",
                    "SỰ KIỆN CHẨN ĐOÁN",
                    _render_table(("Nhóm", "Kết quả", "Số lần"), event_rows),
                )
            )
        return "\n".join(sections)

    def print_summary(self) -> None:
        if self._printed:
            return
        self._printed = True
        self.stop_resource_sampling()
        border = "=" * 88
        print(
            f"\n{border}\nDEBUG :: PIPELINE PERFORMANCE SUMMARY\n{border}\n"
            f"{self.render_summary()}\n{border}"
        )

    def start_resource_sampling(self) -> None:
        if self.resource_sampler is None:
            self.resource_sampler = ResourceSampler()
            self.resource_sampler.start()

    def stop_resource_sampling(self) -> None:
        if self.resource_sampler is not None:
            self.resource_sampler.stop()


_CURRENT_TELEMETRY: ContextVar[PipelineTelemetry | None] = ContextVar(
    "pipeline_telemetry",
    default=None,
)


@contextmanager
def telemetry_session(enabled: bool) -> Iterator[PipelineTelemetry | None]:
    if not enabled:
        yield None
        return
    telemetry = PipelineTelemetry()
    token = _CURRENT_TELEMETRY.set(telemetry)
    telemetry.start_resource_sampling()
    try:
        yield telemetry
    finally:
        telemetry.stop_resource_sampling()
        _CURRENT_TELEMETRY.reset(token)


@contextmanager
def trace_stage(stage_name: str) -> Iterator[None]:
    telemetry = _CURRENT_TELEMETRY.get()
    if telemetry is None:
        yield
        return
    with telemetry.stage(stage_name):
        yield


P = ParamSpec("P")
R = TypeVar("R")


def traced_stage(stage_name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a synchronous pipeline helper without changing its contract."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with trace_stage(stage_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def record_llm_attempt(*, retry: bool) -> None:
    telemetry = _CURRENT_TELEMETRY.get()
    if telemetry is not None:
        telemetry.record_llm_attempt(retry=retry)


@contextmanager
def trace_llm_component(system_prompt: str) -> Iterator[None]:
    telemetry = _CURRENT_TELEMETRY.get()
    if telemetry is None:
        yield
        return
    with telemetry.llm_component(_component_name(system_prompt)):
        yield


def record_retry(label: str, *, stage_name: str | None = None) -> None:
    telemetry = _CURRENT_TELEMETRY.get()
    if telemetry is not None:
        telemetry.record_retry(label, stage_name=stage_name)


def record_counter(name: str, amount: float = 1.0) -> None:
    """Record a numeric diagnostic only while debug telemetry is active."""

    telemetry = _CURRENT_TELEMETRY.get()
    if telemetry is not None:
        telemetry.record_counter(name, amount)


def record_duration(name: str, seconds: float) -> None:
    """Record a diagnostic duration only while debug telemetry is active."""

    telemetry = _CURRENT_TELEMETRY.get()
    if telemetry is not None:
        telemetry.record_duration(name, seconds)


def record_event(category: str, label: str) -> None:
    """Record a categorical diagnostic only while debug telemetry is active."""

    telemetry = _CURRENT_TELEMETRY.get()
    if telemetry is not None:
        telemetry.record_event(category, label)


def observe_debug_event(title: str) -> None:
    """Count model-contract retries already exposed by an explicit debug event.

    Only events that uniquely identify the retrying model call are counted.
    Follow-up dumps such as a validated retry result are intentionally ignored.
    """
    telemetry = _CURRENT_TELEMETRY.get()
    if telemetry is None:
        return
    upper = title.upper()
    attempt_match = re.search(r"\bATTEMPT\s+(\d+)\b", upper)
    if attempt_match and int(attempt_match.group(1)) > 1:
        label = re.sub(r"\s*::\s*(?:RAW\s+)?ATTEMPT\s+\d+.*$", "", title).strip()
        telemetry.record_retry(f"{label} retry")
        return
    if "RETRY RAW" in upper or "PATCH RETRY" in upper:
        label = re.split(r"\s*::\s*(?:RETRY RAW|SEMANTIC FRAMING PATCH RETRY)", title, maxsplit=1)[0]
        telemetry.record_retry(f"{label.strip()} retry")
        return
    if upper.endswith(" RETRY"):
        label = re.sub(r"\s+RETRY$", "", title, flags=re.IGNORECASE).strip()
        telemetry.record_retry(f"{label} retry")


def _format_duration(seconds: float) -> str:
    if seconds < 1.0:
        return f"{seconds * 1000.0:.0f} ms"
    if seconds < 60.0:
        return f"{seconds:.2f} s"
    minutes, remainder = divmod(seconds, 60.0)
    if minutes < 60:
        return f"{int(minutes):02d}:{remainder:05.2f}"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:02d}:{minutes:02d}:{remainder:05.2f}"


def _format_counter(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.3f}"


def _component_name(system_prompt: str) -> str:
    """Map stable prompt role declarations to readable telemetry labels."""
    prompt = " ".join(str(system_prompt or "").split())
    upper = prompt.upper()
    role_markers = (
        ("REQUIREMENT EVIDENCE SELECTOR", "Requirement Evidence Selector"),
        ("EVIDENCE SELECTOR", "Evidence Selector"),
        ("CLAIM EXTRACTOR", "Claim Extractor"),
        ("CLAIM VERIFIER", "Claim Verifier"),
        ("SOURCE CONDITION EXTRACTOR", "Condition Extractor"),
        ("CONDITION MATCHER", "Condition Matcher"),
        ("CASE FACT EXTRACTOR", "Fact Extractor"),
        ("TEMPORAL EXTRACTOR", "Temporal Extractor"),
        ("COVERAGE APPRAISER", "Coverage Appraiser"),
        ("PLAN SEMANTIC APPRAISER", "Plan Semantic Appraiser"),
        ("SEMANTIC PLAN REPAIRER", "Semantic Plan Repairer"),
        ("PLAN AUDITOR", "Plan Auditor"),
        ("LEGAL RESEARCH PLANNER", "Planner"),
        ("RETRIEVAL FACT SELECTOR", "Retrieval Fact Selector"),
        ("RETRIEVAL QUERY COMPOSER", "Retrieval Query Composer"),
        ("RETRIEVAL QUERY VERIFIER", "Retrieval Query Verifier"),
        ("RETRIEVAL PLANNER", "Retrieval Planner"),
        ("ANSWER WRITER CHO CÂU TRẢ LỜI TỪNG PHẦN", "Partial Answer Writer"),
        ("ANSWER WRITER", "Answer Writer"),
        ("RESPONSE AUDITOR", "Response Auditor"),
        ("ANSWER REVISER", "Answer Reviser"),
        ("QUERY NORMALIZER", "Query Normalizer"),
        ("SCOPE REVIEWER", "Scope Reviewer"),
        ("FRONT DESK", "Front Desk"),
        ("BỘ CHUẨN HÓA TIẾNG VIỆT", "Diacritic Normalizer"),
        ("LUẬT SƯ TƯ VẤN SỬA ĐỔI", "Context Partial Reviser"),
        ("LUẬT SƯ TƯ VẤN VIẾT", "Context Partial Writer"),
    )
    for marker, label in role_markers:
        if marker in upper:
            return label
    match = re.search(r"Bạn là\s+([^\.\n]{1,60})", prompt, flags=re.IGNORECASE)
    return match.group(1).strip() if match else "LLM khác"


def _render_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def line(values: tuple[str, ...]) -> str:
        return "| " + " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(values)
        ) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    output = [separator, line(headers), separator]
    output.extend(line(row) for row in rows)
    output.append(separator)
    return "\n".join(output)
