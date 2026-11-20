"""OpenAI-compatible client for the bundled llama.cpp server."""

from __future__ import annotations

import inspect
import json
import os
import re
import time
import types
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Union, get_args, get_origin, get_type_hints

from core.evidence import split_source_records
from core.telemetry import record_llm_attempt, trace_llm_component


DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = "Qwen3-4B-Q4_K_M"
DEFAULT_TEMPERATURE = 0.35
DEFAULT_TOP_P = 0.9
DEFAULT_REPETITION_PENALTY = 1.1


class LocalLLMError(RuntimeError):
    """Raised when the local inference server cannot complete a request."""


@dataclass(slots=True)
class LLMResponse:
    text: str


def _strip_thinking(text: str) -> str:
    """Keep hidden Qwen reasoning out of prompts, answers, and RAGAS inputs."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}

    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType):
        non_null = [item for item in args if item is not type(None)]
        if len(non_null) == 1:
            return _annotation_schema(non_null[0])
        schemas = [_annotation_schema(item) for item in non_null]
        return {"anyOf": schemas} if schemas else {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if origin is list or annotation is list:
        return {"type": "array", "items": _annotation_schema(args[0]) if args else {"type": "string"}}
    return {"type": "string"}


def _argument_descriptions(docstring: str) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    in_args = False
    for raw_line in (docstring or "").splitlines():
        line = raw_line.strip()
        if line == "Args:":
            in_args = True
            continue
        if not in_args:
            continue
        match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)", line)
        if match:
            descriptions[match.group(1)] = match.group(2).strip()
        elif line and not raw_line.startswith((" ", "\t")):
            break
    return descriptions


def tool_schema(func: Callable[..., str]) -> dict[str, Any]:
    """Convert a Python retrieval function into an OpenAI tool definition."""
    signature = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except (NameError, TypeError):
        hints = {}
    doc = inspect.getdoc(func) or ""
    summary = doc.split("Args:", 1)[0].strip()
    arg_docs = _argument_descriptions(doc)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, parameter in signature.parameters.items():
        if name == "depth":
            continue
        schema = _annotation_schema(hints.get(name, parameter.annotation))
        if name in arg_docs:
            schema["description"] = arg_docs[name]
        properties[name] = schema
        if parameter.default is inspect.Parameter.empty:
            required.append(name)

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": summary,
            "parameters": parameters,
        },
    }


class LocalLLMClient:
    """Small synchronous client for a local OpenAI-compatible endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.provider = "local"
        self.provider_label = "Local LLM"
        self.base_url = (base_url or os.getenv("LOCAL_LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.api_key = api_key or os.getenv("LOCAL_LLM_API_KEY", "local")
        self.model = model or os.getenv("LOCAL_LLM_MODEL", DEFAULT_MODEL)
        self.timeout = timeout or int(os.getenv("LOCAL_LLM_TIMEOUT", "300"))
        self.retries = max(0, int(os.getenv("LOCAL_LLM_RETRIES", "2")))
        self.default_max_tokens = int(os.getenv("LOCAL_LLM_MAX_TOKENS", "2048"))
        self.default_temperature = float(os.getenv("LOCAL_LLM_TEMPERATURE", str(DEFAULT_TEMPERATURE)))
        self.default_top_p = float(os.getenv("LOCAL_LLM_TOP_P", str(DEFAULT_TOP_P)))
        self.default_repetition_penalty = float(
            os.getenv("LOCAL_LLM_REPETITION_PENALTY", str(DEFAULT_REPETITION_PENALTY))
        )
        self.disable_thinking = os.getenv("LOCAL_LLM_DISABLE_THINKING", "true").lower() not in {"0", "false", "no"}

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            record_llm_attempt(retry=attempt > 0)
            try:
                request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = LocalLLMError(
                    f"{self.provider_label} HTTP {exc.code}: {body[:500]}"
                )
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(attempt + 1)

        raise LocalLLMError(
            f"Không kết nối được {self.provider_label} tại {url}. "
            f"{'Hãy kiểm tra llama-server. ' if self.provider == 'local' else ''}"
            f"Chi tiết: {last_error}"
        ) from last_error

    def ensure_available(self) -> None:
        if not self.available_models():
            raise LocalLLMError(
                f"{self.provider_label} trả về /models không đúng định dạng OpenAI."
            )

    def available_models(self) -> list[str]:
        """Return model ids exposed by the local OpenAI-compatible server."""
        response = self._request("models")
        raw_models = response.get("data")
        if not isinstance(raw_models, list):
            return []
        return [str(item.get("id", "")).strip() for item in raw_models if isinstance(item, dict) and item.get("id")]

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        repetition_penalty: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        with trace_llm_component(system_prompt):
            chat = self.chat(
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                top_p=top_p,
                repetition_penalty=repetition_penalty,
                max_tokens=max_tokens,
                json_mode=json_mode,
                json_schema=json_schema,
            )
            return chat.send_message(prompt)

    def chat(
        self,
        *,
        system_prompt: str = "",
        tools: list[Callable[..., str]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        repetition_penalty: float | None = None,
        max_tokens: int | None = None,
        max_tool_calls: int = 3,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> "LocalChat":
        effective_temperature = self.default_temperature if temperature is None else temperature
        sampling_enabled = effective_temperature > 0 and not json_mode and json_schema is None
        effective_top_p = top_p if top_p is not None else self.default_top_p if sampling_enabled else 1.0
        effective_repetition_penalty = (
            repetition_penalty
            if repetition_penalty is not None
            else self.default_repetition_penalty if sampling_enabled else 1.0
        )
        return LocalChat(
            client=self,
            system_prompt=system_prompt,
            tools=tools or [],
            model=model or self.model,
            temperature=effective_temperature,
            top_p=effective_top_p,
            repetition_penalty=effective_repetition_penalty,
            max_tokens=max_tokens or self.default_max_tokens,
            max_tool_calls=max_tool_calls,
            json_mode=json_mode,
            json_schema=json_schema,
        )


class LocalChat:
    def __init__(
        self,
        *,
        client: LocalLLMClient,
        system_prompt: str,
        tools: list[Callable[..., str]],
        model: str,
        temperature: float,
        top_p: float,
        repetition_penalty: float,
        max_tokens: int,
        max_tool_calls: int,
        json_mode: bool,
        json_schema: dict[str, Any] | None,
    ) -> None:
        self.client = client
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.repetition_penalty = repetition_penalty
        self.max_tokens = max_tokens
        self.max_tool_calls = max_tool_calls
        self.json_mode = json_mode
        self.json_schema = json_schema
        self.tool_functions = {func.__name__: func for func in tools}
        self.tool_definitions = [tool_schema(func) for func in tools]
        self.tool_contexts: list[str] = []
        self.messages: list[dict[str, Any]] = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

    def get_history(self) -> list[dict[str, Any]]:
        return list(self.messages)

    @staticmethod
    def _inline_tool_calls(content: str) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for index, raw in enumerate(re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content or "", re.DOTALL), 1):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if payload.get("name"):
                calls.append(
                    {
                        "id": f"inline_{index}",
                        "type": "function",
                        "function": {
                            "name": payload["name"],
                            "arguments": json.dumps(payload.get("arguments", {}), ensure_ascii=False),
                        },
                    }
                )
        return calls

    def _execute_tool(self, tool_call: dict[str, Any]) -> str:
        function_call = tool_call.get("function") or {}
        name = str(function_call.get("name", ""))
        func = self.tool_functions.get(name)
        if func is None:
            return f"Lỗi: Tool '{name}' không tồn tại."

        raw_arguments = function_call.get("arguments", "{}")
        try:
            arguments = raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments or "{}")
            if not isinstance(arguments, dict):
                raise TypeError("arguments phải là object")
            result = str(func(**arguments))
        except Exception as exc:
            result = f"Lỗi khi gọi {name}: {exc}"

        for context in split_source_records(result):
            if context not in self.tool_contexts:
                self.tool_contexts.append(context)
        return result

    def send_message(self, message: str) -> LLMResponse:
        self.messages.append({"role": "user", "content": message})
        total_tool_calls = 0

        while True:
            messages = list(self.messages)
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "stream": False,
            }
            payload["temperature"] = self.temperature
            payload["top_p"] = self.top_p
            payload["repeat_penalty"] = self.repetition_penalty
            if self.client.disable_thinking:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            if self.json_schema is not None:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_response",
                        "strict": True,
                        "schema": self.json_schema,
                    },
                }
            elif self.json_mode:
                payload["response_format"] = {"type": "json_object"}
            if self.tool_definitions and total_tool_calls < self.max_tool_calls:
                payload["tools"] = self.tool_definitions
                payload["tool_choice"] = "auto"

            data = self.client._request("chat/completions", payload)
            choices = data.get("choices") or []
            if not choices:
                raise LocalLLMError(
                    f"{self.client.provider_label} không trả choices: {str(data)[:500]}"
                )
            response_message = choices[0].get("message") or {}
            content = response_message.get("content") or ""
            tool_calls = response_message.get("tool_calls") or self._inline_tool_calls(content)

            assistant_message: dict[str, Any] = {"role": "assistant", "content": content or None}
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            self.messages.append(assistant_message)

            if not tool_calls:
                return LLMResponse(_strip_thinking(content))

            for tool_call in tool_calls:
                total_tool_calls += 1
                if total_tool_calls > self.max_tool_calls:
                    result = "Đã đạt giới hạn lượt tra cứu. Hãy tổng hợp từ chứng cứ hiện có."
                else:
                    result = self._execute_tool(tool_call)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", f"call_{total_tool_calls}"),
                        "content": result,
                    }
                )


def create_llm_client(
    provider: str = "local",
    *,
    model: str | None = None,
    timeout: int | None = None,
) -> LocalLLMClient:
    """Create the only backend shipped in the submission."""

    if str(provider or "local").strip().casefold() != "local":
        raise ValueError("Bản nộp chỉ hỗ trợ máy chủ mô hình cục bộ.")
    return LocalLLMClient(model=model, timeout=timeout)
