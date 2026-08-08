interface ProgressBarProps {
  progress: number;
  label: string;
}

export default function ProgressBar({ progress, label }: ProgressBarProps) {
  const width = Math.min(100, Math.max(0, progress));
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5">
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="font-medium text-neutral-700">{label}</span>
        <span className="font-semibold text-black">{width}%</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-neutral-100">
        <div
          className="h-full rounded-full bg-black transition-all duration-500"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}
