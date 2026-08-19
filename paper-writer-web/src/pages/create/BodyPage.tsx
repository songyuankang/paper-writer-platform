import BodyEditorUniPaper from "../../components/BodyEditorUniPaper";
import { useNavigate } from "react-router-dom";
import { useCreateWizard } from "./CreateWizardContext";

export default function BodyPage() {
  const navigate = useNavigate();
  const { task, modelId, setModelId, models, typeDef } =
    useCreateWizard();

  if (task?.status === "failed") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white px-6 text-neutral-800">
        <div className="w-full max-w-xl rounded-2xl border border-red-200 bg-red-50 p-7 shadow-sm">
          <h2 className="text-lg font-semibold text-red-900">论文生成未完成</h2>
          <p className="mt-3 break-words text-sm leading-6 text-red-800">
            {task.error || task.message || "任务执行失败，请返回上一步检查后重试。"}
          </p>
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="mt-5 rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-neutral-700"
          >
            返回上一步
          </button>
        </div>
      </div>
    );
  }

  if (!task) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white text-sm text-neutral-500">
        正在准备编辑器…
      </div>
    );
  }

  return (
    <BodyEditorUniPaper
      taskId={task.task_id}
      modelId={modelId || undefined}
      models={models}
      onModelChange={setModelId}
      typeLabel={typeDef?.label}
      onBack={() => navigate("/")}
    />
  );
}
