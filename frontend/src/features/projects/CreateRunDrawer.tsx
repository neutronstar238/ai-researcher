import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";
import { Drawer } from "../../components/ui/Drawer";
import { useToast } from "../../components/ui/ToastRegion";
import { apiClient } from "../../lib/api/client";
import type { RunCreateInput, RunRecord } from "../../lib/api/types";

export interface CreateRunDrawerProps {
  open: boolean;
  onClose(): void;
  onCreated(run: RunRecord): void;
}

export function CreateRunDrawer({ open, onClose, onCreated }: CreateRunDrawerProps) {
  const questionId = useId();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [direction, setDirection] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const submittingRef = useRef(false);
  const createMutation = useMutation({ mutationFn: (input: RunCreateInput) => apiClient.createRun(input) });

  const closeIfIdle = () => {
    if (!submittingRef.current) onClose();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submittingRef.current) return;

    const trimmedDirection = direction.trim();
    if (!trimmedDirection) {
      setSubmitError("请输入科学问题");
      return;
    }

    submittingRef.current = true;
    setSubmitError(null);
    try {
      const run = await createMutation.mutateAsync({
        direction: trimmedDirection,
        dry_run: dryRun,
      });
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      notify({ tone: "success", message: "研究运行已创建" });
      onCreated(run);
    } catch (error) {
      setSubmitError(errorMessage(error));
    } finally {
      submittingRef.current = false;
    }
  };

  return (
    <Drawer open={open} title="新建研究" onClose={closeIfIdle}>
      <form className="project-form" onSubmit={(event) => void handleSubmit(event)}>
        <div className="form-field">
          <label htmlFor={questionId}>科学问题</label>
          <textarea
            id={questionId}
            rows={7}
            value={direction}
            onChange={(event) => setDirection(event.target.value)}
            aria-describedby={submitError ? `${questionId}-error` : undefined}
          />
        </div>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(event) => setDryRun(event.target.checked)}
          />
          <span>仅验证流程，不执行正式研究</span>
        </label>
        {submitError ? (
          <p className="form-error" id={`${questionId}-error`} role="alert">{submitError}</p>
        ) : null}
        <div className="drawer-actions">
          <button
            className="button-secondary"
            type="button"
            aria-disabled={createMutation.isPending || undefined}
            onClick={closeIfIdle}
          >
            取消
          </button>
          <button className="button-primary" type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? "创建中…" : "开始研究"}
          </button>
        </div>
      </form>
    </Drawer>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "创建研究失败，请重试。";
}
