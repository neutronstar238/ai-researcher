import { X } from "lucide-react";
import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { FOCUSABLE_SELECTOR, registerOverlay, type OverlayHandle } from "./overlayManager";

export interface DrawerProps {
  open: boolean;
  title: string;
  wide?: boolean;
  onClose(): void;
  children: ReactNode;
}

export function Drawer({ open, title, wide = false, onClose, children }: DrawerProps) {
  const titleId = useId();
  const drawerRef = useRef<HTMLElement>(null);
  const overlayRef = useRef<OverlayHandle | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open || !drawerRef.current) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const handle = registerOverlay(drawerRef.current, previousFocus, () => onCloseRef.current());
    overlayRef.current = handle;
    drawerRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus();

    return () => {
      handle.unregister();
      if (overlayRef.current === handle) overlayRef.current = null;
    };
  }, [open]);

  if (!open) return null;

  const trapFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const focusable = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? []);
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
      data-testid="drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && overlayRef.current?.isTopmost()) onClose();
      }}
    >
      <section
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="drawer"
        data-width={wide ? "wide" : "default"}
        onKeyDown={trapFocus}
      >
        <div className="dialog-heading">
          <h2 id={titleId}>{title}</h2>
          <button className="icon-button" type="button" aria-label="关闭" onClick={onClose}>
            <X aria-hidden="true" />
          </button>
        </div>
        <div className="drawer-content">{children}</div>
      </section>
    </div>
  );
}
