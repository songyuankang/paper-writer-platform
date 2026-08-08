#!/usr/bin/env python3
"""Generate a chart PNG with Chinese font support from CSV/JSON data.

Usage:
    python plot_chart.py --data data.csv --type bar --x 年份 --y 销售额 \\
        --title 销售额变化 --ylabel 万元 --out figures/fig1.png

Chart types: bar, line, pie, scatter, hist
Data: CSV (utf-8/gb18030) with a header row, or JSON as a list of objects
      {"x": ..., "y": ...} / [{"年份": 2020, "销售额": 100}, ...].
"""

import argparse
import csv
import io
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def setup_fonts():
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
    plt.rcParams["axes.unicode_minus"] = False


def load_rows(path):
    if str(path).lower().endswith(".json"):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            keys = list(data.keys())
            n = len(data[keys[0]])
            return [{k: data[k][i] for k in keys} for i in range(n)]
        return data
    raw = Path(path).read_bytes()
    text = None
    for enc in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"Cannot decode data file: {path}")
    return list(csv.DictReader(io.StringIO(text)))


def num(value):
    return float(str(value).replace(",", "").replace("%", ""))


def finalize(fig, out, dpi, note=None):
    fig.tight_layout()
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    print(f"[OK] Saved chart: {out}")
    if note:
        print(f"      Note: {note}")


def plot_bar(fig, ax, rows, x, y, xlabel, ylabel, labels):
    cats = [str(r[x]) for r in rows]
    vals = [num(r[y]) for r in rows]
    ax.bar(cats, vals, color="#4C72B0")
    ax.set_xlabel(xlabel or x)
    ax.set_ylabel(ylabel or y)
    if len(cats) > 8:
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    if labels:
        ax.bar_label(ax.containers[0], fmt="%.2f")


def plot_line(fig, ax, rows, x, y, xlabel, ylabel):
    xs = []
    for r in rows:
        raw = str(r[x]).strip()
        xs.append(num(raw) if raw.replace(".", "").replace("-", "").isdigit() else raw)
    vals = [num(r[y]) for r in rows]
    ax.plot(xs, vals, marker="o", color="#55A868")
    ax.set_xlabel(xlabel or x)
    ax.set_ylabel(ylabel or y)
    ax.grid(True, linestyle="--", alpha=0.4)


def plot_pie(fig, ax, rows, x, y):
    cats = [str(r[x]) for r in rows]
    vals = [num(r[y]) for r in rows]
    ax.pie(vals, labels=cats, autopct="%.1f%%", startangle=90)
    ax.axis("equal")


def plot_scatter(fig, ax, rows, x, y, xlabel, ylabel):
    xs = [num(r[x]) for r in rows]
    vals = [num(r[y]) for r in rows]
    ax.scatter(xs, vals, color="#C44E52", alpha=0.7)
    ax.set_xlabel(xlabel or x)
    ax.set_ylabel(ylabel or y)
    ax.grid(True, linestyle="--", alpha=0.4)


def plot_hist(fig, ax, rows, y, xlabel, ylabel):
    vals = [num(r[y]) for r in rows]
    ax.hist(vals, bins="auto", color="#8172B2", edgecolor="white")
    ax.set_xlabel(xlabel or y)
    ax.set_ylabel(ylabel or "频数")
    ax.grid(True, linestyle="--", alpha=0.4)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Plot a chart with Chinese font support")
    parser.add_argument("--data", required=True, help="CSV or JSON data file")
    parser.add_argument("--type", required=True,
                        choices=["bar", "line", "pie", "scatter", "hist"])
    parser.add_argument("--x", default=None, help="X column name")
    parser.add_argument("--y", required=True, help="Y column name")
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument("--title", default="", help="Chart title")
    parser.add_argument("--xlabel", default=None, help="X axis label")
    parser.add_argument("--ylabel", default=None, help="Y axis label")
    parser.add_argument("--figsize", default=None, help="Figure size, e.g. 8x4.5")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--labels", action="store_true", help="Show value labels (bar)")
    args = parser.parse_args()

    setup_fonts()
    rows = load_rows(args.data)
    if not rows:
        raise ValueError("Data file contains no rows.")

    w, h = 8.0, 4.5
    if args.figsize:
        w, h = (float(v) for v in args.figsize.split("x"))
    if args.type == "pie":
        w, h = max(w, 6.0), max(h, 6.0)
    fig, ax = plt.subplots(figsize=(w, h))

    if args.type == "bar":
        plot_bar(fig, ax, rows, args.x, args.y, args.xlabel, args.ylabel, args.labels)
    elif args.type == "line":
        plot_line(fig, ax, rows, args.x, args.y, args.xlabel, args.ylabel)
    elif args.type == "pie":
        plot_pie(fig, ax, rows, args.x, args.y)
    elif args.type == "scatter":
        plot_scatter(fig, ax, rows, args.x, args.y, args.xlabel, args.ylabel)
    elif args.type == "hist":
        plot_hist(fig, ax, rows, args.y, args.xlabel, args.ylabel)

    if args.title:
        ax.set_title(args.title, fontsize=14, pad=12)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    finalize(fig, out, args.dpi)
    print(f"      Rows used: {len(rows)}")


if __name__ == "__main__":
    main()
