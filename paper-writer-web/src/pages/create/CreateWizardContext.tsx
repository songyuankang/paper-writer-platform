import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  API_BASE,
  fetchModels,
  fetchTaskStatus,
  generateAbstract,
  generatePaper,
  getTemplateDetail,
  listTemplates,
  searchReferences,
  type ModelConfig,
  type ReferenceItem,
  type TaskInfo,
  type TemplateDetail,
  type TemplateSummary,
} from "../../api/paper";

/** 12 大学科门类（对应 aiunipaper 的专业选择）。 */
export const DISCIPLINES: { name: string; majors: string[] }[] = [
  { name: "哲学", majors: ["哲学类"] },
  { name: "经济学", majors: ["经济学类", "财政学类", "金融学类", "经济与贸易类"] },
  { name: "法学", majors: ["法学类", "政治学类", "社会学类", "马克思主义理论类"] },
  { name: "教育学", majors: ["教育学类", "体育学类"] },
  { name: "文学", majors: ["中国语言文学类", "外国语言文学类", "新闻传播学类"] },
  { name: "历史学", majors: ["历史学类"] },
  {
    name: "理学",
    majors: ["数学类", "物理学类", "化学类", "生物科学类", "统计学类"],
  },
  {
    name: "工学",
    majors: ["计算机类", "机械类", "电子信息类", "土木类", "自动化类", "材料类"],
  },
  { name: "农学", majors: ["植物生产类", "动物医学类", "林学类"] },
  {
    name: "医学",
    majors: ["临床医学类", "基础医学类", "药学类", "公共卫生与预防医学类"],
  },
  { name: "管理学", majors: ["工商管理类", "公共管理类", "管理科学与工程类"] },
  { name: "艺术学", majors: ["美术学类", "设计学类", "音乐与舞蹈学类"] },
];

/** 论文类型入口卡片。 */
export const PAPER_TYPES: {
  value: string;
  label: string;
  en: string;
  desc: string;
  words: number[];
}[] = [
  {
    value: "毕业论文",
    label: "毕业论文（本科）",
    en: "Undergraduate Thesis",
    desc: "全文 10000~20000 字，三级大纲结构，更高的学术深度与研究难度",
    words: [10000, 15000, 20000],
  },
  {
    value: "课程论文",
    label: "课程论文",
    en: "Course Paper",
    desc: "即学年论文、小论文，培养学生综合运用专业知识和科研能力",
    words: [3000, 5000, 8000],
  },
  {
    value: "开题报告",
    label: "开题报告",
    en: "Opening Report",
    desc: "对选题全面阐述：研究背景、国内外现状、研究方法与进度安排等",
    words: [2000, 3000, 5000],
  },
  {
    value: "文献综述",
    label: "文献综述",
    en: "Literature Review",
    desc: "对参考文献全面整理归纳，形成引言、现状研究、总结等综合阐述",
    words: [3000, 5000, 8000],
  },
];

/** 选题推荐（按学科门类）。 */
export const TOPIC_SUGGESTIONS: Record<string, string[]> = {
  哲学: [
    "基于实践解释学的技术伦理困境与出路",
    "存在主义视域下当代青年意义危机的哲学反思",
  ],
  经济学: [
    "数字经济发展对区域经济增长的影响研究",
    "绿色金融支持企业低碳转型的机制与效应分析",
  ],
  法学: [
    "数据要素市场化的法律规制研究",
    "人工智能生成内容著作权的法律保护路径",
  ],
  教育学: [
    "基于核心素养的课堂教学评价体系构建研究",
    "“双减”政策下课后服务的质量提升路径研究",
  ],
  文学: [
    "网络文学改编影视作品的叙事特征研究",
    "现代汉语流行语的语义演变与文化动因分析",
  ],
  历史学: [
    "近代中国城市公共空间变迁研究（1840—1949）",
    "数字人文视域下历史文献整理的方法与实践",
  ],
  理学: [
    "基于深度学习的医学影像图像识别技术研究",
    "若干类非线性方程的数值解法与稳定性分析",
  ],
  工学: [
    "基于深度学习的图像识别在智能制造质检中的应用",
    "新型液压传动系统在自动化生产线中的设计与优化",
    "基于机器视觉的零件缺陷检测系统设计",
  ],
  农学: [
    "设施农业土壤连作障碍的成因与修复技术研究",
    "基于遥感技术的农田作物长势监测方法研究",
  ],
  医学: [
    "基于深度学习的医学影像辅助诊断技术研究",
    "慢性病管理中的健康行为干预策略研究进展",
  ],
  管理学: [
    "数字化转型背景下企业绩效管理体系优化研究",
    "平台型组织员工激励机制的构建与实证研究",
  ],
  艺术学: [
    "数字媒体艺术在博物馆展陈设计中的应用研究",
    "地域文化元素在文创产品设计中的转化与表达",
  ],
};

export const STEPS = [
  { num: 1, title: "论文选题", en: "Topics" },
  { num: 2, title: "生成摘要", en: "Abstract" },
  { num: 3, title: "参考文献", en: "References" },
  { num: 4, title: "论文正文", en: "Body" },
];

export const inputCls =
  "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2.5 text-sm text-neutral-900 outline-none transition placeholder:text-neutral-400 focus:border-black focus:ring-2 focus:ring-neutral-200";

export const MATERIAL_KIND_OPTIONS = ["开题报告", "仿写论文", "其他资料"];

const STEP_PATHS: Record<string, number> = {
  "/create/topic": 1,
  "/create/abstract": 2,
  "/create/references": 3,
  "/create/body": 4,
};

const LAST_TASK_STORAGE_KEY = "paper-writer:last-task-id";

interface CreateWizardContextValue {
  paperType: string;
  setPaperType: (value: string) => void;
  discipline: string;
  setDiscipline: (value: string) => void;
  major: string;
  setMajor: (value: string) => void;
  topic: string;
  setTopic: (value: string) => void;
  wordCount: number;
  setWordCount: (value: number) => void;
  language: string;
  setLanguage: (value: string) => void;
  specialRequirements: string;
  setSpecialRequirements: (value: string) => void;
  materialsOn: boolean;
  setMaterialsOn: (value: boolean) => void;
  materialFiles: File[];
  setMaterialFiles: (value: File[]) => void;
  materialKinds: string[];
  setMaterialKinds: (
    value: string[] | ((prev: string[]) => string[]),
  ) => void;
  uploadError: string | null;
  setUploadError: (value: string | null) => void;
  abstract: string;
  setAbstract: (value: string) => void;
  keywords: string[];
  setKeywords: (value: string[]) => void;
  keywordsText: string;
  setKeywordsText: (value: string) => void;
  abstractLoading: boolean;
  abstractError: string | null;
  refs: ReferenceItem[];
  selectedRefs: string[];
  setSelectedRefs: (value: string[]) => void;
  refLoading: boolean;
  refError: string | null;
  models: ModelConfig[];
  modelId: string;
  setModelId: (value: string) => void;
  templates: TemplateSummary[];
  templateId: string;
  setTemplateId: (value: string) => void;
  templateDetail: TemplateDetail | null;
  task: TaskInfo | null;
  error: string | null;
  submitting: boolean;
  typeDef: (typeof PAPER_TYPES)[number];
  majorsOf: string[];
  running: boolean;
  taskFailed: boolean;
  taskDone: boolean;
  progress: number;
  step: number;
  activeStep: number;
  stepBadge: (num: number) => ReactNode;
  recommendTopic: () => void;
  getRecommendedTopics: () => string[];
  addMaterialFiles: (selected: FileList | null) => void;
  removeMaterialFile: (index: number) => void;
  formatSize: (bytes: number) => string;
  loadAbstract: () => Promise<void>;
  loadReferences: () => Promise<void>;
  toggleRef: (citation: string) => void;
  handleNext: () => Promise<void>;
  goStep: (target: number) => void;
}

const CreateWizardContext = createContext<CreateWizardContextValue | null>(null);

export function CreateWizardProvider({ children }: { children: ReactNode }) {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const initialType =
    searchParams.get("type") &&
    PAPER_TYPES.some((t) => t.value === searchParams.get("type"))
      ? (searchParams.get("type") as string)
      : "毕业论文";

  const [paperType, setPaperType] = useState(initialType);
  const [discipline, setDiscipline] = useState("工学");
  const [major, setMajor] = useState("计算机类");
  const [topic, setTopic] = useState("");
  const [wordCount, setWordCount] = useState(10000);
  const [language, setLanguage] = useState("中文");
  const [specialRequirements, setSpecialRequirements] = useState("");
  const [materialsOn, setMaterialsOn] = useState(false);
  const [materialFiles, setMaterialFiles] = useState<File[]>([]);
  const [materialKinds, setMaterialKinds] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [abstract, setAbstract] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordsText, setKeywordsText] = useState("");
  const [abstractLoading, setAbstractLoading] = useState(false);
  const [abstractError, setAbstractError] = useState<string | null>(null);
  const [refs, setRefs] = useState<ReferenceItem[]>([]);
  const [selectedRefs, setSelectedRefs] = useState<string[]>([]);
  const [refLoading, setRefLoading] = useState(false);
  const [refError, setRefError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [modelId, setModelId] = useState("");
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [templateDetail, setTemplateDetail] =
    useState<TemplateDetail | null>(null);
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<number | null>(null);

  const typeDef =
    PAPER_TYPES.find((t) => t.value === paperType) ?? PAPER_TYPES[0];
  const majorsOf =
    DISCIPLINES.find((d) => d.name === discipline)?.majors ?? [];
  const running =
    task !== null && task.status !== "completed" && task.status !== "failed";
  const taskFailed = task !== null && task.status === "failed";
  const taskDone = task !== null && task.status === "completed";
  const progress = task?.progress ?? 0;
  const step = STEP_PATHS[location.pathname] ?? 1;

  useEffect(
    () => () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    fetchModels()
      .then((list) => setModels(list.filter((m) => m.enabled)))
      .catch(() => setModels([]));
  }, []);

  // 从 URL ?task= 恢复编辑器任务：直达/刷新正文页时不丢编辑器状态
  useEffect(() => {
    const tid = searchParams.get("task") ||
      window.localStorage.getItem(LAST_TASK_STORAGE_KEY);
    if (!tid || task) {
      return;
    }
    fetchTaskStatus(tid)
      .then((info) => {
        setTask(info);
        // 规范化地址，后续刷新时即使 localStorage 被清理也能恢复任务。
        if (!searchParams.get("task") && location.pathname === "/create/body") {
          navigate(`/create/body?task=${encodeURIComponent(tid)}`, { replace: true });
        }
        if (info.status !== "completed" && info.status !== "failed") {
          startProgressStream(tid);
        }
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, location.pathname]);

  useEffect(() => {
    listTemplates()
      .then((data) => {
        setTemplates(data.items);
        setTemplateId(data.default_id ?? data.items[0]?.id ?? "");
      })
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    if (!templateId) {
      setTemplateDetail(null);
      return;
    }
    getTemplateDetail(templateId)
      .then(setTemplateDetail)
      .catch(() => setTemplateDetail(null));
  }, [templateId]);

  useEffect(() => {
    setWordCount(typeDef.words[0]);
  }, [paperType]); // eslint-disable-line react-hooks/exhaustive-deps

  function goStep(target: number) {
    const path =
      target === 2
        ? "/create/abstract"
        : target === 3
          ? "/create/references"
          : target === 4
            ? "/create/body"
            : "/create/topic";
    navigate(path);
  }

  function recommendTopic() {
    const pool = TOPIC_SUGGESTIONS[discipline] ?? TOPIC_SUGGESTIONS["工学"];
    const idx = pool.indexOf(topic);
    setTopic(pool[(idx + 1) % pool.length]);
  }

  function getRecommendedTopics() {
    const pool = TOPIC_SUGGESTIONS[discipline] ?? TOPIC_SUGGESTIONS["工学"];
    return [...pool].slice(0, 8);
  }

  const ALLOWED_UPLOAD_EXT = [
    "txt",
    "docx",
    "xls",
    "xlsx",
    "jpg",
    "jpeg",
    "png",
  ];
  const MAX_UPLOAD_SIZE = 5 * 1024 * 1024;
  const MAX_UPLOAD_FILES = 5;

  function addMaterialFiles(selected: FileList | null) {
    if (!selected) {
      return;
    }
    setUploadError(null);
    const next = [...materialFiles];
    const nextKinds = [...materialKinds];
    for (const f of Array.from(selected)) {
      if (next.length >= MAX_UPLOAD_FILES) {
        setUploadError(`最多上传 ${MAX_UPLOAD_FILES} 个资料文件`);
        break;
      }
      const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
      if (!ALLOWED_UPLOAD_EXT.includes(ext)) {
        setUploadError(
          `文件「${f.name}」格式不支持，支持：txt/docx/xls/xlsx/jpg/jpeg/png`,
        );
        continue;
      }
      if (f.size > MAX_UPLOAD_SIZE) {
        setUploadError(`文件「${f.name}」超过 5MB 大小限制`);
        continue;
      }
      next.push(f);
      nextKinds.push("其他资料");
    }
    setMaterialFiles(next);
    setMaterialKinds(nextKinds);
  }

  function removeMaterialFile(index: number) {
    setMaterialFiles((prev) => prev.filter((_, i) => i !== index));
    setMaterialKinds((prev) => prev.filter((_, i) => i !== index));
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function loadAbstract() {
    setAbstractLoading(true);
    setAbstractError(null);
    try {
      const res = await generateAbstract({
        title: topic.trim(),
        major: `${discipline}·${major}`,
        paper_type: paperType,
        special_requirements: specialRequirements.trim(),
        model_id: modelId || undefined,
      });
      setAbstract(res.abstract);
      setKeywords(res.keywords ?? []);
      setKeywordsText((res.keywords ?? []).join("，"));
    } catch (err) {
      setAbstractError(
        err instanceof Error ? err.message : "摘要生成失败，请手动填写摘要",
      );
    } finally {
      setAbstractLoading(false);
    }
  }

  async function loadReferences() {
    if (!topic.trim() && keywords.length === 0) {
      setRefError("请先填写论文选题或关键词");
      return;
    }
    setRefLoading(true);
    setRefError(null);
    try {
      const res = await searchReferences({
        title: topic.trim(),
        major: `${discipline}·${major}`,
        keywords: keywords.length > 0 ? keywords : undefined,
      });
      setRefs(res.references);
      setSelectedRefs(res.references.map((r) => r.citation));
    } catch (err) {
      setRefError(err instanceof Error ? err.message : "文献搜索失败");
      setRefs([]);
      setSelectedRefs([]);
    } finally {
      setRefLoading(false);
    }
  }

  function toggleRef(citation: string) {
    setSelectedRefs((prev) =>
      prev.includes(citation)
        ? prev.filter((c) => c !== citation)
        : [...prev, citation],
    );
  }

  async function handleNext() {
    setError(null);
    if (step === 1) {
      if (!topic.trim()) {
        setError("请输入或选择一个论文选题");
        return;
      }
      if (!discipline || !major) {
        setError("请选择专业");
        return;
      }
      goStep(2);
      void loadAbstract();
      return;
    }
    if (step === 2) {
      if (!abstract.trim()) {
        setError("请填写或生成论文摘要");
        return;
      }
      goStep(3);
      void loadReferences();
      return;
    }
    if (step === 3) {
      setSubmitting(true);
      try {
        const { task_id } = await generatePaper({
          title: topic.trim(),
          major: `${discipline}·${major}`,
          paper_type: paperType,
          word_count: wordCount,
          chart_enabled: paperType !== "开题报告",
          chart_config:
            paperType !== "开题报告"
              ? { enabled: true, count: 3, types: ["bar", "line", "pie"] }
              : null,
          special_requirements: specialRequirements.trim(),
          model_id: modelId || undefined,
          reference_style: "gb7714",
          files: materialFiles.length > 0 ? materialFiles : undefined,
          materialKinds:
            materialFiles.length > 0 ? materialKinds : undefined,
          abstract: abstract.trim(),
          keywords,
          references: selectedRefs.length > 0 ? selectedRefs : undefined,
          draft_mode: true,
          template_id: templateId || undefined,
        });
        window.localStorage.setItem(LAST_TASK_STORAGE_KEY, task_id);
        startProgressStream(task_id);
        navigate(`/create/body?task=${encodeURIComponent(task_id)}`);
      } catch (err) {
        setSubmitting(false);
        setError(
          err instanceof Error
            ? err.message
            : "提交失败，请检查后端服务是否已启动",
        );
      }
    }
  }

  function startProgressStream(taskId: string) {
    const fallbackPoll = () => {
      if (pollRef.current !== null) {
        return;
      }
      pollRef.current = window.setInterval(async () => {
        try {
          const info = await fetchTaskStatus(taskId);
          setTask(info);
          if (info.status === "completed" || info.status === "failed") {
            if (pollRef.current !== null) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
            setSubmitting(false);
          }
        } catch {
          if (pollRef.current !== null) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
          }
          setSubmitting(false);
        }
      }, 1500);
    };

    if (typeof EventSource === "undefined") {
      fallbackPoll();
      return;
    }
    const es = new EventSource(`${API_BASE}/api/generate/stream/${taskId}`);
    let finished = false;
    const finish = () => {
      if (finished) {
        return;
      }
      finished = true;
      es.close();
      setSubmitting(false);
    };
    es.addEventListener("progress", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent<string>).data);
        setTask({
          task_id: taskId,
          status: data.status,
          progress: data.progress,
          message: data.message,
          current_stage: data.current_stage,
          current_chapter: data.current_chapter,
          chapter_count: data.chapter_count,
          error: null,
          files: [],
        });
        if (data.status === "completed" || data.status === "failed") {
          finish();
          void fetchTaskStatus(taskId).then(setTask).catch(() => undefined);
        }
      } catch {
        // 忽略无法解析的事件
      }
    });
    es.onerror = () => {
      finish();
      fallbackPoll();
    };
  }

  const activeStep = taskDone
    ? 4
    : progress >= 70
      ? 3
      : progress >= 18
        ? 2
        : 1;

  function stepBadge(num: number) {
    if (num < step) {
      return (
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-green-500 text-xs font-bold text-white">
          ✓
        </span>
      );
    }
    if (num === step) {
      return (
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-xs font-bold text-white">
          {num}
        </span>
      );
    }
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-200 text-xs font-bold text-slate-500">
        {num}
      </span>
    );
  }

  const value: CreateWizardContextValue = {
    paperType,
    setPaperType,
    discipline,
    setDiscipline,
    major,
    setMajor,
    topic,
    setTopic,
    wordCount,
    setWordCount,
    language,
    setLanguage,
    specialRequirements,
    setSpecialRequirements,
    materialsOn,
    setMaterialsOn,
    materialFiles,
    setMaterialFiles,
    materialKinds,
    setMaterialKinds,
    uploadError,
    setUploadError,
    abstract,
    setAbstract,
    keywords,
    setKeywords,
    keywordsText,
    setKeywordsText,
    abstractLoading,
    abstractError,
    refs,
    selectedRefs,
    setSelectedRefs,
    refLoading,
    refError,
    models,
    modelId,
    setModelId,
    templates,
    templateId,
    setTemplateId,
    templateDetail,
    task,
    error,
    submitting,
    typeDef,
    majorsOf,
    running,
    taskFailed,
    taskDone,
    progress,
    step,
    activeStep,
    stepBadge,
    recommendTopic,
    getRecommendedTopics,
    addMaterialFiles,
    removeMaterialFile,
    formatSize,
    loadAbstract,
    loadReferences,
    toggleRef,
    handleNext,
    goStep,
  };

  return (
    <CreateWizardContext.Provider value={value}>
      {children}
    </CreateWizardContext.Provider>
  );
}

export function useCreateWizard(): CreateWizardContextValue {
  const ctx = useContext(CreateWizardContext);
  if (!ctx) {
    throw new Error("useCreateWizard must be used inside CreateWizardProvider");
  }
  return ctx;
}
