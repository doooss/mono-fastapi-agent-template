"""Upstream failures -> BackendError with a client-safe message. Details go to the log only."""

import logging

import anthropic

from agent_core.runtime import BackendError

logger = logging.getLogger("agent_core.backends")


def from_anthropic(exc: anthropic.AnthropicError) -> BackendError:
    logger.warning("anthropic call failed", extra={"error": type(exc).__name__}, exc_info=exc)
    match exc:
        case anthropic.RateLimitError():
            return BackendError("UPSTREAM_RATE_LIMITED", "요청이 많아 잠시 후 다시 시도해 주세요.")
        case anthropic.InternalServerError() | anthropic.APIConnectionError():
            return BackendError(
                "UPSTREAM_UNAVAILABLE", "모델 서비스에 일시적으로 연결할 수 없습니다."
            )
        case _:
            return BackendError("UPSTREAM_ERROR", "모델 호출에 실패했습니다.")
