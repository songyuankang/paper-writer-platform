import { useState } from "react";
import type { DraftParagraph } from "../api/paper";
import EditableDraftChartBlock from "./EditableDraftChartBlock";
import EditableInsightBlock from "./EditableInsightBlock";
import EditableCrossReferenceBlock from "./EditableCrossReferenceBlock";
import type { EditableChartSpec } from "./chartSpecEditorState";

type BlockPatch = {
  text?: string;
  title?: string;
  headers?: string[];
  rows?: string[][];
  caption?: string;
  display_scale?: number;
};

type Props = {
  taskId: string;
  block: DraftParagraph;
  index: number;
  onText: (text: string) => void;
  onUpdate: (patch: BlockPatch) => Promise<void> | void;
  onRefresh?: () => Promise<void> | void;
  onDelete: () => void;
  onMove: (direction: "up" | "down") => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onChartUpdate?: (patch: { title?: string; caption?: string; display_scale?: number }) => Promise<void> | void;
  onRegenerateChart?: () => Promise<void> | void;
  onAiRegenerateChart?: () => Promise<void> | void;
  onChartSpecUpdate?: (chartSpec: EditableChartSpec) => Promise<void> | void;
};

const BTN = "rounded border border-neutral-200 bg-white px-2 py-1 text-xs text-neutral-600 transition hover:border-black hover:text-black disabled:opacity-40";

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="max-h-[88vh] w-full max-w-4xl overflow-auto rounded-2xl bg-white p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-black">{title}</h3>
          <button className="text-xl text-neutral-400 hover:text-black" onClick={onClose} aria-label="关闭">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function TableEditor({
  block,
  onClose,
  onSave,
}: {
  block: DraftParagraph;
  onClose: () => void;
  onSave: (patch: BlockPatch) => Promise<void> | void;
}) {
  const [title, setTitle] = useState(block.title || "数据表");
  const [headers, setHeaders] = useState<string[]>(block.headers?.length ? block.headers : ["指标", "数值"]);
  const [rows, setRows] = useState<string[][]>(block.rows?.length ? block.rows : [["", ""]]);
  const changeCell = (rowIndex: number, columnIndex: number, value: string) => {
    setRows(rows.map((row, ri) => ri === rowIndex ? row.map((cell, ci) => ci === columnIndex ? value : cell) : row));
  };
  const addRow = () => setRows([...rows, headers.map(() => "")]);
  const removeRow = (rowIndex: number) => setRows(rows.filter((_, index) => index !== rowIndex));
  const addColumn = () => {
    setHeaders([...headers, "新列"]);
    setRows(rows.map((row) => [...row, ""]));
  };
  return (
    <Modal title="表格修改" onClose={onClose}>
      <label className="mb-3 block text-xs text-neutral-500">
        表格标题
        <input className="mt-1 w-full rounded border px-2 py-1.5 text-sm" value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <div className="max-h-[46vh] overflow-auto rounded border">
        <table className="min-w-full text-sm">
          <thead className="bg-neutral-50"><tr>{headers.map((header, columnIndex) => <th key={columnIndex} className="border-b p-2"><input className="w-full bg-transparent text-center font-semibold outline-none" value={header} onChange={(event) => setHeaders(headers.map((item, index) => index === columnIndex ? event.target.value : item))} /></th>)}</tr></thead>
          <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, columnIndex) => <td key={columnIndex} className="border-b border-r p-1"><input className="w-full bg-transparent px-1 py-1 text-center outline-none focus:bg-amber-50" value={cell} onChange={(event) => changeCell(rowIndex, columnIndex, event.target.value)} /></td>)}<td className="p-1"><button className="text-xs text-red-500" onClick={() => removeRow(rowIndex)}>删除</button></td></tr>)}</tbody>
        </table>
      </div>
      <div className="mt-3 flex gap-2">
        <button className={BTN} onClick={addRow}>+ 新增行</button>
        <button className={BTN} onClick={addColumn}>+ 新增列</button>
        <div className="flex-1" />
        <button className={BTN} onClick={onClose}>取消</button>
        <button className="rounded bg-black px-4 py-1.5 text-xs font-semibold text-white" onClick={() => void onSave({ title, headers, rows })}>确认修改</button>
      </div>
    </Modal>
  );
}

export default function EditableDraftBlock({
  taskId,
  block,
  index,
  onText,
  onUpdate,
  onRefresh,
  onDelete,
  onMove,
  canMoveUp,
  canMoveDown,
  onChartUpdate,
  onRegenerateChart,
  onAiRegenerateChart,
  onChartSpecUpdate,
}: Props) {
  const [editing, setEditing] = useState(false);
  if (block.type === "insight") {
    return <EditableInsightBlock block={block} index={index} onDelete={onDelete} onMove={onMove} canMoveUp={canMoveUp} canMoveDown={canMoveDown} />;
  }
  if (block.type === "chart") {
    return <EditableDraftChartBlock taskId={taskId} block={block} onUpdate={onChartUpdate} onRegenerate={onRegenerateChart} onAiRegenerate={onAiRegenerateChart} onRefresh={onRefresh} onChartSpecUpdate={onChartSpecUpdate} onDelete={onDelete} onMove={onMove} canMoveUp={canMoveUp} canMoveDown={canMoveDown} />;
  }
  if (block.type === "cross_reference") {
    return <EditableCrossReferenceBlock taskId={taskId} block={block} onRefresh={onRefresh || (async () => undefined)} onDelete={onDelete} onMove={onMove} canMoveUp={canMoveUp} canMoveDown={canMoveDown} />;
  }
  if (block.type === "table") {
    return (
      <>
        <div className="rounded-lg border border-neutral-200 bg-white p-3 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-neutral-700">{typeof block.table_number === "number" && block.table_number > 0 ? `表${block.table_number} ${block.title || "数据表"}` : (block.title || "数据表（待编号）")}</span>
            <div className="flex gap-1">
              <button className={BTN} onClick={() => setEditing(true)}>修改表格</button>
              <button className={BTN} disabled={!canMoveUp} onClick={() => onMove("up")}>↑</button>
              <button className={BTN} disabled={!canMoveDown} onClick={() => onMove("down")}>↓</button>
              <button className="rounded border border-red-200 px-2 py-1 text-xs text-red-500" onClick={onDelete}>删除</button>
            </div>
          </div>
          <div className="overflow-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-neutral-50"><tr>{(block.headers || []).map((header, headerIndex) => <th className="border px-3 py-2" key={headerIndex}>{header}</th>)}</tr></thead>
              <tbody>{(block.rows || []).map((row, rowIndex) => <tr key={rowIndex}>{row.map((value, columnIndex) => <td className="border px-3 py-2 text-center" key={columnIndex}>{value}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </div>
        {editing && <TableEditor block={block} onClose={() => setEditing(false)} onSave={async (patch) => { await onUpdate(patch); setEditing(false); }} />}
      </>
    );
  }
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs text-neutral-400">
        <span>段落 {index + 1}</span>
        <div className="flex gap-1">
          <button className={BTN} disabled={!canMoveUp} onClick={() => onMove("up")}>↑</button>
          <button className={BTN} disabled={!canMoveDown} onClick={() => onMove("down")}>↓</button>
          <button className="rounded border border-red-200 px-2 py-1 text-xs text-red-500" onClick={onDelete}>删除</button>
        </div>
      </div>
      <textarea className="min-h-[92px] w-full rounded border border-neutral-200 bg-white px-3 py-2 text-sm leading-7 outline-none transition focus:border-black" value={block.text || ""} onChange={(event) => onText(event.target.value)} />
    </div>
  );
}
