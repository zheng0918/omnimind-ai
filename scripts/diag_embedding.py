"""诊断脚本：直接调用百炼 embedding 接口，确认 key/额度/连通性。

用法：在项目根目录执行 `python scripts/diag_embedding.py`
读取与服务相同的 .env 配置。欠费会返回明确错误码（Arrearage/AccountAbnormal）。
"""

from __future__ import annotations

import time

from dashscope import TextEmbedding

from app.core.config import get_settings


def main() -> None:
    s = get_settings()
    key = s.dashscope_api_key
    masked = f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "(too short / placeholder)"
    print(f"model      = {s.dashscope_embed_model}")
    print(f"dim        = {s.embed_dim}")
    print(f"timeout_s  = {s.dashscope_timeout_s}")
    print(f"api_key    = {masked}")
    if key == "placeholder":
        print("\n[FATAL] DASHSCOPE_API_KEY 未注入，仍是 placeholder。")
        return

    print("\n调用 TextEmbedding.call ...")
    started = time.monotonic()
    resp = TextEmbedding.call(
        model=s.dashscope_embed_model,
        input=["帮我检索技术栈"],
        dimension=s.embed_dim,
        api_key=key,
    )
    cost = int((time.monotonic() - started) * 1000)
    print(f"cost_ms      = {cost}")
    print(f"status_code  = {getattr(resp, 'status_code', None)}")
    print(f"code         = {getattr(resp, 'code', None)}")
    print(f"message      = {getattr(resp, 'message', None)}")
    print(f"request_id   = {getattr(resp, 'request_id', None)}")

    if getattr(resp, "status_code", None) == 200:
        vecs = resp.output["embeddings"]
        print(f"\n[OK] 返回 {len(vecs)} 个向量，维度 {len(vecs[0]['embedding'])}。模型可用、未欠费。")
    else:
        print("\n[FAIL] 调用未成功。常见 code 含义：")
        print("  Arrearage / AccountAbnormal -> 账户欠费/异常")
        print("  InvalidApiKey / Unauthorized -> key 错误")
        print("  Throttling.RateQuota        -> 限流/配额")


if __name__ == "__main__":
    main()
