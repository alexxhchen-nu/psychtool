"""psychtool 端到端 demo：合成个案 TRAIN-A 完整跑一遍。

用法：
    python scripts/demo.py

模型默认 linksub deepseek-v4-pro（OpenAI 兼容）；密钥从环境变量 PSYCHTOOL_API_KEY
读取（api_key 不入库）。全程只处理合成材料。
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from psychtool.core.workspace import init_workspace, import_material
from psychtool.core.claims import add_claim, list_claims
from psychtool.core.draft import generate_draft
from psychtool.core.review import review_summary
from psychtool.config import Config
from psychtool.gateway.http import http_transport
from psychtool.gateway.orchestrator import EgressOrchestrator, SyntheticApproval


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-auto", action="store_true")
    parser.add_argument("--approval-reason")
    args = parser.parse_args()
    # 模型配置：优先环境变量，缺省 linksub
    cfg = Config(
        base_url=os.environ.get("PSYCHTOOL_BASE_URL", "https://linksub.fun/v1"),
        model=os.environ.get("PSYCHTOOL_MODEL", "deepseek-v4-pro"),
        data_tier="synthetic",
        api_key=os.environ.get("PSYCHTOOL_API_KEY"),
    )
    can_generate = bool(
        cfg.api_key
        and args.synthetic_auto
        and args.approval_reason
        and args.approval_reason.strip()
    )
    if not cfg.api_key:
        print("⚠  未设置 PSYCHTOOL_API_KEY，跳过真实模型起草（只演示到候选陈述）")
    elif not can_generate:
        print("⚠  模型起草要求 --synthetic-auto 与非空 --approval-reason，已跳过")

    ws = init_workspace(Path(tempfile.mkdtemp()) / "TRAIN-A", case_id="TRAIN-A")

    # 1. 导入三个信息提供者的材料
    import_material(ws, material_id="A-YOUTH", title="本人访谈", provider="本人", date="2026-10-12",
                    text="我在九月开学后开始觉得作业用时变长，但科学社活动一直能按时参加。\n\n我觉得数学作业比以前花时间；我没有记录具体时长。")
    import_material(ws, material_id="A-CAREGIVER", title="照护者访谈", provider="照护者", date="2026-10-13",
                    text="我觉得作业变慢从七月就开始了，不是九月。\n\n我没有看到学校课堂上的情况。")
    print("✅ 1. 导入材料：A-YOUTH、A-CAREGIVER（段落已切分、版本化）\n")

    # 2. 候选陈述（归属 + 来源定位）
    add_claim(ws, claim_id="A-F1", source_document_id="A-YOUTH", source_version=1, source_passage_id="A-Y1",
              provider_role="self_report", observation_setting="访谈练习", record_time="2026-10-12",
              category="client_statement", topic="onset", text="本人报告九月开学后作业用时变长，同时仍按时参加科学社。")
    add_claim(ws, claim_id="A-F3", source_document_id="A-CAREGIVER", source_version=1, source_passage_id="A-C1",
              provider_role="other_report", observation_setting="家庭观察练习", record_time="2026-10-13",
              category="client_statement", topic="onset", text="照护者把变化开始时间描述为七月，与本人的九月说明不同。")
    print("✅ 2. 候选陈述：")
    for c in list_claims(ws):
        print(f"   [{c.id}] 归属={c.provider_role} 来源={c.source_document_id} v{c.source_version} {c.source_passage_id}")
        print(f"      {c.text}")
    print()

    # 3. 审阅：矛盾保留
    print("✅ 3. 审阅（矛盾）：", review_summary(ws)["conflicts"], "\n")

    # 4. 真实模型起草 + 来源索引
    if can_generate:
        runner = EgressOrchestrator(
            config=cfg,
            approval=SyntheticApproval(reason=args.approval_reason),
            transport=http_transport,
        )
        draft = generate_draft(
            ws,
            draft_id="d1",
            claim_ids=["A-F1", "A-F3"],
            instructions="写一段背景段落，保留归属与矛盾，缺失标未知",
            runner=runner,
        )
        print("✅ 4. 真实模型起草：")
        print("   " + draft.text.replace("\n", "\n   ") + "\n")
        print("   ## 来源索引")
        for c in draft.citations:
            print(f"   [{c.claim_id}] {c.source_document_id} v{c.source_version} 段落 {c.source_passage_id}")
    else:
        print("（跳过 4：模型起草前提未满足，原因见上方提示）")

    print("\n完成。")


if __name__ == "__main__":
    main()
