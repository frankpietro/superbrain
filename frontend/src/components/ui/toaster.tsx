import * as React from "react";
import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
  type ToastProps,
} from "./toast";

interface ToastState extends Omit<ToastProps, "children"> {
  id: string;
  title?: string;
  description?: string;
}

type ToastListener = (toasts: ToastState[]) => void;

const listeners = new Set<ToastListener>();
let active: ToastState[] = [];
let counter = 0;

function emit(): void {
  for (const l of listeners) l(active);
}

export function toast(input: Omit<ToastState, "id">): string {
  const id = `t-${++counter}`;
  active = [...active, { id, ...input }];
  emit();
  return id;
}

export function dismissToast(id: string): void {
  active = active.filter((t) => t.id !== id);
  emit();
}

export function Toaster() {
  const [items, setItems] = React.useState<ToastState[]>(active);

  React.useEffect(() => {
    const listener: ToastListener = (next) => setItems(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return (
    <ToastProvider swipeDirection="right">
      {items.map(({ id, title, description, ...props }) => (
        <Toast
          key={id}
          {...props}
          onOpenChange={(open) => {
            if (!open) dismissToast(id);
          }}
        >
          <div className="flex-1 space-y-0.5">
            {title ? <ToastTitle>{title}</ToastTitle> : null}
            {description ? <ToastDescription>{description}</ToastDescription> : null}
          </div>
          <ToastClose />
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}
