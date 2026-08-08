/**
 * 学校模板库：用 IndexedDB 把上传的 .docx 模板持久化在当前浏览器中。
 * 模板可重命名、删除、复用；仅存本机，不修改后端。
 */

export interface TemplateRecord {
  id: string;
  /** 可重命名的模板名称（不含 .docx 后缀） */
  name: string;
  /** 原始文件名 */
  fileName: string;
  size: number;
  blob: Blob;
  createdAt: string;
  updatedAt: string;
}

const DB_NAME = "paper-writer-templates";
const STORE = "templates";
const LAST_USED_KEY = "paper-writer-last-template";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run<T>(
  mode: IDBTransactionMode,
  action: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDb();
  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const req = action(tx.objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function listTemplates(): Promise<TemplateRecord[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => {
      const rows = (req.result as TemplateRecord[]).sort((a, b) =>
        b.updatedAt.localeCompare(a.updatedAt),
      );
      resolve(rows);
    };
    req.onerror = () => reject(req.error);
  });
}

export async function saveTemplate(file: File, name?: string): Promise<TemplateRecord> {
  const now = new Date().toISOString();
  const record: TemplateRecord = {
    id: crypto.randomUUID(),
    name: (name ?? file.name).replace(/\.docx$/i, ""),
    fileName: file.name,
    size: file.size,
    blob: file,
    createdAt: now,
    updatedAt: now,
  };
  await run("readwrite", (store) => store.put(record));
  return record;
}

export async function renameTemplate(id: string, name: string): Promise<void> {
  const record = await run("readonly", (store) => store.get(id));
  if (!record) {
    return;
  }
  const updated: TemplateRecord = {
    ...(record as TemplateRecord),
    name,
    updatedAt: new Date().toISOString(),
  };
  await run("readwrite", (store) => store.put(updated));
}

export async function deleteTemplate(id: string): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export function rememberLastUsed(id: string | null): void {
  if (id) {
    localStorage.setItem(LAST_USED_KEY, id);
  } else {
    localStorage.removeItem(LAST_USED_KEY);
  }
}

export function getLastUsedId(): string | null {
  return localStorage.getItem(LAST_USED_KEY);
}
