import json

import httpx
import pytest
from openai import OpenAI

from learngraph_review.errors import ReviewError
from learngraph_review.gateway import OpenAIGateway, Settings, estimate_cost
from learngraph_review.models import GModelResult


def response_body():
    return {
        "id": "resp_offline",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "gpt-5-nano-2025-08-07",
        "output": [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [],
                        "text": json.dumps(
                            {
                                "summary": "transport fixture",
                                "issues": [],
                                "checked_objectives": ["目标"],
                            }
                        ),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 30,
            "total_tokens": 130,
            "input_tokens_details": {"cached_tokens": 20},
            "output_tokens_details": {"reasoning_tokens": 10},
        },
    }


def make_gateway(handler, settings=None):
    client = OpenAI(
        api_key="offline-test-not-a-real-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return OpenAIGateway(settings or Settings(), client=client)


def run(gateway, model="gpt-5-nano"):
    return gateway.run(
        model=model, instructions="审查指令", payload={"data": "样例"}, schema=GModelResult
    )


def test_official_sdk_serializes_strict_responses_schema():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.url.path == "/v1/responses"
        return httpx.Response(200, json=response_body())

    result, usage = run(make_gateway(handler))
    request = requests[0]
    assert request["store"] is False
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert request["reasoning"] == {"effort": "minimal"}
    assert request["max_output_tokens"] == 6000
    assert result.checked_objectives == ["目标"]
    assert usage.cached_input_tokens == 20 and usage.reasoning_tokens == 10
    assert usage.estimated_cost_usd == pytest.approx(0.0000161)


@pytest.mark.parametrize("failure", ["refusal", "incomplete", "invalid_json", "invalid_schema"])
def test_model_failure_never_returns_approval(failure):
    body = response_body()
    if failure == "refusal":
        body["output"][0]["content"] = [{"type": "refusal", "refusal": "cannot review"}]
    elif failure == "incomplete":
        body["status"] = "incomplete"
        body["incomplete_details"] = {"reason": "max_output_tokens"}
    elif failure == "invalid_json":
        body["output"][0]["content"][0]["text"] = "not JSON"
    else:
        body["output"][0]["content"][0]["text"] = '{"summary":"missing fields"}'
    with pytest.raises(ReviewError):
        run(make_gateway(lambda _: httpx.Response(200, json=body)))


@pytest.mark.parametrize("failure", ["429", "timeout"])
def test_api_error_is_sanitized(failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private-user-text-do-not-log", request=request)
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": "private-user-text-do-not-log",
                    "type": "rate_limit_error",
                }
            },
        )

    with pytest.raises(ReviewError) as error:
        run(make_gateway(handler))
    assert "private-user-text" not in str(error.value)


def test_input_budget_is_checked_before_any_http_call():
    def handler(_):
        pytest.fail("over-budget input must not call API")

    gateway = make_gateway(handler, Settings(max_input_chars=100))
    with pytest.raises(ReviewError, match="预算"):
        gateway.run(
            model="gpt-5-nano",
            instructions="review",
            payload={"x": "中" * 200},
            schema=GModelResult,
        )


def test_no_key_fails_without_network(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ReviewError, match="OPENAI_API_KEY"):
        OpenAIGateway()


def test_non_reasoning_model_omits_reasoning_parameter():
    def handler(request):
        assert "reasoning" not in json.loads(request.content)
        return httpx.Response(200, json=response_body())

    _, usage = run(make_gateway(handler), model="gpt-4o-mini")
    assert usage.estimated_cost_usd is None


def test_estimate_counts_reasoning_as_part_of_output_not_twice():
    assert estimate_cost("gpt-5-nano", 1_000_000, 0, 1_000_000) == pytest.approx(0.45)
    assert estimate_cost("custom-model", 100, 0, 20) is None
