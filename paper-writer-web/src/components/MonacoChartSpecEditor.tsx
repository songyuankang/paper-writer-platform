import Editor from "@monaco-editor/react";

type Props = {
  value: string;
  onChange: (value: string) => void;
};

/** Monaco is lazy-loaded only after the user enters ChartSpec JSON advanced mode. */
export default function MonacoChartSpecEditor({ value, onChange }: Props) {
  return (
    <Editor
      height="420px"
      defaultLanguage="json"
      theme="vs"
      value={value}
      onChange={(next) => onChange(next || "")}
      options={{
        minimap: { enabled: false },
        fontSize: 13,
        wordWrap: "on",
        tabSize: 2,
        formatOnPaste: true,
        formatOnType: true,
        scrollBeyondLastLine: false,
        automaticLayout: true,
      }}
    />
  );
}
