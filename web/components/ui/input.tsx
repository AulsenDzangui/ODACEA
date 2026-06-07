import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-(--ink-200) bg-white px-3 py-1 text-sm transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-(--ink-400) focus-visible:border-(--graphite-600) focus-visible:ring-3 focus-visible:ring-(--graphite-700)/15 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-(--paper-100) disabled:opacity-60 aria-invalid:border-(--danger-500) aria-invalid:ring-3 aria-invalid:ring-(--danger-500)/20 dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
}

export { Input }
