import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface ErrorBannerProps {
  title: string;
  description?: string;
  className?: string;
}

export function ErrorBanner({ title, description, className }: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" aria-hidden="true" />
      <div>
        <div className="font-semibold">{title}</div>
        {description ? <div className="mt-1 text-destructive/80">{description}</div> : null}
      </div>
    </div>
  );
}
