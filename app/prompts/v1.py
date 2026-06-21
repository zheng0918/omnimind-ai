"""提示词装配（v1）——问答 RAG / 智能审查 / 智能编写。

全局约定（所有提示词共同遵循）：
- 仅依据传入的【资料】/【片段】/【招标文件】作答，不引入外部知识、不臆造数据
  （合规要求，见 finalRequirements §6.1：所有 AI 输出需人工最终确认）。
- JSON Mode 提示词只输出单个 JSON 对象，字段名与枚举严格按各函数说明，
  不得包含解释文字或 Markdown 代码围栏；枚举值大小写敏感，调用方做白名单兜底。
- 问答上下文按 token 上限截断（spec §10.2：6000，留 2000 给输出）；历史保留最近若干轮。
- 改动提示词须同步 PROMPT_VERSION（落库 prompt_ver 便于回溯）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.llm.base import ChatMessage
from app.utils.tokens import count_tokens, truncate_to_tokens

if TYPE_CHECKING:
    from app.rag.retriever import RetrievedBlock

PROMPT_VERSION = "v1"

_QA_SYSTEM = (
    "你是企业知识库智能助手，严格依据下方【资料】回答用户问题。\n"
    "【必须】\n"
    "- 仅使用【资料】中的信息作答，不得引入外部知识或用常识补全；\n"
    "- 每个事实性陈述后用方括号标注来源编号，如 [1]、[2]，编号须对应【资料】序号；"
    "同一结论有多条来源时可并列标注，如 [1][3]；\n"
    "- 回答语言与用户提问保持一致，简洁、准确。\n"
    "【禁止】\n"
    "- 编造【资料】中不存在的信息、数据或结论；\n"
    "- 使用超出【资料】序号范围或不存在的引用编号；\n"
    "- 在没有任何相关资料时强行作答。\n"
    "【资料不足或矛盾时】\n"
    '- 资料不足以支撑回答时，如实说明"根据现有资料无法回答"，并可指出还缺少哪类信息；\n'
    "- 资料相互矛盾时，并列呈现分歧并各自标注来源，不擅自裁决。"
)

_REWRITE_SYSTEM = (
    "你是检索查询改写助手。根据对话历史，把用户最新提问改写为一个可独立检索的完整问题。\n"
    "【必须】\n"
    '- 补全指代（"它/这个/上述"等）、省略的主语与上下文；\n'
    "- 保留专有名词、型号、术语与关键词的原文，不要替换为近义词（否则影响检索召回）；\n"
    "- 与原提问使用同一语言，且只输出单个问题。\n"
    "【禁止】\n"
    "- 回答问题本身；\n"
    "- 添加任何解释、前缀、引号或修饰；\n"
    "- 改变原意或扩展为无关内容。\n"
    "【边界】最新提问本身已是完整独立问题时，原样输出。\n"
    "只输出改写后的问题文本。"
)


def build_query_rewrite_messages(
    history: list[ChatMessage], query: str
) -> list[ChatMessage]:
    """装配 query 改写消息。无历史时仍可调用（模型通常原样返回）。"""
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    user = f"对话历史：\n{convo}\n\n最新提问：{query}\n\n改写后的问题：" if convo else query
    return [
        ChatMessage(role="system", content=_REWRITE_SYSTEM),
        ChatMessage(role="user", content=user),
    ]


def _format_blocks(blocks: list[RetrievedBlock], token_budget: int) -> str:
    """把父块拼成带编号的资料文本，受 token 预算约束（超出则丢弃靠后的块）。"""
    lines: list[str] = []
    used = 0
    for idx, block in enumerate(blocks, start=1):
        page = f"，第{block.page}页" if block.page is not None else ""
        header = f"[{idx}]（文档{block.document_id}{page}）"
        entry = f"{header}\n{block.text}"
        cost = count_tokens(entry)
        if used + cost > token_budget and lines:
            break
        if used + cost > token_budget:
            entry = f"{header}\n{truncate_to_tokens(block.text, max(token_budget - used - 16, 1))}"
        lines.append(entry)
        used += cost
    return "\n\n".join(lines)


def build_qa_messages(
    blocks: list[RetrievedBlock],
    history: list[ChatMessage],
    query: str,
    *,
    context_token_limit: int,
) -> list[ChatMessage]:
    """装配问答消息：system + 资料 + 历史 + 提问，总上下文受 token 上限约束。"""
    system_tokens = count_tokens(_QA_SYSTEM)
    query_tokens = count_tokens(query)
    history_tokens = sum(count_tokens(m["content"]) for m in history)
    block_budget = max(context_token_limit - system_tokens - query_tokens - history_tokens, 1)
    materials = _format_blocks(blocks, block_budget)

    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=f"{_QA_SYSTEM}\n\n【资料】\n{materials}"),
    ]
    messages.extend(history)
    messages.append(ChatMessage(role="user", content=query))
    return messages


# ---- 智能审查（REQ-REV）----

_CHECKLIST_EXTRACT_SYSTEM = (
    "你是招投标审查专家。从【招标文件】中抽取投标方必须响应的关键要求，形成审查清单。\n"
    "【必须】\n"
    "- 只输出一个 JSON 对象："
    '{"items":[{"title":"要点简述","requirement":"判定依据（投标文件应如何响应，须可核查）",'
    '"riskType":"missing|risk|suggestion|format"}]}；\n'
    "- riskType 取且仅取 missing/risk/suggestion/format 之一；\n"
    "- 聚焦实质性、可核查的硬性要求；最多 20 条。\n"
    "【禁止】\n"
    "- 输出 JSON 以外的任何内容（说明文字、Markdown 代码围栏等）；\n"
    "- 编造招标文件中没有的要求，或写成泛泛而谈的套话；\n"
    "- 超过 20 条，或输出空 title / 空 requirement。\n"
    "【必须参照】仅依据给定的【招标文件】原文。"
)

_RISK_JUDGE_SYSTEM = (
    "你是招投标合规审查助手。依据【审查要点】与判定依据，判断【投标文件片段】是否满足要求。\n"
    "【必须】\n"
    "- 只输出一个 JSON 对象："
    '{"severity":"HIGH|MEDIUM|PASS","riskType":"missing|risk|suggestion|format",'
    '"title":"风险简述","description":"具体说明问题或通过理由","originalText":"逐字摘自片段的原文或null",'
    '"suggestedText":"可执行的修改建议或null","confidence":0.0到1.0之间的小数}；\n'
    "- severity 判定：完全满足→PASS；存在缺失/不符且影响重大→HIGH；存在瑕疵或可优化建议→MEDIUM；\n"
    "- originalText 必须逐字摘录自【投标文件片段】，片段中无对应内容时置 null；\n"
    "- severity=PASS 时 suggestedText 置 null，不得为通过项附修改建议；\n"
    "- confidence 如实反映判断把握，且与 severity 一致——证据越充分值越高。\n"
    "【禁止】\n"
    "- 输出 JSON 以外的任何内容；\n"
    "- 臆造 originalText 或片段中不存在的事实；\n"
    "- 在证据缺失时仍给出高 confidence。\n"
    "【片段缺失时】片段为\"（未检索到相关内容）\"视为投标文件未响应该要求："
    "severity 通常为 HIGH、riskType=missing、originalText=null，description 说明未在文档中找到相应内容。\n"
    "【必须参照】仅依据给定的【审查要点】判定依据与【投标文件片段】。"
)


def build_checklist_extract_messages(tender_text: str) -> list[ChatMessage]:
    """装配招标文件清单抽取消息（JSON Mode）。"""
    return [
        ChatMessage(role="system", content=_CHECKLIST_EXTRACT_SYSTEM),
        ChatMessage(role="user", content=f"【招标文件】\n{tender_text}"),
    ]


def build_risk_judge_messages(
    item_title: str, requirement: str, evidence: str
) -> list[ChatMessage]:
    """装配单条要点的风险判定消息（JSON Mode）。"""
    user = (
        f"【审查要点】{item_title}\n判定依据：{requirement}\n\n"
        f"【投标文件片段】\n{evidence or '（未检索到相关内容）'}"
    )
    return [
        ChatMessage(role="system", content=_RISK_JUDGE_SYSTEM),
        ChatMessage(role="user", content=user),
    ]


# ---- 智能编写（REQ-WRT）----

_SCORE_POINT_SYSTEM = (
    "你是招投标方案编写专家。从【招标文件】中抽取评分点（投标方案需逐条响应的评审要素）。\n"
    "【必须】\n"
    "- 只输出一个 JSON 对象："
    '{"points":[{"pointText":"评分点描述","weight":分值数字或null}]}；\n'
    "- weight 取招标文件明确给出的分值数字，无明确分值时置 null；\n"
    "- 聚焦实质性、可响应的评审要素；最多 30 条。\n"
    "【禁止】\n"
    "- 输出 JSON 以外的任何内容；\n"
    "- 编造评分点，或将同一要素重复拆分；\n"
    "- 臆造 weight，或纳入纯格式性、与评分无关的条款。\n"
    "【必须参照】仅依据【招标文件】的评分办法与评审要素。"
)

_OUTLINE_SYSTEM = (
    "你是招投标方案编写专家。依据【评分点】与【参考素材】规划投标方案大纲。\n"
    "【必须】\n"
    "- 只输出一个 JSON 对象："
    '{"outline":[{"title":"章标题","sections":["小节标题1","小节标题2"]}]}；\n'
    "- 覆盖全部评分点——每个评分点至少由一个小节承接；\n"
    "- 结构符合投标方案常规逻辑（如项目理解、技术/施工方案、组织管理、质量安全、服务承诺等）；\n"
    "- 章不超过 8 个，每章小节不超过 6 个；小节标题具体、可独立成文。\n"
    "【禁止】\n"
    "- 输出 JSON 以外的任何内容；\n"
    '- 遗漏评分点，或使用"概述/其他"等空泛、无法独立成文的小节标题；\n'
    "- 超出章 / 小节数量上限。\n"
    "【必须参照】【评分点】为覆盖目标，【参考素材】为结构与命名参考。"
)

_SECTION_SYSTEM = (
    "你是招投标方案编写专家。基于【参考素材】撰写指定小节的正文。\n"
    "【必须】\n"
    "- 紧扣【待撰写小节】主题，实质响应【需响应的评分点】；\n"
    "- 正文使用 Markdown（可含小标题、要点列表、表格），条理清晰、专业书面；\n"
    "- 结合【项目参数】具体化表述（项目名称、规模、工期等）。\n"
    "【禁止】\n"
    '- 编造具体数字、资质、业绩、案例或承诺；素材缺失处用"[待补充：xxx]"占位，不得虚构；\n'
    '- 使用"竭诚/务必/保证100%/一定"等无依据的空泛承诺或营销腔；\n'
    '- 重复输出小节标题本身，或加入"以下是…""本节将…"等冗余说明；\n'
    "- 写入与本小节无关的内容。\n"
    "【必须参照】优先采用【参考素材】中的事实；素材为空时仅作一般性、专业性的框架陈述，"
    '并以"[待补充]"标注需企业填充处。'
)

_RESPONSE_CHECK_SYSTEM = (
    "你是招投标方案评审助手。判断【投标方案正文】对每个【评分点】的响应程度。\n"
    "【必须】\n"
    "- 只输出一个 JSON 对象："
    '{"results":[{"index":评分点序号,"responseStatus":"NONE|PARTIAL|RESPONDED"}]}；\n'
    "- 为每个评分点输出且仅输出一条结果，index 从 1 起且与输入顺序一致；\n"
    "- 判定标准：实质且完整响应→RESPONDED；有提及但不充分/不完整→PARTIAL；完全未涉及→NONE。\n"
    "【禁止】\n"
    "- 输出 JSON 以外的任何内容；\n"
    "- 漏判或重复评分点；\n"
    "- 仅因正文出现关键词就判为 RESPONDED（提及 ≠ 实质响应）。\n"
    "【必须参照】仅依据给定的【评分点】与【投标方案正文】。"
)


def build_score_point_extract_messages(tender_text: str) -> list[ChatMessage]:
    """装配招标文件评分点抽取消息（JSON Mode）。"""
    return [
        ChatMessage(role="system", content=_SCORE_POINT_SYSTEM),
        ChatMessage(role="user", content=f"【招标文件】\n{tender_text}"),
    ]


def build_outline_messages(score_points: list[str], materials: str) -> list[ChatMessage]:
    """装配大纲规划消息（JSON Mode）。"""
    points = "\n".join(f"- {p}" for p in score_points) or "（无明确评分点，按常规方案结构）"
    user = f"【评分点】\n{points}\n\n【参考素材】\n{materials or '（无）'}"
    return [
        ChatMessage(role="system", content=_OUTLINE_SYSTEM),
        ChatMessage(role="user", content=user),
    ]


def build_section_messages(
    chapter_title: str,
    section_title: str,
    score_points: list[str],
    materials: str,
    project_params: dict[str, str],
) -> list[ChatMessage]:
    """装配单个小节正文撰写消息（流式生成）。"""
    points = "\n".join(f"- {p}" for p in score_points) or "（无特定评分点）"
    params = (
        "\n".join(f"{k}：{v}" for k, v in project_params.items() if v)
        or "（未提供）"
    )
    user = (
        f"【所属章】{chapter_title}\n【待撰写小节】{section_title}\n\n"
        f"【需响应的评分点】\n{points}\n\n【项目参数】\n{params}\n\n"
        f"【参考素材】\n{materials or '（未检索到相关素材，请基于常规专业知识谨慎撰写）'}"
    )
    return [
        ChatMessage(role="system", content=_SECTION_SYSTEM),
        ChatMessage(role="user", content=user),
    ]


def build_response_check_messages(
    score_points: list[str], draft_text: str
) -> list[ChatMessage]:
    """装配评分点响应度校验消息（JSON Mode）。"""
    points = "\n".join(f"{i}. {p}" for i, p in enumerate(score_points, start=1))
    user = f"【评分点】\n{points}\n\n【投标方案正文】\n{draft_text or '（空）'}"
    return [
        ChatMessage(role="system", content=_RESPONSE_CHECK_SYSTEM),
        ChatMessage(role="user", content=user),
    ]
