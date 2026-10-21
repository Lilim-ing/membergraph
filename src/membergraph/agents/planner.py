from __future__ import annotations

from ..contracts import SubQuestion
from .base import AgentContext, BaseAgent
from ..blackboard import Blackboard
from ..tools.metrics import list_metrics

SYSTEM = (
    "你是会员增长团队的规划者。把一个模糊的业务议题拆成 3-4 个可被数据验证的子问题。"
    "每个子问题必须绑定一个已注册指标和一个允许的维度。只输出 JSON。"
)


class Planner(BaseAgent):
    name = "planner"
    role = "planner"
    system = SYSTEM

    def run(self, ctx: AgentContext, bb: Blackboard, **kwargs) -> None:
        topic = bb.read("topic", "")
        data = ctx.ask(self.role, self.system, {"topic": topic, "metrics": list_metrics()})
        questions = [SubQuestion(**q) for q in data.get("sub_questions", [])]
        if not questions:
            raise ValueError("planner returned no sub-questions")
        bb.write("sub_questions", [q.model_dump() for q in questions], self.name)
        ctx.tracer.emit(
            "plan",
            agent=self.name,
            count=len(questions),
            metrics=[q.metric for q in questions],
        )
