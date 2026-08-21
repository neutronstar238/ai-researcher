import { X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export type ToastTone = "success" | "warning" | "danger" | "info";

export interface ToastMessage {
  tone: ToastTone;
  message: string;
}

interface ToastContextValue {
  notify(toast: ToastMessage): void;
}

const ToastContext = createContext<ToastContextValue | null>(null);
const TOAST_DURATION_MS = 5_000;
const MAX_TOASTS = 4;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Array<ToastMessage & { id: number }>>([]);
  const nextToastId = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) clearTimeout(timer);
    timers.current.delete(id);
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);
  const notify = useCallback((toast: ToastMessage) => {
    const id = nextToastId.current + 1;
    nextToastId.current = id;
    timers.current.set(id, setTimeout(() => dismiss(id), TOAST_DURATION_MS));
    setToasts((current) => {
      const next = [...current, { ...toast, id }];
      const removed = next.slice(0, Math.max(0, next.length - MAX_TOASTS));
      for (const item of removed) {
        const timer = timers.current.get(item.id);
        if (timer !== undefined) clearTimeout(timer);
        timers.current.delete(item.id);
      }
      return next.slice(-MAX_TOASTS);
    });
  }, [dismiss]);
  const value = useMemo<ToastContextValue>(() => ({ notify }), [notify]);

  useEffect(() => () => {
    for (const timer of timers.current.values()) clearTimeout(timer);
    timers.current.clear();
  }, []);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-region" role="status" aria-live="polite" aria-atomic="false">
        {toasts.map((toast) => (
          <div className="toast" data-tone={toast.tone} key={toast.id}>
            <span>{toast.message}</span>
            <button type="button" className="toast-dismiss" aria-label={`关闭通知：${toast.message}`} onClick={() => dismiss(toast.id)}>
              <X aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
