import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Drawer } from "../../components/ui/Drawer";
import { useToast } from "../../components/ui/ToastRegion";
import { apiClient } from "../../lib/api/client";
import type { BatchCreateInput, BatchRecord } from "../../lib/api/types";

export interface BatchDrawerProps {
  open: boolean;
  onClose(): void;
}

type SubmitErrorTarget = "questionPdf" | "start" | "limit" | "questionIds" | "form";

interface SubmitError {
  target: SubmitErrorTarget;
  message: string;
}

export function parseQuestionIds(value: string): number[] {
  if (!value.trim()) return [];
  const parts = value.split(",").map((part) => part.trim());
  if (parts.some((part) => !/^\d+$/.test(part))) {
    throw new Error("题号必须是 1 到 125 的整数");
  }
  const ids = parts.map(Number);
  if (ids.some((id) => id < 1 || id > 125)) {
    throw new Error("题号必须是 1 到 125 的整数");
  }
  if (new Set(ids).size !== ids.length) {
    throw new Error("题号不能重复");
  }
  return [...ids].sort((left, right) => left - right);
}

export function BatchDrawer({ open, onClose }: BatchDrawerProps) {
  const pathId = useId();
  const startId = useId();
  const limitId = useId();
  const idsId = useId();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [questionPdf, setQuestionPdf] = useState("");
  const [start, setStart] = useState("1");
  const [limit, setLimit] = useState("125");
  const [questionIds, setQuestionIds] = useState("");
  const [resume, setResume] = useState(false);
  const [dryRun, setDryRun] = useState(true);
  const [submitError, setSubmitError] = useState<SubmitError | null>(null);
  const [receipt, setReceipt] = useState<BatchRecord | null>(null);
  const submittingRef = useRef(false);
  const mountedRef = useRef(false);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const receiptHeadingRef = useRef<HTMLHeadingElement>(null);
  const createMutation = useMutation({
    mutationFn: (input: BatchCreateInput) => apiClient.createBatch(input),
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (receipt) receiptHeadingRef.current?.focus();
  }, [receipt]);

  const closeIfIdle = () => {
    if (!submittingRef.current) onClose();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submittingRef.current) return;

    let input: BatchCreateInput;
    try {
      input = {
        question_pdf: validateField("questionPdf", () => requiredPath(questionPdf)),
        start: validateField("start", () => boundedInteger(start, "起始题号")),
        limit: validateField("limit", () => boundedInteger(limit, "题目数量")),
        include_question_ids: validateField("questionIds", () => parseQuestionIds(questionIds)),
        resume,
        dry_run: dryRun,
      };
    } catch (error) {
      setSubmitError(error instanceof FieldValidationError
        ? { target: error.target, message: error.message }
        : { target: "form", message: errorMessage(error) });
      return;
    }

    submittingRef.current = true;
    setSubmitError(null);
    cancelButtonRef.current?.focus();
    try {
      const created = await createMutation.mutateAsync(input);
      if (!mountedRef.current) return;
      await queryClient.cancelQueries({ queryKey: ["batches"], exact: true });
      if (!mountedRef.current) return;
      await queryClient.invalidateQueries({ queryKey: ["batches"], exact: true });
      if (!mountedRef.current) return;
      setReceipt(created);
      notify({ tone: "success", message: "批量任务已创建" });
    } catch (error) {
      if (mountedRef.current) setSubmitError({ target: "form", message: errorMessage(error) });
    } finally {
      submittingRef.current = false;
    }
  };

  return (
    <Drawer open={open} title="批量任务" onClose={closeIfIdle}>
      {receipt ? (
        <div className="batch-receipt" aria-label="批量任务创建回执">
          <h3 ref={receiptHeadingRef} tabIndex={0}>批量任务创建回执</h3>
          <p>批量任务已由服务端接收，关闭后可在项目空间的批量任务记录中查看。</p>
          <dl>
            <div><dt>批量 ID</dt><dd>{receipt.batch_id}</dd></div>
            <div><dt>状态</dt><dd>{receipt.status}</dd></div>
            <div><dt>题目数</dt><dd>{receipt.question_count}</dd></div>
            <div><dt>创建时间</dt><dd><time dateTime={receipt.created_at}>{receipt.created_at}</time></dd></div>
          </dl>
        </div>
      ) : (
        <form className="project-form" noValidate onSubmit={(event) => void handleSubmit(event)}>
          <div className="form-field">
            <label htmlFor={pathId}>服务器 PDF 路径</label>
            <input
              id={pathId}
              type="text"
              value={questionPdf}
              onChange={(event) => setQuestionPdf(event.target.value)}
              aria-invalid={submitError?.target === "questionPdf" || undefined}
              aria-describedby={`${pathId}-help${submitError?.target === "questionPdf" ? ` ${pathId}-error` : ""}`}
            />
            <p className="form-help" id={`${pathId}-help`}>请输入本地研究服务可读取的 PDF 路径；这里不会上传浏览器文件。</p>
          </div>
          <div className="batch-form-grid">
            <div className="form-field">
              <label htmlFor={startId}>起始题号</label>
              <input
                id={startId}
                type="number"
                min="1"
                max="125"
                value={start}
                onChange={(event) => setStart(event.target.value)}
                aria-invalid={submitError?.target === "start" || undefined}
                aria-describedby={submitError?.target === "start" ? `${startId}-error` : undefined}
              />
            </div>
            <div className="form-field">
              <label htmlFor={limitId}>题目数量</label>
              <input
                id={limitId}
                type="number"
                min="1"
                max="125"
                value={limit}
                onChange={(event) => setLimit(event.target.value)}
                aria-invalid={submitError?.target === "limit" || undefined}
                aria-describedby={submitError?.target === "limit" ? `${limitId}-error` : undefined}
              />
            </div>
          </div>
          <div className="form-field">
            <label htmlFor={idsId}>指定题号</label>
            <input
              id={idsId}
              type="text"
              placeholder="例如：2, 4, 5"
              value={questionIds}
              onChange={(event) => setQuestionIds(event.target.value)}
              aria-invalid={submitError?.target === "questionIds" || undefined}
              aria-describedby={`${idsId}-help${submitError?.target === "questionIds" ? ` ${idsId}-error` : ""}`}
            />
            <p className="form-help" id={`${idsId}-help`}>可留空；多个题号用英文逗号分隔，范围为 1–125。</p>
          </div>
          <label className="checkbox-field">
            <input type="checkbox" checked={resume} onChange={(event) => setResume(event.target.checked)} />
            <span>续跑已有结果</span>
          </label>
          <label className="checkbox-field">
            <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
            <span>安全预览，不执行正式批量研究</span>
          </label>
          {submitError ? (
            <p className="form-error" id={errorId(submitError.target, { pathId, startId, limitId, idsId })} role="alert">
              {submitError.message}
            </p>
          ) : null}
          <div className="drawer-actions">
            <button
              ref={cancelButtonRef}
              className="button-secondary"
              type="button"
              aria-disabled={createMutation.isPending || undefined}
              onClick={closeIfIdle}
            >
              取消
            </button>
            <button className="button-primary" type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? "创建中…" : "创建批量任务"}
            </button>
          </div>
        </form>
      )}
    </Drawer>
  );
}

class FieldValidationError extends Error {
  constructor(readonly target: Exclude<SubmitErrorTarget, "form">, message: string) {
    super(message);
  }
}

function validateField<T>(target: Exclude<SubmitErrorTarget, "form">, validate: () => T): T {
  try {
    return validate();
  } catch (error) {
    throw new FieldValidationError(target, errorMessage(error));
  }
}

function errorId(
  target: SubmitErrorTarget,
  ids: { pathId: string; startId: string; limitId: string; idsId: string },
): string {
  if (target === "questionPdf") return `${ids.pathId}-error`;
  if (target === "start") return `${ids.startId}-error`;
  if (target === "limit") return `${ids.limitId}-error`;
  if (target === "questionIds") return `${ids.idsId}-error`;
  return `${ids.pathId}-form-error`;
}

function requiredPath(value: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error("请输入服务器 PDF 路径");
  return normalized;
}

function boundedInteger(value: string, label: string): number {
  const normalized = value.trim();
  if (!/^\d+$/.test(normalized)) throw new Error(`${label}必须是 1 到 125 的整数`);
  const result = Number(normalized);
  if (result < 1 || result > 125) throw new Error(`${label}必须是 1 到 125 的整数`);
  return result;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "创建批量任务失败，请重试。";
}
