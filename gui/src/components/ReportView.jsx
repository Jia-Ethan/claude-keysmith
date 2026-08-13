import React from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

const ACTION_VARIANT = {
  write: "accent",
  backup: "yellow",
  remove: "red",
  noop: "gray",
  restore: "green",
};

function actionLabel(t, action) {
  const key = `common.action${action[0]?.toUpperCase() ?? ""}${action.slice(1)}`;
  const translated = t(key);
  return translated === key ? action : translated;
}

/** 写操作报告的结构化视图：target/source/actions/backups/warnings/blockers + 按需展开的原始 JSON。 */
export function ReportView({ report, showTarget = true }) {
  const { t } = useTranslation();
  if (!report) return null;
  const targetEntries = Object.entries(report.target || {}).filter(([, v]) => typeof v === "string" && v);

  return (
    <div className="space-y-4">
      {showTarget && targetEntries.length > 0 && (
        <section>
          <h3 className="text-xs font-medium text-muted-foreground">{t("deploy.previewTarget")}</h3>
          <dl className="mt-1.5 space-y-1">
            {targetEntries.map(([key, value]) => (
              <div key={key} className="flex gap-2 text-xs">
                <dt className="shrink-0 font-mono text-muted-foreground">{key}</dt>
                <dd className="break-all font-mono text-secondary-foreground">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {report.source && (
        <section>
          <h3 className="text-xs font-medium text-muted-foreground">{t("deploy.previewSource")}</h3>
          <div className="mt-1.5 space-y-1 text-xs">
            <div className="flex gap-2">
              <span className="shrink-0 text-muted-foreground">{t("deploy.kind")}</span>
              <Badge variant="accent">{report.source.kind}</Badge>
            </div>
            {report.source.path && (
              <div className="break-all font-mono text-secondary-foreground">{report.source.path}</div>
            )}
            <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-muted-foreground">
              {report.source.sizeBytes != null && (
                <span>{t("deploy.size")}: {report.source.sizeBytes} {t("deploy.bytes")}</span>
              )}
              {report.source.sha256 && (
                <span className="break-all">{t("deploy.sha256")}: {report.source.sha256}</span>
              )}
            </div>
          </div>
        </section>
      )}

      {report.actions.length > 0 && (
        <section>
          <h3 className="text-xs font-medium text-muted-foreground">{t("deploy.plannedActions")}</h3>
          <ul className="mt-1.5 space-y-1.5">
            {report.actions.map((action, index) => (
              <li key={index} className="flex items-start gap-2 text-xs">
                <Badge variant={ACTION_VARIANT[action.action] ?? "default"} className="mt-px shrink-0">
                  {actionLabel(t, action.action)}
                </Badge>
                <div className="min-w-0">
                  <div className="break-all font-mono text-secondary-foreground">{action.path}</div>
                  {action.detail && <div className="text-muted-foreground">{action.detail}</div>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {report.backups.length > 0 && (
        <section>
          <h3 className="text-xs font-medium text-muted-foreground">{t("deploy.plannedBackups")}</h3>
          <ul className="mt-1.5 space-y-1.5">
            {report.backups.map((backup, index) => (
              <li key={index} className="text-xs">
                <div className="break-all font-mono text-secondary-foreground">
                  {backup.backupPath || `${backup.target} (${t("deploy.plannedBackups").toLowerCase()})`}
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-muted-foreground">
                  {backup.sizeBytes != null && <span>{backup.sizeBytes} {t("deploy.bytes")}</span>}
                  {backup.sha256 && <span className="break-all">{backup.sha256.slice(0, 16)}…</span>}
                  {backup.created && <span>{backup.created}</span>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {report.warnings.length > 0 && (
        <section>
          <h3 className="text-xs font-medium text-warn">{t("deploy.warnings")}</h3>
          <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-xs text-secondary-foreground">
            {report.warnings.map((warning, index) => <li key={index}>{warning}</li>)}
          </ul>
        </section>
      )}

      {report.blockers.length > 0 && (
        <section>
          <h3 className="text-xs font-medium text-danger">{t("deploy.blockers")}</h3>
          <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-xs text-danger">
            {report.blockers.map((blocker, index) => <li key={index}>{blocker}</li>)}
          </ul>
        </section>
      )}

      {report.reloadRequired && (
        <p className="rounded-[10px] border border-[var(--warn)] bg-[var(--warn-soft)] px-3 py-2 text-xs text-warn">
          {report.reloadHint || t("dashboard.reloadRequired")}
        </p>
      )}

      <RawJson data={report.raw} />
    </div>
  );
}

/** 按需展开的原始 JSON；避免常驻大段文本。 */
export function RawJson({ data }) {
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(false);
  if (!data) return null;
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} aria-hidden="true" />
        {t("common.rawJson")}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="log-block mt-1.5">{JSON.stringify(data, null, 2)}</pre>
      </CollapsibleContent>
    </Collapsible>
  );
}
