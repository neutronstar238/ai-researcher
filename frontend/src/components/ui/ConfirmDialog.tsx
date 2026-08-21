import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { registerOverlay, type OverlayHandle } from "./overlayManager";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm(): void | Promise<void>;
  onClose(): void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  danger = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const [confirming, setConfirming] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const overlayRef = useRef<OverlayHandle | null>(null);
  const onCloseRef = useRef(onClose);
  const dangerRef = useRef(danger);
  const confirmingRef = useRef(false);
  const mountedRef = useRef(false);
  onCloseRef.current = onClose;
  dangerRef.current = danger;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!open || !dialogRef.current) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const handle = registerOverlay(dialogRef.current, previousFocus, () => {
      if (!dangerRef.current && !confirmingRef.current) onCloseRef.current();
    });
    overlayRef.current = handle;
    cancelRef.current?.focus();

    return () => {
      handle.unregister();
      if (overlayRef.current === handle) overlayRef.current = null;
    };
  }, [open]);

  if (!open) return null;

  const handleConfirm = async () => {
    if (confirmingRef.current) return;
    confirmingRef.current = true;
    setConfirming(true);
    setSubmitError(null);
    cancelRef.current?.focus();
    try {
      await onConfirm();
      if (mountedRef.current) onCloseRef.current();
    } catch (error) {
      if (mountedRef.current) setSubmitError(toErrorMessage(error));
    } finally {
      if (mountedRef.current) {
        confirmingRef.current = false;
        setConfirming(false);
      }
    }
  };

  const trapFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("button:not([disabled])") ?? []);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className="dialog-backdrop"
      data-testid="confirm-dialog-backdrop"
      onMouseDown={(event) => {
        if (
          !danger
          && !confirmingRef.current
          && event.target === event.currentTarget
          && overlayRef.current?.isTopmost()
        ) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={trapFocus}
      >
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{description}</p>
        {submitError ? <p className="dialog-error" role="alert">{submitError}</p> : null}
        <div className="dialog-actions">
          <button
            ref={cancelRef}
            className="button-secondary"
            type="button"
            aria-disabled={confirming || undefined}
            onClick={() => {
              if (!confirmingRef.current) onClose();
            }}
          >
            取消
          </button>
          <button
            className={danger ? "button-danger" : "button-primary"}
            type="button"
            disabled={confirming}
            onClick={handleConfirm}
          >
            {confirming ? "处理中…" : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

function toErrorMessage(error: unknown): string {
  try {
    if (error && typeof error === "object" && "message" in error) {
      const message = (error as { message?: unknown }).message;
      if (typeof message === "string" && message.trim()) return message;
    }
  } catch {
    // Hostile or cross-realm values may expose a throwing message getter.
  }
  return "操作失败，请重试。";
}
