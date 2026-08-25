"""同步版的基础重试机制，语义保持与 Mini-Agent 一致。"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryConfig:
    """LLM API 请求的重试配置。"""

    def __init__(
        self,
        enabled: bool = True,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        self.enabled = enabled
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_exceptions = retryable_exceptions

    def calculate_delay(self, attempt: int) -> float:
        delay = self.initial_delay * (self.exponential_base**attempt)
        return min(delay, self.max_delay)


class RetryExhaustedError(Exception):
    """所有重试都失败后的最终异常。"""

    def __init__(self, last_exception: Exception, attempts: int) -> None:
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(
            f"Retry failed after {attempts} attempts. "
            f"Last error: {last_exception}"
        )


def retry(
    config: RetryConfig | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """为同步函数提供有界指数退避重试。"""

    retry_config = config or RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            if not retry_config.enabled:
                return func(*args, **kwargs)

            for attempt in range(retry_config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retry_config.retryable_exceptions as error:
                    if attempt >= retry_config.max_retries:
                        logger.error(
                            "Function %s retry failed after %s retries",
                            func.__name__,
                            retry_config.max_retries,
                        )
                        raise RetryExhaustedError(error, attempt + 1) from error

                    delay = retry_config.calculate_delay(attempt)
                    if on_retry is not None:
                        on_retry(error, attempt + 1)
                    time.sleep(delay)

            raise RuntimeError("Retry loop exited unexpectedly")

        return wrapper

    return decorator
