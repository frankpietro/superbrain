import { teamInitials } from "@/lib/format";
import { cn } from "@/lib/utils";

interface TeamCrestProps {
  name: string;
  className?: string;
}

export function TeamCrest({ name, className }: TeamCrestProps) {
  return (
    <span
      className={cn(
        "inline-flex h-7 w-7 flex-none items-center justify-center rounded-full bg-accent text-xs font-bold text-accent-foreground",
        className,
      )}
      aria-hidden="true"
    >
      {teamInitials(name) || "?"}
    </span>
  );
}
