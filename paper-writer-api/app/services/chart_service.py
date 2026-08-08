"""升级版图表生成模块。

支持 20 种图表类型、按专业智能推荐、数量控制（figure_1..N.png）、
图表数据导出（charts/chart_data.json）。全部数据为示例数据，需替换为真实数据。
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle
from matplotlib.sankey import Sankey

CHART_TYPES: dict[str, str] = {
    "bar": "柱状图",
    "horizontal_bar": "条形图",
    "radar": "雷达图",
    "stacked_bar": "分向条形图",
    "line": "折线图",
    "area": "面积图",
    "heatmap": "热力图",
    "stock": "股价图",
    "histogram": "直方图",
    "boxplot": "箱线图",
    "violin": "小提琴图",
    "scatter": "散点图",
    "pie": "饼图",
    "treemap": "树状图",
    "sunburst": "旭日图",
    "decomposition_tree": "分解树",
    "sankey": "桑基图",
    "funnel": "漏斗图",
    "flowchart": "流程图",
    "chord": "和弦图",
}

MAJOR_RECOMMEND: dict[str, list[str]] = {
    "计算机": ["flowchart", "line", "bar"],
    "教育学": ["bar", "pie", "radar"],
    "经管": ["line", "heatmap", "sankey"],
    "医学": ["bar", "histogram", "boxplot"],
    "理工": ["line", "scatter", "histogram"],
}

DEFAULT_TYPES = ["bar", "line", "pie"]


def _to_native(obj):
    """把 numpy 标量/数组递归转为 Python 原生类型，便于 JSON 序列化。"""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


def setup_fonts() -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
    plt.rcParams["axes.unicode_minus"] = False


def recommend_types(major: str) -> list[str]:
    for key, types in MAJOR_RECOMMEND.items():
        if key in major:
            return list(types)
    return list(DEFAULT_TYPES)


# ------------------------------------------------------------------ 示例数据

def _cats(n: int = 5):
    return [f"类别{chr(65 + i)}" for i in range(n)]


def _sample_data(chart_type: str) -> dict:
    if chart_type in ("bar", "horizontal_bar", "radar"):
        return {"categories": _cats(), "values": [120, 168, 205, 246, 180]}
    if chart_type == "stacked_bar":
        return {
            "categories": _cats(),
            "series": {
                "系列1": [50, 70, 90, 110, 80],
                "系列2": [70, 98, 115, 136, 100],
            },
        }
    if chart_type in ("line", "area"):
        return {
            "categories": ["2021", "2022", "2023", "2024"],
            "series": {
                "指标A": [120, 168, 205, 246],
                "指标B": [80, 110, 140, 175],
            },
        }
    if chart_type == "heatmap":
        rng = np.random.default_rng(42)
        return {
            "rows": [f"行{i}" for i in range(1, 6)],
            "cols": [f"列{i}" for i in range(1, 6)],
            "matrix": rng.integers(0, 100, size=(5, 5)).tolist(),
        }
    if chart_type == "stock":
        rng = np.random.default_rng(7)
        rows = []
        for i in range(12):
            base = 100 + i * 2
            rows.append({
                "day": f"D{i + 1}",
                "open": base, "high": base + 6, "low": base - 5,
                "close": base + rng.integers(-3, 4),
            })
        return {"items": rows}
    if chart_type == "histogram":
        return {"values": list(np.random.default_rng(1).normal(50, 12, 200))}
    if chart_type in ("boxplot", "violin"):
        rng = np.random.default_rng(2)
        return {"series": [rng.normal(loc, 8, 60).tolist() for loc in (40, 50, 60, 55)]}
    if chart_type == "scatter":
        rng = np.random.default_rng(3)
        return {"x": rng.normal(50, 15, 60).tolist(),
                "y": rng.normal(50, 15, 60).tolist()}
    if chart_type in ("pie", "funnel"):
        return {"categories": ["分类A", "分类B", "分类C", "分类D"],
                "values": [35, 28, 22, 15]}
    if chart_type == "treemap":
        return {"items": [("模块A", 40), ("模块B", 25), ("模块C", 18),
                          ("模块D", 10), ("模块E", 7)]}
    if chart_type == "sunburst":
        return {"hierarchy": {
            "一级A": {"二级A1": 30, "二级A2": 20},
            "一级B": {"二级B1": 25, "二级B2": 15},
            "一级C": {"二级C1": 10},
        }}
    if chart_type in ("decomposition_tree", "flowchart"):
        return {"root": "总目标",
                "children": ["子目标A", "子目标B", "子目标C", "子目标D"]}
    if chart_type == "sankey":
        return {"flows": [("来源A", "去向1", 60), ("来源A", "去向2", 40),
                          ("来源B", "去向1", 30)]}
    if chart_type == "chord":
        return {"nodes": ["节点A", "节点B", "节点C", "节点D"],
                "edges": [("节点A", "节点B", 3), ("节点A", "节点C", 2),
                          ("节点B", "节点D", 2), ("节点C", "节点D", 1)]}
    return {"categories": _cats(), "values": [1, 2, 3, 4, 5]}


# ------------------------------------------------------------------ 渲染

def _render(fig, ax, chart_type: str, data: dict) -> plt.Axes:
    if chart_type == "bar":
        ax.bar(data["categories"], data["values"], color="#4C72B0")
        ax.set_ylabel("数值")
    elif chart_type == "horizontal_bar":
        ax.barh(data["categories"], data["values"], color="#55A868")
        ax.set_xlabel("数值")
    elif chart_type == "radar":
        ax.remove()
        ax = fig.add_subplot(111, projection="polar")
        cats = data["categories"]
        vals = data["values"]
        angles = np.linspace(0, 2 * np.pi, len(cats), endpoint=False).tolist()
        ax.plot(angles + angles[:1], vals + vals[:1], color="#C44E52")
        ax.fill(angles + angles[:1], vals + vals[:1], alpha=0.25, color="#C44E52")
        ax.set_xticks(angles)
        ax.set_xticklabels(cats)
    elif chart_type == "stacked_bar":
        cats = data["categories"]
        bottom = np.zeros(len(cats))
        colors = ["#4C72B0", "#55A868"]
        for (name, series), color in zip(data["series"].items(), colors):
            ax.bar(cats, series, bottom=bottom, label=name, color=color)
            bottom += np.asarray(series)
        ax.legend()
    elif chart_type == "line":
        cats = data["categories"]
        for name, series in data["series"].items():
            ax.plot(cats, series, marker="o", label=name)
        ax.legend()
    elif chart_type == "area":
        cats = data["categories"]
        for name, series in data["series"].items():
            ax.plot(cats, series, marker="o", label=name)
            ax.fill_between(range(len(cats)), series, alpha=0.25)
        ax.legend()
    elif chart_type == "heatmap":
        im = ax.imshow(data["matrix"], cmap="YlOrRd", aspect="auto")
        ax.set_xticks(range(len(data["cols"])))
        ax.set_xticklabels(data["cols"])
        ax.set_yticks(range(len(data["rows"])))
        ax.set_yticklabels(data["rows"])
        fig.colorbar(im, ax=ax)
    elif chart_type == "stock":
        for i, item in enumerate(data["items"]):
            color = "#55A868" if item["close"] >= item["open"] else "#C44E52"
            ax.plot([i, i], [item["low"], item["high"]], color=color, lw=0.8)
            ax.add_patch(Rectangle(
                (i - 0.25, min(item["open"], item["close"])),
                0.5, abs(item["close"] - item["open"]),
                facecolor=color, edgecolor=color))
        ax.set_xticks(range(len(data["items"])))
        ax.set_xticklabels([item["day"] for item in data["items"]], rotation=45,
                           fontsize=8)
    elif chart_type == "histogram":
        ax.hist(data["values"], bins=12, color="#8172B2", edgecolor="white")
        ax.set_xlabel("数值")
        ax.set_ylabel("频数")
    elif chart_type == "boxplot":
        ax.boxplot(data["series"])
        ax.set_xticks(range(1, len(data["series"]) + 1))
        ax.set_xticklabels([f"组{i + 1}" for i in range(len(data["series"]))])
    elif chart_type == "violin":
        ax.violinplot(data["series"], showmeans=True)
        ax.set_xticks(range(1, len(data["series"]) + 1))
        ax.set_xticklabels([f"组{i + 1}" for i in range(len(data["series"]))])
    elif chart_type == "scatter":
        ax.scatter(data["x"], data["y"], alpha=0.6, color="#C44E52")
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
    elif chart_type == "pie":
        ax.pie(data["values"], labels=data["categories"], autopct="%.1f%%",
               startangle=90)
        ax.axis("equal")
    elif chart_type == "treemap":
        _treemap(ax, data["items"])
    elif chart_type == "sunburst":
        _sunburst(ax, data["hierarchy"])
    elif chart_type in ("decomposition_tree", "flowchart"):
        _tree(ax, data["root"], data["children"], vertical=chart_type == "decomposition_tree")
    elif chart_type == "sankey":
        _sankey(ax, data["flows"])
    elif chart_type == "funnel":
        _funnel(ax, data["categories"], data["values"])
    elif chart_type == "chord":
        _chord(ax, data["nodes"], data["edges"])
    return ax


def _treemap(ax, items):
    total = sum(v for _, v in items)
    x = 0.0
    colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2", "#CCB974"]
    for i, (label, value) in enumerate(items):
        width = value / total
        ax.add_patch(Rectangle((x, 0), width, 1, facecolor=colors[i % len(colors)],
                               edgecolor="white"))
        ax.text(x + width / 2, 0.5, f"{label}\n{value}", ha="center",
                va="center", fontsize=9, color="white")
        x += width
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")


def _sunburst(ax, hierarchy):
    inner = []
    outer = []
    for l1, children in hierarchy.items():
        inner.append(l1)
        for l2, v in children.items():
            outer.append((f"{l1}/{l2}", v))
    ax.pie([1] * len(inner), radius=1.0, wedgeprops=dict(width=0.35,
            edgecolor="white"), labels=inner, labeldistance=0.55, rotatelabels=False)
    ax.pie([v for _, v in outer], radius=1.35, wedgeprops=dict(width=0.35,
            edgecolor="white"))
    ax.axis("equal")


def _tree(ax, root, children, vertical):
    ax.axis("off")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.15, 1.15)
    if vertical:
        ax.add_patch(Rectangle((0.3, 0.75), 0.4, 0.2, facecolor="#4C72B0"))
        ax.text(0.5, 0.85, root, ha="center", va="center", color="white", fontsize=9)
        n = len(children)
        for i, child in enumerate(children):
            x = (i + 1) / (n + 1)
            ax.add_patch(Rectangle((x - 0.12, 0.15), 0.24, 0.18, facecolor="#55A868"))
            ax.text(x, 0.24, child, ha="center", va="center", color="white", fontsize=8)
            ax.add_patch(FancyArrowPatch((0.5, 0.75), (x, 0.33),
                         arrowstyle="-|>", color="#888888", lw=1))
    else:
        ax.add_patch(Rectangle((0.25, 0.7), 0.5, 0.2, facecolor="#4C72B0"))
        ax.text(0.5, 0.8, root, ha="center", va="center", color="white", fontsize=9)
        n = len(children)
        for i, child in enumerate(children):
            x = (i + 1) / (n + 1)
            ax.add_patch(Rectangle((x - 0.1, 0.15), 0.2, 0.18, facecolor="#55A868"))
            ax.text(x, 0.24, child, ha="center", va="center", color="white", fontsize=7)
            ax.add_patch(FancyArrowPatch((0.5, 0.7), (x, 0.33),
                         connectionstyle="arc3,rad=0.15", arrowstyle="-|>",
                         color="#888888", lw=1))


def _sankey(ax, flows):
    ax.axis("off")
    try:
        sankey = Sankey(ax=ax, scale=0.08, offset=0.12, head_angle=120,
                        format="%.0f", unit="")
        nets = {}
        for src, dst, val in flows:
            nets[src] = nets.get(src, 0) + val
            nets[dst] = nets.get(dst, 0) - val
        total_in = sum(v for v in nets.values() if v > 0)
        for src, dst, val in flows:
            sankey.add(flows=[total_in, -val, -(total_in - val)],
                       labels=[src, dst, ""],
                       orientations=[0, -1, 1])
        sankey.finish()
    except Exception:
        _funnel(ax, [f"{s}→{d}" for s, d, _ in flows], [v for _, _, v in flows])


def _funnel(ax, categories, values):
    values = np.asarray(values, dtype=float)
    vmax = values.max()
    for i, (cat, v) in enumerate(zip(categories, values)):
        width = 0.9 * v / vmax
        ax.barh(i, width, left=(1 - width) / 2, height=0.6, color="#CCB974")
        ax.text(0.5, i, f"{cat}  {v}", ha="center", va="center", fontsize=9)
    ax.set_yticks([])
    ax.set_xlim(0, 1)
    ax.invert_yaxis()


def _chord(ax, nodes, edges):
    ax.axis("off")
    ax.set_aspect("equal")
    n = len(nodes)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pos = {node: (np.cos(a), np.sin(a)) for node, a in zip(nodes, angles)}
    for node in nodes:
        x, y = pos[node]
        ax.add_patch(Circle((x, y), 0.12, facecolor="#4C72B0", edgecolor="white"))
        ax.text(x, y, node, ha="center", va="center", fontsize=8, color="white")
    for src, dst, weight in edges:
        if src not in pos or dst not in pos:
            continue
        ax.add_patch(FancyArrowPatch(pos[src], pos[dst],
                     connectionstyle="arc3,rad=0.25",
                     arrowstyle="-", color="#55A868",
                     alpha=min(0.9, 0.2 + weight * 0.2)))
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-1.3, 1.3)


# ------------------------------------------------------------------ 主流程

def generate_charts(task_dir: Path, major: str, enabled: bool, count: int,
                    types: list[str]) -> list[dict]:
    """生成 count 张图表到 task_dir/charts/，返回图表元数据列表。"""
    setup_fonts()
    selected = [t for t in types if t in CHART_TYPES]
    if not selected:
        selected = recommend_types(major)
    if not enabled or count <= 0:
        return []

    charts_dir = task_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    meta_list: list[dict] = []
    data_list: list[dict] = []
    for i in range(1, count + 1):
        chart_type = selected[(i - 1) % len(selected)]
        label = CHART_TYPES[chart_type]
        data = _to_native(_sample_data(chart_type))
        title = f"示例{label}（示例数据）"

        fig, ax = plt.subplots(figsize=(6.5, 3.8))
        ax = _render(fig, ax, chart_type, data)
        ax.set_title(title, fontsize=12)
        fig.tight_layout()
        file_name = f"figure_{i}.png"
        fig.savefig(charts_dir / file_name, dpi=200, bbox_inches="tight")
        plt.close(fig)

        meta_list.append({
            "file": file_name, "type": chart_type, "label": label,
            "title": title, "chapter": 0, "number": "", "caption": "",
        })
        data_list.append({"type": chart_type, "title": title, "data": data})

    (charts_dir / "chart_data.json").write_text(
        json.dumps(data_list, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta_list
