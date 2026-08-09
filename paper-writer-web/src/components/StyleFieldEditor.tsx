import type {
  TemplateAlignment,
  TemplateIndentUnit,
  TemplateLineSpacingMode,
  TemplateStyleInput,
} from "../api/paper";

const ALIGNMENTS: { value: TemplateAlignment; label: string }[] = [
  { value: "left", label: "左对齐" },
  { value: "center", label: "居中" },
  { value: "right", label: "右对齐" },
  { value: "justify", label: "两端对齐" },
];

const LINE_SPACING_MODES: {
  value: TemplateLineSpacingMode;
  label: string;
}[] = [
  { value: "multiple", label: "倍数" },
  { value: "exact", label: "固定值" },
  { value: "at_least", label: "最小值" },
];

const INDENT_UNITS: { value: TemplateIndentUnit; label: string }[] = [
  { value: "chars", label: "字符" },
  { value: "pt", label: "磅" },
];

const inputCls =
  "w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100";
const labelCls = "mb-1 block text-xs font-medium text-slate-600";

interface StyleFieldEditorProps {
  title: string;
  value: TemplateStyleInput;
  onChange: (next: TemplateStyleInput) => void;
}

export default function StyleFieldEditor({
  title,
  value,
  onChange,
}: StyleFieldEditorProps) {
  function patch(p: Partial<TemplateStyleInput>) {
    onChange({ ...value, ...p });
  }

  const font = value.font_family ?? {
    east_asia: "宋体",
    latin: "Times New Roman",
  };
  const line = value.line_spacing ?? { mode: "multiple", value: 1.5 };
  const indent = value.first_line_indent ?? { unit: "chars", value: 0 };

  return (
    <section className="border-t border-slate-200 pt-4">
      <h3 className="mb-3 text-sm font-bold text-slate-800">{title}</h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <label className={labelCls}>中文字体</label>
          <input
            className={inputCls}
            value={font.east_asia}
            onChange={(e) =>
              patch({
                font_family: { ...font, east_asia: e.target.value },
              })
            }
          />
        </div>
        <div>
          <label className={labelCls}>西文字体</label>
          <input
            className={inputCls}
            value={font.latin}
            onChange={(e) =>
              patch({ font_family: { ...font, latin: e.target.value } })
            }
          />
        </div>
        <div>
          <label className={labelCls}>字号</label>
          <input
            type="number"
            min={1}
            max={96}
            step={0.5}
            className={inputCls}
            value={value.font_size_pt}
            onChange={(e) =>
              patch({ font_size_pt: Number(e.target.value) })
            }
          />
        </div>
        <div>
          <label className={labelCls}>对齐</label>
          <select
            className={inputCls}
            value={value.alignment}
            onChange={(e) =>
              patch({
                alignment: e.target.value as TemplateAlignment,
              })
            }
          >
            {ALIGNMENTS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>行距模式</label>
          <select
            className={inputCls}
            value={line.mode}
            onChange={(e) =>
              patch({
                line_spacing: {
                  ...line,
                  mode: e.target.value as TemplateLineSpacingMode,
                },
              })
            }
          >
            {LINE_SPACING_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>行距值</label>
          <input
            type="number"
            min={line.mode === "multiple" ? 0.5 : 1}
            max={line.mode === "multiple" ? 10 : 100}
            step={0.1}
            className={inputCls}
            value={line.value}
            onChange={(e) =>
              patch({
                line_spacing: {
                  ...line,
                  value: Number(e.target.value),
                },
              })
            }
          />
        </div>
        <div>
          <label className={labelCls}>段前</label>
          <input
            type="number"
            min={0}
            max={500}
            step={1}
            className={inputCls}
            value={value.space_before_pt}
            onChange={(e) =>
              patch({ space_before_pt: Number(e.target.value) })
            }
          />
        </div>
        <div>
          <label className={labelCls}>段后</label>
          <input
            type="number"
            min={0}
            max={500}
            step={1}
            className={inputCls}
            value={value.space_after_pt}
            onChange={(e) =>
              patch({ space_after_pt: Number(e.target.value) })
            }
          />
        </div>
        <div>
          <label className={labelCls}>首行缩进单位</label>
          <select
            className={inputCls}
            value={indent.unit}
            onChange={(e) =>
              patch({
                first_line_indent: {
                  ...indent,
                  unit: e.target.value as TemplateIndentUnit,
                },
              })
            }
          >
            {INDENT_UNITS.map((u) => (
              <option key={u.value} value={u.value}>
                {u.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>首行缩进值</label>
          <input
            type="number"
            min={0}
            max={indent.unit === "chars" ? 20 : 500}
            step={0.5}
            className={inputCls}
            value={indent.value}
            onChange={(e) =>
              patch({
                first_line_indent: {
                  ...indent,
                  value: Number(e.target.value),
                },
              })
            }
          />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
        {(
          [
            ["bold", "粗体"],
            ["italic", "斜体"],
            ["underline", "下划线"],
            ["keep_with_next", "与下段同页"],
            ["page_break_before", "段前分页"],
          ] as const
        ).map(([key, label]) => (
          <label
            key={key}
            className="flex items-center gap-1.5 text-sm text-slate-700"
          >
            <input
              type="checkbox"
              checked={Boolean(value[key])}
              onChange={(e) => patch({ [key]: e.target.checked })}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            {label}
          </label>
        ))}
      </div>
    </section>
  );
}
