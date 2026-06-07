import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-md border border-(--ink-200) bg-white px-3 py-2 text-sm transition-colors outline-none placeholder:text-(--ink-400) focus-visible:border-(--graphite-600) focus-visible:ring-3 focus-visible:ring-(--graphite-700)/15 disabled:cursor-not-allowed disabled:bg-(--paper-100) disabled:opacity-60 aria-invalid:border-(--danger-500) aria-invalid:ring-3 aria-invalid:ring-(--danger-500)/20 dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
