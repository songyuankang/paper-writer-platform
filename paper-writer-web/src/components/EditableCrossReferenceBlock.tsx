import { useCallback, useEffect, useState } from "react";
import { deleteCrossReference, getCrossReferences, getReferenceCandidates, updateCrossReference, type CrossReference, type DraftParagraph, type ReferenceCandidate } from "../api/paper";

type Props = {
  taskId: string;
  block: DraftParagraph;
  onRefresh: () => Promise<void> | void;
  onMove: (direction: "up" | "down") => void;
  onDelete: () => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
};

const BTN = "rounded border border-neutral-200 bg-white px-2 py-1 text-xs text-neutral-600 transition hover:border-black hover:text-black disabled:opacity-40";

export default function EditableCrossReferenceBlock({ taskId, block, onRefresh, onMove, onDelete, canMoveUp, canMoveDown }: Props) {
  const [references, setReferences] = useState<Record<string, CrossReference>>({});
  const [candidates, setCandidates] = useState<ReferenceCandidate[]>([]);
  const [busy, setBusy] = useState(false);
  const parts = block.content || [];
  const referenceId = parts.find((part) => part.type === "cross_reference")?.reference_id;
  const reference = referenceId ? references[referenceId] : undefined;
  const broken = reference?.status === "broken" || !referenceId;

  const load = useCallback(async () => {
    const [referenceResult, candidateResult] = await Promise.all([
      getCrossReferences(taskId), getReferenceCandidates(taskId),
    ]);
    setReferences(Object.fromEntries(referenceResult.references.map((item) => [item.id, item])));
    setCandidates(candidateResult.objects);
  }, [taskId]);

  // A draft refresh produces a new block object after document renumbering;
  // reload the reference registry so the visible label follows target_object_id.
  useEffect(() => { void load().catch(() => undefined); }, [load, block]);

  const render = () => {
    if (!parts.length) return block.text || "[引用对象不存在]";
    return parts.map((part, index) => {
      if (part.type === "text") return <span key={index}>{part.text || ""}</span>;
      const item = part.reference_id ? references[part.reference_id] : undefined;
      if (!item || item.status === "broken") return <span key={index} className="font-medium text-amber-700">[引用对象不存在]</span>;
      return <span key={index} className="font-medium text-slate-900 underline decoration-slate-400 underline-offset-2">{item.resolved_label || item.display_label}</span>;
    });
  };

  async function repair(targetId: string) {
    if (!referenceId) return;
    setBusy(true);
    try {
      await updateCrossReference(taskId, referenceId, targetId);
      await load();
      await onRefresh();
    } finally { setBusy(false); }
  }

  async function remove() {
    if (!referenceId) { onDelete(); return; }
    setBusy(true);
    try {
      await deleteCrossReference(taskId, referenceId);
      await onRefresh();
    } finally { setBusy(false); }
  }

  return <div className={`rounded-lg border p-3 text-sm leading-7 ${broken ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"}`}>
    <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
      <span className="font-medium text-neutral-700">结构化引用</span>
      {broken ? <span className="text-amber-700">⚠ 引用对象不存在</span> : <span>由 ResearchObject 动态解析</span>}
      <span className="ml-auto flex gap-1">
        <button className={BTN} disabled={!canMoveUp || busy} onClick={() => onMove("up")}>↑</button>
        <button className={BTN} disabled={!canMoveDown || busy} onClick={() => onMove("down")}>↓</button>
        <button className="rounded border border-red-200 px-2 py-1 text-xs text-red-500" disabled={busy} onClick={() => void remove()}>删除引用</button>
      </span>
    </div>
    <p className="mt-2 text-[15px] text-neutral-800">{render()}</p>
    {broken && <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-amber-200 pt-2 text-xs"><span className="text-amber-800">选择其他对象：</span>{candidates.map((candidate) => <button key={candidate.id} disabled={busy} onClick={() => void repair(candidate.id)} className={BTN}>{candidate.display_label} {candidate.title}</button>)}</div>}
  </div>;
}
