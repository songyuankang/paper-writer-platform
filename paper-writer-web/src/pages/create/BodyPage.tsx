import BodyEditorUniPaper from "../../components/BodyEditorUniPaper";
import { useCreateWizard } from "./CreateWizardContext";

export default function BodyPage() {
  const { task, modelId, setModelId, models, typeDef, goStep } =
    useCreateWizard();

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
      onBack={() => goStep(3)}
    />
  );
}
