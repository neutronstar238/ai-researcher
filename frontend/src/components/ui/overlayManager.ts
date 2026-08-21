export const FOCUSABLE_SELECTOR = "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

interface OverlayEntry {
  id: symbol;
  container: HTMLElement;
  restoreFocus: HTMLElement | null;
  onEscape(): void;
}

export interface OverlayHandle {
  isTopmost(): boolean;
  unregister(): void;
}

const stack: OverlayEntry[] = [];
let originalBodyOverflow = "";

function focusFirst(container: HTMLElement): void {
  container.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus();
}

function handleEscape(event: KeyboardEvent): void {
  if (event.key !== "Escape") return;
  const topmost = stack.at(-1);
  if (!topmost) return;

  event.preventDefault();
  event.stopPropagation();
  topmost.onEscape();
}

function lockBody(): void {
  if (stack.length !== 0) return;
  originalBodyOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", handleEscape);
}

function unlockBody(): void {
  if (stack.length !== 0) return;
  document.body.style.overflow = originalBodyOverflow;
  document.removeEventListener("keydown", handleEscape);
}

export function registerOverlay(
  container: HTMLElement,
  restoreFocus: HTMLElement | null,
  onEscape: () => void,
): OverlayHandle {
  lockBody();
  const entry: OverlayEntry = { id: Symbol("overlay"), container, restoreFocus, onEscape };
  stack.push(entry);
  let registered = true;

  return {
    isTopmost() {
      return registered && stack.at(-1)?.id === entry.id;
    },
    unregister() {
      if (!registered) return;
      registered = false;
      const index = stack.findIndex((candidate) => candidate.id === entry.id);
      if (index < 0) return;

      const wasTopmost = index === stack.length - 1;
      const nextEntry = stack[index + 1];
      if (nextEntry?.restoreFocus && entry.container.contains(nextEntry.restoreFocus)) {
        nextEntry.restoreFocus = entry.restoreFocus;
      }
      stack.splice(index, 1);

      if (wasTopmost) {
        const newTopmost = stack.at(-1);
        if (newTopmost) {
          if (entry.restoreFocus?.isConnected && newTopmost.container.contains(entry.restoreFocus)) {
            entry.restoreFocus.focus();
          } else {
            focusFirst(newTopmost.container);
          }
        } else if (entry.restoreFocus?.isConnected) {
          entry.restoreFocus.focus();
        }
      }

      unlockBody();
    },
  };
}
