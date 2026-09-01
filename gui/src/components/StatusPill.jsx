import React from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

const TONE = {
  healthy: "text-ok",
  "partial-install": "text-warn",
  "upgrade-required": "text-warn",
  drifted: "text-warn",
  "recovery-required": "text-danger",
  conflict: "text-danger",
  "not-installed": "text-muted-foreground",
  unknown: "text-muted-foreground",
};

const DOT = {
  healthy: "bg-[var(--ok)]",
  "partial-install": "bg-[var(--warn)]",
  "upgrade-required": "bg-[var(--warn)]",
  drifted: "bg-[var(--warn)]",
  "recovery-required": "bg-[var(--danger)]",
  conflict: "bg-[var(--danger)]",
  "not-installed": "bg-[var(--text-muted)]",
  unknown: "bg-[var(--text-muted)]",
};

/** 状态脉冲点 + 本地化标签；健康态不 pulse（reduced-motion 见 globals.css）。 */
export function StatusPill({ health = "unknown", className }) {
  const { t } = useTranslation();
  const tone = TONE[health] ?? TONE.unknown;
  const dot = DOT[health] ?? DOT.unknown;
  return (
    <span className={cn("inline-flex items-center gap-2 text-sm font-medium", tone, className)}>
      <span className={cn("pulse-dot", dot)} aria-hidden="true" />
      {t(`health.${health}`)}
    </span>
  );
}
