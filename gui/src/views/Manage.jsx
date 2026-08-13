import React from "react";
import { useTranslation } from "react-i18next";
import { open } from "@tauri-apps/plugin-dialog";
import { toast } from "sonner";
import { useAppState } from "@/hooks/useAppState";
import { getSettings } from "@/lib/settings";
import {
  fetchStatus,
  fetchBackups,
  previewUninstall,
  executeUninstall,
  previewRecover,
  executeRecover,
  previewRestore,
  executeRestore,
  previewInstall,
  executeInstall,
} from "@/lib/api";
import { FadeIn } from "@/components/FadeIn";
import { ReportView } from "@/components/ReportView";
import { StatusPill } from "@/components/StatusPill";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

/**
 * pending 流：{ kind: 'uninstall'|'recover'|'restore'|'repair', preview, execArgs }
 * 统一 preview → ConfirmDialog → execute。
 */
export function Manage() {
  const { t } = useTranslation();
  const { cliInfo, operationInProgress } = useAppState();
  const [scope, setScope] = React.useState("user");
  const [projectDir, setProjectDir] = React.useState(() => getSettings().defaultProjectDir);
  const [includeRuntime, setIncludeRuntime] = React.useState(false);
  const [state, setState] = React.useState({ loading: false, status: null, backups: null, error: null });
  const [pending, setPending] = React.useState(null);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [doneReport, setDoneReport] = React.useState(null);

  const target = { scope, projectDir: projectDir.trim() };

  const load = React.useCallback(async () => {
    if (!cliInfo.path) return;
    if (scope !== "user" && !projectDir.trim()) {
      setState({ loading: false, status: null, backups: null, error: null });
      return;
    }
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const status = await fetchStatus({ ...target, runtime: scope === "user" });
      const backups = await fetchBackups(target).catch(() => null);
      setState({ loading: false, status, backups, error: null });
    } catch (error) {
      setState({ loading: false, status: null, backups: null, error: error?.message || String(error) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cliInfo.path, scope, projectDir]);

  React.useEffect(() => { load(); }, [load]);

  const recoveryRequired = Boolean(state.status?.recovery.recoveryRequired);

  const startPreview = async (kind, options) => {
    setBusy(true);
    setDoneReport(null);
    try {
      let preview;
      if (kind === "uninstall") preview = await previewUninstall(options);
      else if (kind === "recover") preview = await previewRecover(options);
      else if (kind === "restore") preview = await previewRestore(options);
      else preview = await previewInstall(options); // repair
      setPending({ kind, options, preview });
      setConfirmOpen(true);
    } catch (error) {
      toast.error(error?.message || String(error));
    } finally {
      setBusy(false);
    }
  };

  const runExecute = async () => {
    if (!pending) return;
    setConfirmOpen(false);
    setBusy(true);
    try {
      let report;
      if (pending.kind === "uninstall") report = await executeUninstall(pending.options);
      else if (pending.kind === "recover") report = await executeRecover(pending.options);
      else if (pending.kind === "restore") report = await executeRestore(pending.options);
      else report = await executeInstall(pending.options);
      setDoneReport(report);
      if (report.gate.ok) toast.success(t(`manage.${pending.kind === "repair" ? "recoverSuccess" : `${pending.kind}Success`}`));
      else toast.error(report.error || report.blockers.join("; "));
      setPending(null);
      load();
    } catch (error) {
      toast.error(error?.message || String(error));
    } finally {
      setBusy(false);
    }
  };

  const confirmTitleKey = {
    uninstall: "manage.uninstallConfirm",
    recover: "manage.recoverConfirm",
    restore: "manage.restoreConfirm",
    repair: "manage.runtimeRepairPreview",
  }[pending?.kind ?? "uninstall"];

  if (cliInfo.checked && !cliInfo.path) {
    return (
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("manage.title")}</h1>
        <p className="mt-4 rounded-[12px] border border-[var(--danger)] bg-[var(--danger-soft)] px-4 py-3 text-xs text-danger">
          {t("deploy.cliUnavailable")}
        </p>
      </FadeIn>
    );
  }

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("manage.title")}</h1>
      </FadeIn>

      {/* 范围选择 */}
      <FadeIn delay={0.06}>
        <section className="card-glass mt-5 flex flex-wrap items-end gap-3 p-5">
          <div>
            <label htmlFor="manage-scope" className="text-sm font-medium">{t("manage.scope")}</label>
            <Select value={scope} onValueChange={setScope}>
              <SelectTrigger id="manage-scope" className="mt-1.5 w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="user">{t("common.scopeUser")}</SelectItem>
                <SelectItem value="project">{t("common.scopeProject")}</SelectItem>
                <SelectItem value="local">{t("common.scopeLocal")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {scope !== "user" && (
            <div className="min-w-0 flex-1">
              <label htmlFor="manage-dir" className="text-sm font-medium">{t("manage.projectDir")}</label>
              <div className="mt-1.5 flex gap-2">
                <Input id="manage-dir" className="flex-1 font-mono text-xs" value={projectDir}
                  onChange={(e) => setProjectDir(e.target.value)} />
                <Button variant="outline" onClick={async () => {
                  const picked = await open({ directory: true });
                  if (picked) setProjectDir(picked);
                }}>{t("deploy.browse")}</Button>
              </div>
            </div>
          )}
          <Button variant="outline" size="sm" onClick={load} disabled={busy || state.loading || !cliInfo.path}>
            {state.loading ? t("common.loading") : t("common.refresh")}
          </Button>
        </section>
      </FadeIn>

      {state.error && (
        <FadeIn delay={0.08}>
          <div className="mt-4">
            <p className="text-xs text-danger">{t("manage.loadFailed")}</p>
            <pre className="log-block mt-1.5">{state.error}</pre>
          </div>
        </FadeIn>
      )}

      {state.status && (
        <FadeIn delay={0.1}>
          <section className="card-glass mt-4 p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium">{t("dashboard.projectStatus")}</h2>
              <StatusPill health={state.status.health} />
            </div>

            {/* 恢复优先 */}
            {recoveryRequired && (
              <div className="mt-3 rounded-[12px] border border-[var(--danger)] bg-[var(--danger-soft)] p-4">
                <p className="text-xs text-danger">{t("manage.recoveryBanner")}</p>
                <Button size="sm" variant="destructive" className="mt-2.5"
                  disabled={busy || operationInProgress}
                  onClick={() => startPreview("recover", target)}>
                  {t("manage.recoverPreview")}
                </Button>
              </div>
            )}
          </section>
        </FadeIn>
      )}

      {/* 卸载 */}
      {state.status && (
        <FadeIn delay={0.14}>
          <section className="card-glass mt-4 p-5">
            <h2 className="text-sm font-medium">{t("manage.uninstall")}</h2>
            {scope === "user" && (
              <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-secondary-foreground">
                <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={includeRuntime}
                  onChange={(e) => setIncludeRuntime(e.target.checked)} />
                {t("manage.uninstallRuntime")}
              </label>
            )}
            <p className="mt-2 text-xs text-muted-foreground">{t("manage.confirmUninstallBody")}</p>
            <div className="mt-3">
              <Button size="sm" variant="destructive" disabled={busy || operationInProgress || recoveryRequired}
                onClick={() => startPreview("uninstall", { ...target, runtime: includeRuntime })}>
                {t("manage.uninstallPreview")}
              </Button>
              {recoveryRequired && <p className="mt-1.5 text-xs text-danger">{t("manage.mustRecover")}</p>}
            </div>
          </section>
        </FadeIn>
      )}

      {/* runtime 修复（user scope） */}
      {scope === "user" && state.status?.runtimeReadiness && !state.status.runtimeReadiness.runtimeReady && (
        <FadeIn delay={0.16}>
          <section className="card-glass mt-4 p-5">
            <h2 className="text-sm font-medium">{t("manage.runtimeRepair")}</h2>
            <p className="mt-1.5 text-xs text-muted-foreground">{t("manage.runtimeRepairDesc")}</p>
            <Button size="sm" className="mt-3" disabled={busy || operationInProgress || recoveryRequired}
              onClick={() => startPreview("repair", { scope: "user", runtime: true })}>
              {t("manage.runtimeRepairPreview")}
            </Button>
          </section>
        </FadeIn>
      )}

      {/* 受控备份 */}
      {state.backups && (
        <FadeIn delay={0.18}>
          <section className="card-glass mt-4 p-5">
            <h2 className="text-sm font-medium">{t("manage.backups")}</h2>
            {state.backups.backups.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">{t("manage.backupsEmpty")}</p>
            ) : (
              <>
                <p className="mt-1.5 text-xs text-muted-foreground">{t("manage.restoreManagedOnly")}</p>
                <ul className="mt-3 space-y-3">
                  {state.backups.backups.map((backup) => (
                    <li key={backup.backupPath} className="rounded-[10px] border border-border p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Badge variant="accent">{backup.kind}</Badge>
                            <span className="font-mono text-xs text-secondary-foreground">{backup.targetName}</span>
                          </div>
                          <div className="mt-1 break-all font-mono text-xs text-muted-foreground">{backup.backupPath}</div>
                          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-[11px] text-muted-foreground">
                            {backup.created && <span>{backup.created}</span>}
                            {backup.sizeBytes != null && <span>{backup.sizeBytes} {t("deploy.bytes")}</span>}
                            {backup.sha256 && <span className="break-all">{backup.sha256.slice(0, 16)}…</span>}
                          </div>
                        </div>
                        <Button size="sm" variant="outline" className="shrink-0"
                          disabled={busy || operationInProgress || recoveryRequired}
                          onClick={() => startPreview("restore", {
                            target: backup.targetName,
                            backup: backup.backupPath,
                            scope,
                            projectDir: projectDir.trim(),
                          })}>
                          {t("manage.restore")}
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </FadeIn>
      )}

      {/* 执行结果 */}
      {doneReport && (
        <FadeIn delay={0.1}>
          <section className="card-glass mt-4 p-5">
            <h2 className={cn("text-sm font-medium", doneReport.gate.ok ? "text-ok" : "text-danger")}>
              {doneReport.gate.ok ? t("common.confirm") + " ✓" : t("errors.execFailed")}
            </h2>
            <div className="mt-3"><ReportView report={doneReport} /></div>
          </section>
        </FadeIn>
      )}

      {/* 预览 + 二次确认 */}
      {pending && (
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={(openNext) => { setConfirmOpen(openNext); if (!openNext) setPending(null); }}
          title={t(confirmTitleKey)}
          body={<ReportView report={pending.preview} />}
          confirmText={t("common.confirm") + " (--yes)"}
          confirmDisabled={!pending.preview.gate.ok}
          danger={pending.kind === "uninstall"}
          onConfirm={runExecute}
        />
      )}
    </div>
  );
}
