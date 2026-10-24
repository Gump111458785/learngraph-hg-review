from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Protocol, TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from .errors import ReviewError
from .models import Usage

ResultT = TypeVar("ResultT", bound=BaseModel)


@dataclass(frozen=True)
class Settings:
    model_h: str = "gpt-5-nano"
    model_g: str = "gpt-5-nano"
    reasoning_effort: str = "minimal"
    max_output_tokens: int = 6000
    timeout_seconds: float = 60
    max_input_chars: int = 60_000

    def __post_init__(self) -> None:
        if self.max_output_tokens < 256 or self.timeout_seconds <= 0 or self.max_input_chars < 100:
            raise ValueError("输出 token、超时或输入长度配置无效")
        if not self.model_h.strip() or not self.model_g.strip():
            raise ValueError("模型名称不能为空")

    @classmethod
    def from_env(cls) -> Settings:
        # dotenv is loaded explicitly by CLI, never as an import side effect.
        return cls(
            model_h=os.getenv("OPENAI_MODEL_H", "gpt-5-nano"),
            model_g=os.getenv("OPENAI_MODEL_G", "gpt-5-nano"),
            reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "minimal"),
            max_output_tokens=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "6000")),
            timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60")),
        )


class Gateway(Protocol):
    def run(
        self,
        *,
        model: str,
        instructions: str,
        payload: dict,
        schema: type[ResultT],
    ) -> tuple[ResultT, Usage]: ...


# Reference estimates, USD per 1M tokens, verified 2026-10-24 on official model pages.
# Unknown models intentionally have no cost estimate. Actual billing remains authoritative.
PRICES = {
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
}


def estimate_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int):
    rates = PRICES.get(model)
    if rates is None:
        return None
    fresh, cached, output = rates
    return round(
        ((input_tokens - cached_tokens) * fresh + cached_tokens * cached + output_tokens * output)
        / 1_000_000,
        9,
    )


class OpenAIGateway:
    """Bounded calls through the official Responses API; failures never become approval."""

    def __init__(self, settings: Settings | None = None, *, client=None):
        self.settings = settings or Settings.from_env()
        if client is None and not os.getenv("OPENAI_API_KEY", "").strip():
            raise ReviewError(
                "未配置 OPENAI_API_KEY；请在本机 .env 中配置，不要发送到聊天或提交 Git"
            )
        self.client = client or OpenAI(timeout=self.settings.timeout_seconds, max_retries=1)

    def run(
        self,
        *,
        model: str,
        instructions: str,
        payload: dict,
        schema: type[ResultT],
    ) -> tuple[ResultT, Usage]:
        serialized = json.dumps(payload, ensure_ascii=False)
        if len(serialized) + len(instructions) > self.settings.max_input_chars:
            raise ReviewError("单次审查超过 60000 字符预算；请按资料或教学单元拆分，不能截断后通过")
        extra = {}
        effort = self.settings.reasoning_effort
        if model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")) and effort:
            extra["reasoning"] = {"effort": effort}
        start = time.monotonic()
        try:
            response = self.client.responses.parse(
                model=model,
                instructions=instructions,
                input=serialized,
                text_format=schema,
                store=False,
                max_output_tokens=self.settings.max_output_tokens,
                **extra,
            )
            if response.status != "completed" or response.output_parsed is None:
                raise ReviewError("模型未返回完整结构化审查（可能拒绝或输出被截断），本次不予放行")
            result = schema.model_validate(response.output_parsed)
        except (OpenAIError, ValidationError) as exc:
            # Do not print response bodies or SDK exception strings that may contain input data.
            message = f"OpenAI 调用或结构校验失败（{type(exc).__name__}），本次不予放行"
            raise ReviewError(message) from exc
        usage = response.usage
        if usage is None:
            raise ReviewError("API 未返回用量信息，无法记录完整运行审计")
        cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        details = getattr(usage, "output_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", 0) or 0
        return result, Usage(
            model=response.model,
            response_id=response.id,
            input_tokens=usage.input_tokens,
            cached_input_tokens=cached,
            output_tokens=usage.output_tokens,
            reasoning_tokens=reasoning,
            estimated_cost_usd=estimate_cost(
                model,
                usage.input_tokens,
                cached,
                usage.output_tokens,
            ),
            elapsed_seconds=round(time.monotonic() - start, 3),
        )
