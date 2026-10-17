import { useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/api"
import type { Setting } from "@/lib/types"

const KEY = "log_get_requests"
/** Mirror the backend default — used until the row exists. */
const FALLBACK = false

/**
 * Admin-only: whether successful GETs get an access-log row. Stored
 * server-side, so it reaches every terminal — if it sits among per-browser
 * preferences, badge it "affects every terminal".
 */
export function RequestLoggingSwitch({
  row,
  onSaved,
}: {
  row: Setting | undefined
  onSaved: (row: Setting) => void
}) {
  const on = row ? row.value === "true" : FALLBACK
  const [saving, setSaving] = useState(false)

  const toggle = async (next: boolean) => {
    if (saving) return
    setSaving(true)
    try {
      onSaved(await api.updateSetting(KEY, next ? "true" : "false"))
      toast.success(next ? "Logging every request" : "Successful GETs no longer logged", {
        description: next
          ? "Reads and writes both land in the request log."
          : "Writes, and anything that failed, are still recorded.",
      })
    } catch (e) {
      toast.error("Could not save the setting", { description: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <label htmlFor="log-get" className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border p-4">
      <span className="space-y-1">
        <span className="block text-sm font-medium">Log successful GET requests</span>
        <span className="block text-xs text-muted-foreground">
          {on
            ? "On — every read is logged. Expect a lot of rows."
            : "Off — only writes and failed requests are logged (recommended)."}
        </span>
      </span>
      {saving ? (
        <Loader2 className="size-4 animate-spin text-muted-foreground" />
      ) : (
        <Switch id="log-get" checked={on} onCheckedChange={(v) => void toggle(v)} />
      )}
    </label>
  )
}
