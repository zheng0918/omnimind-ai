"""问答 RAG 的 prompt 装配（v1）。

包含：基于历史的 query 改写、问答上下文装配（system + 编号父块 + 历史 + 提问）。
上下文按 token 上限截断（spec §10.2：6000，留 2000 给输出）；历史保留最近若干轮。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.llm.base import ChatMessage
from app.utils.tokens import count_tokens, truncate_to_tokens

if TYPE_CHECKING:
    from app.rag.retriever import RetrievedBlock

PROMPT_VERSION = "v1"

_QA_SYSTEM = (
    "你是企业知识库智能助手。请严格依据下方提供的【资料】回答用户问题。\n"
    "要求：\n"
    "1. 只使用资料中的信息作答，不得编造；资料不足以回答时，如实说明"
    '"根据现有资料无法回答"。\n'
    "2. 在引用资料处用方括号标注来源编号，如 [1]、[2]，编号对应【资料】中的序号。\n"
    "3. 回答简洁、准确，使用与用户提问一致的语言。"
)

_REWRITE_SYSTEM = (
    "你是检索查询改写助手。根据对话历史，把用户最新的提问改写为一个"
    "可独立检索的完整问题：补全指代、省略的主语与上下文，不要回答问题，"
    "只输出改写后的问题本身，不加任何解释或引号。"
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
    "你是招投标审查专家。请从给定的【招标文件】中抽取投标方必须响应的关键要求，"
    "形成审查清单。只输出 JSON 对象，格式："
    '{"items":[{"title":"要点简述","requirement":"判定依据（投标文件应如何响应）",'
    '"riskType":"missing|risk|suggestion|format"}]}。'
    "最多 20 条，聚焦实质性、可核查的要求，不要泛泛而谈。"
)

_RISK_JUDGE_SYSTEM = (
    "你是招投标合规审查助手。请依据【审查要点】判断【投标文件片段】是否满足要求，"
    "只输出 JSON 对象，格式："
    '{"severity":"HIGH|MEDIUM|PASS","riskType":"missing|risk|suggestion|history|format",'
    '"title":"风险简述","description":"具体说明","originalText":"原文或null",'
    '"suggestedText":"修改建议或null","confidence":0.0到1.0之间的小数}。\n'
    "判定规则：完全满足→severity=PASS；存在缺失/不符且影响重大→HIGH；"
    "存在瑕疵或建议优化→MEDIUM。confidence 表示判断把握程度。"
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
    "你是招投标方案编写专家。请从给定的【招标文件】中抽取评分点（投标方案需逐条响应"
    "的评审要素），只输出 JSON 对象，格式："
    '{"points":[{"pointText":"评分点描述","weight":分值数字或null}]}。'
    "最多 30 条，聚焦实质性、可响应的评审要素，忽略纯格式性条款。"
)

_OUTLINE_SYSTEM = (
    "你是招投标方案编写专家。请依据【评分点】与【参考素材】规划投标方案大纲，"
    "覆盖全部评分点且结构清晰。只输出 JSON 对象，格式："
    '{"outline":[{"title":"章标题","sections":["小节标题1","小节标题2"]}]}。'
    "章不超过 8 个，每章小节不超过 6 个；小节标题应可独立成文。"
)

_SECTION_SYSTEM = (
    "你是招投标方案编写专家。请基于【参考素材】撰写指定小节的正文，要求："
    "1. 紧扣小节主题，充分响应相关评分点；2. 仅依据素材，不臆造数据；"
    "3. 用 Markdown 正文（可含小标题、要点列表），不要重复小节标题本身；"
    "4. 语言专业、条理清晰。"
)

_RESPONSE_CHECK_SYSTEM = (
    "你是招投标方案评审助手。请判断【投标方案正文】对每个【评分点】的响应程度，"
    "只输出 JSON 对象，格式："
    '{"results":[{"index":评分点序号,"responseStatus":"NONE|PARTIAL|RESPONDED"}]}。'
    "完全响应→RESPONDED；部分提及但不充分→PARTIAL；未涉及→NONE。序号从 1 起。"
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
