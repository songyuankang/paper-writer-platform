"""大纲章节职责的确定性验证器。

目录结构在写入草稿和启动全文流水线前均可调用本模块。它不重写用户目录，
只输出可审计的角色分配与异常；自动修复由既有 outline 生成链路完成。
"""
from __future__ import annotations

import re
from typing import Any

from app.draft.outline_quality import classify_research


ROLE_TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "technical": {
        "introduction": ("绪论", "引言", "背景", "意义", "现状", "需求"),
        "theory": ("理论", "关键技术", "相关技术", "基础"),
        "design": ("算法", "模型", "方法", "方案", "设计", "系统"),
        "validation": ("实验", "测试", "验证", "性能", "对比", "消融"),
        "conclusion": ("结论", "总结", "展望"),
    },
    "engineering": {
        "introduction": ("绪论", "引言", "背景", "意义", "需求", "现状"),
        "theory": ("理论", "关键技术", "基础", "需求分析"),
        "design": ("总体设计", "详细设计", "架构", "模块", "系统设计", "实现", "部署"),
        "validation": ("测试", "实验", "验证", "评估", "运行结果", "性能"),
        "conclusion": ("结论", "总结", "展望"),
    },
    "empirical": {
        "introduction": ("绪论", "引言", "背景", "意义", "文献", "研究内容", "研究思路"),
        "theory": ("理论", "机制", "假设", "文献综述"),
        "design": ("研究设计", "数据", "变量", "模型", "样本", "计量"),
        "empirical": ("实证", "基准回归", "稳健", "异质", "机制检验", "结果"),
        "conclusion": ("结论", "政策", "建议", "局限", "展望"),
    },
    "empirical_economics": {
        "introduction": ("绪论", "引言", "背景", "意义", "文献", "研究内容", "研究思路"),
        "theory": ("理论基础", "作用机制", "传导机制", "研究假设", "理论分析", "文献综述"),
        "design": ("研究设计", "数据", "变量", "模型设定", "计量模型", "样本"),
        "empirical": ("基准回归", "稳健性", "异质性", "机制检验", "实证结果", "回归结果"),
        "conclusion": ("结论", "政策", "局限", "展望"),
    },
}

_INTRO_FORBIDDEN = {
    "technical": ("实验", "测试", "性能对比", "消融", "结论", "总结与展望"),
    "engineering": ("详细设计", "系统实现", "部署", "测试", "结论", "总结与展望"),
    "empirical": ("研究假设", "研究设计", "数据", "变量", "回归", "实证", "稳健", "异质", "结论", "政策建议"),
    "empirical_economics": ("理论基础", "作用机制", "研究假设", "研究设计", "数据", "变量", "模型设定", "计量模型", "基准回归", "回归", "稳健", "异质", "机制检验", "实证", "结论", "政策建议", "局限"),
}
_ECONOMIC_TERMS = ("共同富裕", "收入", "分配", "经济", "金融", "财政", "基尼", "泰尔", "居民", "就业", "产业", "贸易")
_ENGINEERING_TERMS = ("系统设计", "系统实现", "工程", "平台", "装置", "部署", "架构")


def _norm(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _profile(paper_info: dict[str, Any]) -> str:
    text = _norm(" ".join([
        str(paper_info.get("title") or ""), str(paper_info.get("abstract") or ""),
        " ".join(str(item) for item in paper_info.get("keywords") or []),
    ]))
    research_type = classify_research(paper_info)
    if research_type == "empirical" and any(_norm(term) in text for term in _ECONOMIC_TERMS):
        return "empirical_economics"
    if research_type == "technical" and any(_norm(term) in text for term in _ENGINEERING_TERMS):
        return "engineering"
    return research_type if research_type in ROLE_TEMPLATES else "technical"


def _section_text(section: dict[str, Any]) -> str:
    return _norm(" ".join([str(section.get("title") or ""), str(section.get("gist") or ""), str(section.get("purpose") or "")]))


def _top_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots = [item for item in sections if int(item.get("level") or 1) == 1]
    if roots:
        return roots
    # 旧草稿有时只保存叶子 section（如 1-1、2-1），按 ID 根前缀构造逻辑章节，
    # 仅用于验证，绝不改写原有 sections。
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in sections:
        root_id = str(item.get("id") or "").split("-", 1)[0]
        if root_id:
            grouped.setdefault(root_id, []).append(item)
    return [{
        "id": root_id,
        "number": root_id,
        "level": 1,
        "title": " ".join(str(item.get("title") or "") for item in values),
        "gist": " ".join(str(item.get("gist") or "") for item in values),
    } for root_id, values in grouped.items()]


def _root_and_descendants(sections: list[dict[str, Any]], root_id: str) -> list[dict[str, Any]]:
    return [item for item in sections if str(item.get("id") or "") == root_id or str(item.get("id") or "").startswith(root_id + "-")]


class OutlineRoleValidator:
    """按论文研究范式验证章节职责并给出可审计问题码。"""

    @classmethod
    def validate(cls, paper_info: dict[str, Any], sections: list[dict[str, Any]]) -> dict[str, Any]:
        profile = _profile(paper_info)
        template = ROLE_TEMPLATES[profile]
        top_sections = _top_sections(sections)
        assignments: list[dict[str, Any]] = []
        for section in top_sections:
            text = _section_text(section)
            matched = [role for role, terms in template.items() if any(_norm(term) in text for term in terms)]
            assignments.append({
                "section_id": str(section.get("id") or ""),
                "number": str(section.get("number") or ""),
                "title": str(section.get("title") or ""),
                "roles": matched,
            })

        issues: list[dict[str, Any]] = []
        covered_roles = {role for assignment in assignments for role in assignment["roles"]}
        missing_roles = [role for role in template if role not in covered_roles]
        if missing_roles:
            issues.append({
                "code": "missing_required_roles",
                "severity": "high",
                "message": "缺少必要章节职责：" + "、".join(missing_roles) + "。",
                "roles": missing_roles,
                "section_ids": [],
            })

        first = top_sections[0] if top_sections else None
        if first:
            first_id = str(first.get("id") or "")
            first_nodes = _root_and_descendants(sections, first_id)
            forbidden_hits: list[dict[str, str]] = []
            for node in first_nodes:
                text = _section_text(node)
                matched = next((term for term in _INTRO_FORBIDDEN[profile] if _norm(term) in text), "")
                if matched:
                    forbidden_hits.append({
                        "section_id": str(node.get("id") or ""),
                        "number": str(node.get("number") or ""),
                        "title": str(node.get("title") or ""),
                        "matched_role": matched,
                    })
            # 单个“理论”或“文献”提示不直接否决；多种主体职责同时进入绪论才是 P0 异常。
            distinct = {item["matched_role"] for item in forbidden_hits}
            if len(distinct) >= 3:
                issues.append({
                    "code": "introduction_role_overload",
                    "severity": "critical",
                    "message": "第一章同时承担多个后续主体职责，不能继续全文生成。",
                    "roles": sorted(distinct),
                    "section_ids": [item["section_id"] for item in forbidden_hits],
                    "conflicts": forbidden_hits,
                })
        else:
            issues.append({
                "code": "missing_introduction",
                "severity": "critical",
                "message": "目录没有可识别的第一章。",
                "roles": ["introduction"],
                "section_ids": [],
            })

        critical = [item for item in issues if item.get("severity") == "critical"]
        return {
            "version": 1,
            "profile": profile,
            "valid": not issues,
            "requires_repair": bool(critical),
            "requires_user_confirmation": bool(issues),
            "role_assignments": assignments,
            "covered_roles": sorted(covered_roles),
            "issues": issues,
        }

    @classmethod
    def repair_instruction(cls, validation: dict[str, Any]) -> str:
        profile = str(validation.get("profile") or "empirical")
        if profile == "empirical_economics":
            return (
                "上一版目录未通过经济学实证论文的章节职责校验。请重建完整目录："
                "第一章仅含背景、意义、文献与研究内容；第二章包含理论基础、机制和假设；"
                "第三章包含数据、变量和模型；第四章包含基准回归、稳健性、异质性和机制；"
                "第五章包含结论、政策与局限。不得把后续主体职责放入第一章。"
            )
        return (
            "上一版目录未通过章节职责校验。请保持第一章为背景、意义、现状和研究内容，"
            "将理论/设计、验证/实证和结论分别放入后续独立章节；只返回合法 sections JSON。"
        )
