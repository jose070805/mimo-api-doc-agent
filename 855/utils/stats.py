"""Token 消耗统计与成本估算"""

import time
from dataclasses import dataclass, field

from core.mimo_client import TokenUsage


@dataclass
class CostEstimate:
    """基于常见定价层级的近似成本"""

    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    request_count: int
    duration_seconds: float

    def summary(self) -> str:
        return (
            f"\n📊 Token 消耗报告\n"
            f"  请求次数:         {self.request_count}\n"
            f"  Prompt tokens:    {self.prompt_tokens:,}\n"
            f"  Completion tokens: {self.completion_tokens:,}\n"
            f"  Total tokens:     {self.total_tokens:,}\n"
            f"  耗时:             {self.duration_seconds:.1f}s\n"
            f"  估算成本:         ${self.estimated_cost_usd:.4f} USD"
        )


class StatsTracker:
    """跨全流程的 Token 用量追踪"""

    def __init__(self, input_price_per_1k: float = 0.001, output_price_per_1k: float = 0.002):
        self._input_price = input_price_per_1k
        self._output_price = output_price_per_1k
        self._start = time.monotonic()
        self._agent_usage: dict[str, TokenUsage] = {}
        self._phase_times: dict[str, float] = {}

    def record(self, agent: str, usage: TokenUsage):
        self._agent_usage[agent] = usage

    def record_phase(self, phase: str, duration: float):
        self._phase_times[phase] = duration

    def total_usage(self) -> TokenUsage:
        total = TokenUsage()
        for u in self._agent_usage.values():
            total.merge(u)
        return total

    def estimate(self) -> CostEstimate:
        t = self.total_usage()
        cost = (
            t.prompt_tokens / 1000 * self._input_price
            + t.completion_tokens / 1000 * self._output_price
        )
        return CostEstimate(
            total_tokens=t.total_tokens,
            prompt_tokens=t.prompt_tokens,
            completion_tokens=t.completion_tokens,
            estimated_cost_usd=cost,
            request_count=t.request_count,
            duration_seconds=time.monotonic() - self._start,
        )

    def report(self) -> str:
        est = self.estimate()
        lines = [est.summary(), "", "各 Agent 用量:"]
        for name, usage in self._agent_usage.items():
            lines.append(f"  {name}: {usage.summary()}")
        if self._phase_times:
            lines.append("")
            lines.append("各阶段耗时:")
            for phase, dur in self._phase_times.items():
                lines.append(f"  {phase}: {dur:.1f}s")
        return "\n".join(lines)
