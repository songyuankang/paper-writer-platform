import { useEffect, useMemo } from "react";
import type { OutlineChapter } from "../api/paper";

const OUTLINE_KEY = "paper-writer-outline";
const CN = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"];

interface ParsedLine {
  title: string;
  level: number;
}

interface OutlineEditorProps {
  value: string;
  onChange: (value: string) => void;
  totalWords: number;
  aiChapters?: OutlineChapter[] | null;
}

function parseOutline(text: string): ParsedLine[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      let level = 1;
      if (/^第[一二三四五六七八九十百\d]+章/.test(line)) {
        level = 1;
      } else if (/^\d+(\.\d+)+/.test(line)) {
        level = Math.min(3, line.split(".").length - 1 + 1);
      } else if (/^\d+[、.)]/.test(line)) {
        level = 1;
      }
      return { title: line, level };
    });
}

function cnNum(n: number): string {
  if (n <= 10) return CN[n];
  if (n < 20) return `十${n > 10 ? CN[n - 10] : ""}`;
  return String(n);
}

/** 移动章节后按新的序号重排常见编号（第一章 / 1 / 1.1 / 1、 等）。 */
function renumberLine(line: string, top: number, sub: number): string {
  const cn = /^第([一二三四五六七八九十百\d]+)章(.*)$/.exec(line);
  if (cn) return `第${cnNum(top)}章${cn[2]}`;
  const d2 = /^(\d+)\.(\d+)(.*)$/.exec(line);
  if (d2) return `${top}.${sub}${d2[3]}`;
  const d1 = /^(\d+)[、.]\s*(.*)$/.exec(line);
  if (d1) return `${top}、${d1[2]}`;
  const ds = /^(\d+)\s+(.*)$/.exec(line);
  if (ds) return `${top} ${ds[2]}`;
  return line;
}

function toBlocks(lines: ParsedLine[]): ParsedLine[][] {
  const blocks: ParsedLine[][] = [];
  let current: ParsedLine[] = [];
  for (const line of lines) {
    if (line.level === 1) {
      if (current.length > 0) {
        blocks.push(current);
      }
      current = [line];
    } else {
      current.push(line);
    }
  }
  if (current.length > 0) {
    blocks.push(current);
  }
  return blocks;
}

export default function OutlineEditor({
  value,
  onChange,
  totalWords,
  aiChapters,
}: OutlineEditorProps) {
  const lines = useMemo(() => parseOutline(value), [value]);
  const blocks = useMemo(() => toBlocks(lines), [lines]);

  useEffect(() => {
    if (value) {
      return;
    }
    const saved = localStorage.getItem(OUTLINE_KEY);
    if (saved) {
      onChange(saved);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function moveBlock(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= blocks.length) {
      return;
    }
    const next = blocks.map((b) => b.slice());
    [next[index], next[target]] = [next[target], next[index]];
    const rebuilt: string[] = [];
    next.forEach((block, topIdx) => {
      block.forEach((line, subIdx) => {
        rebuilt.push(renumberLine(line.title, topIdx + 1, subIdx));
      });
    });
    onChange(rebuilt.join("\n"));
  }

  function save() {
    localStorage.setItem(OUTLINE_KEY, value);
    window.alert("大纲已保存到本机浏览器");
  }

  function clearAll() {
    if (window.confirm("清空大纲编辑区？")) {
      onChange("");
    }
  }

  const estimate = (nBlocks: number) =>
    nBlocks > 0 ? Math.round(totalWords / nBlocks) : 0;

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-700">论文大纲</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={save}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-600 hover:border-indigo-300"
          >
            保存大纲
          </button>
          <button
            type="button"
            onClick={() => {
              const saved = localStorage.getItem(OUTLINE_KEY);
              if (saved) {
                onChange(saved);
              } else {
                window.alert("还没有保存过的大纲");
              }
            }}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-600 hover:border-indigo-300"
          >
            恢复上次
          </button>
          <button
            type="button"
            onClick={clearAll}
            className="text-xs text-slate-400 hover:text-red-500"
          >
            清空
          </button>
        </div>
      </div>

      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={8}
        placeholder={
          "示例：\n第一章 绪论\n1.1 研究背景\n1.2 研究意义\n\n第二章 相关理论\n2.1 理论基础\n2.2 文献回顾"
        }
        className="w-full resize-y rounded-xl border border-slate-300 bg-white px-3 py-2.5 font-mono text-sm text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
      />

      <p className="text-xs text-slate-400">
        支持格式：第一章 绪论 / 1.1 研究背景 / 1.1.1 …；用“上移/下移”调整一级章节顺序（自动重排编号）
      </p>

      {blocks.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-slate-400">
            大纲预览（{blocks.length} 个一级章节 · 预计总字数 {totalWords}）
          </p>
          <ul className="space-y-1">
            {blocks.map((block, bi) => (
              <li key={`${block[0].title}-${bi}`}>
                {block.map((line, si) => (
                  <div
                    key={`${line.title}-${si}`}
                    className="flex items-center gap-2 rounded-lg px-2 py-1 text-sm text-slate-600 hover:bg-white"
                    style={{ marginLeft: `${(line.level - 1) * 14}px` }}
                  >
                    <span className="w-3 shrink-0 text-xs text-slate-300">
                      {line.level > 1 ? "└" : ""}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{line.title}</span>
                    {line.level === 1 && (
                      <>
                        <span className="shrink-0 text-xs text-slate-400">
                          约 {estimate(blocks.length)} 字
                        </span>
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            disabled={bi === 0}
                            onClick={() => moveBlock(bi, -1)}
                            className="rounded border border-slate-200 px-1.5 py-0.5 text-xs text-slate-500 hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-30"
                          >
                            上移
                          </button>
                          <button
                            type="button"
                            disabled={bi === blocks.length - 1}
                            onClick={() => moveBlock(bi, 1)}
                            className="rounded border border-slate-200 px-1.5 py-0.5 text-xs text-slate-500 hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-30"
                          >
                            下移
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}

      {aiChapters && aiChapters.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-indigo-500">
            AI 大纲 · 预计字数分配（提交后按此结构生成）
          </p>
          <ul className="space-y-0.5">
            {aiChapters.map((c, i) => (
              <li
                key={`${c.title}-${i}`}
                className="flex items-center gap-2 text-sm text-slate-600"
                style={{ marginLeft: `${(c.level - 1) * 14}px` }}
              >
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
                {c.level === 1 && c.word_count > 0 && (
                  <span className="shrink-0 text-xs text-slate-400">
                    约 {c.word_count} 字
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
