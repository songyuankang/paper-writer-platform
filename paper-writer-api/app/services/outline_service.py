"""论文大纲：生成（按论文类型的章节模板）、解析（用户大纲文本）、字数分配。"""

from __future__ import annotations

import re

from app.models.generate import OutlineChapter

OUTLINES: dict[str, list[str]] = {
    "课程论文": ["1 引言", "2 文献综述", "3 主体分析", "4 结论"],
    "毕业论文": ["1 绪论", "2 文献综述与理论基础", "3 研究设计", "4 结果与分析",
              "5 结论与展望"],
    "期刊论文": ["1 引言", "2 研究方法", "3 结果与分析", "4 讨论", "5 结论"],
    "实证研究": ["1 引言", "2 研究假设", "3 数据与模型", "4 实证结果",
              "5 稳健性检验与结论"],
    "文献综述": ["1 引言", "2 主题一：研究现状", "3 主题二：研究进展",
              "4 述评与展望"],
    "开题报告": ["1 选题背景与意义", "2 国内外研究现状", "3 研究内容与方法",
              "4 研究进度安排"],
}

CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

SUB_TEMPLATES: dict[str, list[str]] = {
    "引言": ["研究背景", "研究意义"],
    "绪论": ["研究背景", "研究意义"],
    "文献综述": ["国内外研究现状", "研究述评"],
    "主体分析": ["核心问题分析", "典型案例讨论"],
    "研究设计": ["研究思路", "研究方法与数据"],
    "研究方法": ["研究思路", "研究步骤"],
    "方法": ["研究方法", "研究步骤"],
    "结果与分析": ["主要结果", "结果讨论"],
    "实证结果": ["描述性统计", "回归分析结果"],
    "数据与模型": ["数据来源", "模型设定"],
    "研究假设": ["研究假设提出", "假设依据"],
    "稳健性检验": ["稳健性检验", "研究结论"],
    "讨论": ["结果解释", "与既有研究比较"],
    "结论": ["主要结论", "研究展望"],
    "述评与展望": ["现有研究不足", "未来研究方向"],
    "选题背景与意义": ["选题背景", "研究意义"],
    "国内外研究现状": ["国内研究现状", "国外研究现状"],
    "研究内容与方法": ["研究内容", "研究方法与技术路线"],
    "研究进度安排": ["进度计划", "预期成果"],
}


def to_cn_number(n: int) -> str:
    """1-20 转中文数字（用于 第X章）。"""
    if 1 <= n <= 10:
        return CN_NUM[n]
    if n < 20:
        return "十" + (CN_NUM[n - 10] if n > 10 else "")
    return "二十"


def sub_chapters_for(title: str) -> list[str]:
    for key, subs in SUB_TEMPLATES.items():
        if key in title:
            return subs
    return ["主要内容概述", "重点问题分析"]


def allocate_words(n_chapters: int, total: int) -> list[int]:
    """按章节位置分配字数：首尾略少、中间平均。"""
    if n_chapters <= 0:
        return []
    if n_chapters == 1:
        return [total]
    weights = [0.9] + [1.0] * (n_chapters - 2) + [0.9]
    weight_sum = sum(weights)
    allocated = [round(total * w / weight_sum) for w in weights]
    allocated[-1] += total - sum(allocated)
    return allocated


def generate_outline(title: str, major: str, paper_type: str,
                     word_count: int) -> dict:
    """根据标题/专业/论文类型/字数生成大纲（章节结构 + 预计字数分配）。"""
    tops = OUTLINES.get(paper_type, OUTLINES["课程论文"])
    tops = [t.split(" ", 1)[-1] for t in tops]  # 去掉 "1 " 前缀
    alloc = allocate_words(len(tops), word_count)
    chapters: list[OutlineChapter] = []
    lines: list[str] = []
    for i, top in enumerate(tops):
        label = f"第{to_cn_number(i + 1)}章 {top}"
        lines.append(label)
        chapters.append(OutlineChapter(title=label, level=1, word_count=alloc[i]))
        for j, sub in enumerate(sub_chapters_for(top)):
            sub_label = f"{i + 1}.{j + 1} {sub}"
            lines.append(sub_label)
            chapters.append(OutlineChapter(title=sub_label, level=2, word_count=0))
        lines.append("")
    return {
        "outline": "\n".join(lines).strip(),
        "chapters": [c.model_dump() for c in chapters],
    }


def parse_outline(text: str) -> list[dict]:
    """解析用户大纲文本，返回按顺序的章节列表 [{title, level}]。

    识别规则：
    - “第一章 / 第1章 …” -> 一级
    - “1.1 / 1.1.1 …”    -> 二级/三级（按小数点数量）
    - “1、1. 1)”          -> 一级
    - 无编号行            -> 一级
    """
    chapters: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^第[一二三四五六七八九十百\d]+章", line):
            level = 1
        elif re.match(r"^\d+(\.\d+)+", line):
            level = min(3, line.count(".") + 1)
        elif re.match(r"^\d+[、.)]", line):
            level = 1
        else:
            level = 1
        chapters.append({"title": line, "level": level})
    return chapters
