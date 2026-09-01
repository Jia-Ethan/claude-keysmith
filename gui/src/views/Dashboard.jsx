import React from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw, Check, Minus, AlertTriangle, Wrench } from "lucide-react";
import { useAppState } from "@/hooks/useAppState";
import { getSettings, removeRecentProject } from "@/lib/settings";
import { fetchStatus, fetchDoctor } from "@/lib/api";
import { setView } from "@/lib/store";
import { buildInfo } from "@/lib/buildInfo";
import { FadeIn } from "@/components/FadeIn";
import { StatusPill } from "@/components/StatusPill";
import { RawJson } from "@/components/ReportView";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function PresenceRow({ label, present }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1 text-xs">
      <span className="text-secondary-foreground">{label}</span>
      {present ? (
        <Check className="size-3.5 text-ok" aria-label="present" />
      ) : (
        <Minus className="size-3.5 text-muted-foreground" aria-label="absent" />
      )}
    </div>
  );
}

function UserScopeCard({ status, doctor, onRepair }) {
  const { t } = useTranslation();
  const readiness = status.runtimeReadiness;
  const recovery = status.recovery;
  const identity = status.sourceIdentity;

  return (
    <div className="mt-3 space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <section className="rounded-[12px] border border-border bg-[color-mix(in_srgb,var(--bg-secondary)_55%,transparent)] p-3.5">
          <h3 className="text-xs font-medium text-muted-foreground">{t("dashboard.presenceTitle")}</h3>
          <div className="mt-1.5 divide-y divide-border/60">
            <PresenceRow label={t("dashboard.memoryFile")} present={status.presence.memoryFile} />
            <PresenceRow label={t("dashboard.importBlock")} present={status.presence.importBlock} />
            <PresenceRow label={t("dashboard.instructionFile")} present={status.presence.instructionFile} />
            <PresenceRow label={t("dashboard.systemPrompt")} present={status.presence.systemPrompt} />
            <PresenceRow label={t("dashboard.appendPrompt")} present={status.presence.appendPrompt} />
            <PresenceRow label={t("dashboard.settingsFile")} present={status.presence.settingsFile} />
            <PresenceRow label={t("dashboard.shellWrapper")} present={status.presence.shellWrapper} />
          </div>
        </section>

        <section className="rounded-[12px] border border-border bg-[color-mix(in_srgb,var(--bg-secondary)_55%,transparent)] p-3.5">
          <h3 className="text-xs font-medium text-muted-foreground">{t("dashboard.alignmentTitle")}</h3>
          <div className="mt-1.5 divide-y divide-border/60">
            <PresenceRow label={t("dashboard.importBlock")} present={status.alignment.importBlockPresent} />
            <PresenceRow label={t("dashboard.settingsAligned")} present={status.alignment.settingsSystemPromptAligned} />
            <PresenceRow label={t("dashboard.wrapperCurrent")} present={status.alignment.shellWrapperCurrent} />
          </div>
          <div className="mt-2.5 space-y-1 text-xs">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">{t("dashboard.sourceKind")}</span>
              <Badge variant="accent">{identity.kind}</Badge>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">{t("dashboard.drift")}</span>
              <span className={identity.drift ? "text-warn" : "text-ok"}>
                {identity.drift ? t("common.yes") : t("common.no")}
              </span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">{t("dashboard.promptDrift")}</span>
              <span className={identity.settingsSystemPromptDrift ? "text-warn" : "text-ok"}>
                {identity.settingsSystemPromptDrift ? t("common.yes") : t("common.no")}
              </span>
            </div>
          </div>
        </section>
      </div>

      {readiness && (
        <section className="rounded-[12px] border border-border bg-[color-mix(in_srgb,var(--bg-secondary)_55%,transparent)] p-3.5">
          <h3 className="text-xs font-medium text-muted-foreground">{t("dashboard.runtimeTitle")}</h3>
          <div className="mt-2 grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">{t("dashboard.upstream")}</span>
              <span className={cn("break-all font-mono text-right", readiness.upstreamExists ? "text-secondary-foreground" : "text-danger")}>
                {readiness.upstreamPath || t("dashboard.upstreamMissing")}
              </span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">{t("dashboard.wrapperCurrent")}</span>
              <span className={readiness.shellWrapperCurrent ? "text-ok" : "text-warn"}>
                {readiness.shellWrapperCurrent ? t("common.yes") : t("common.no")}
              </span>
            </div>
          </div>
          {readiness.legacyLauncherConflict && (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-danger">
              <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
              {t("health.conflict")}: legacy launcher
            </p>
          )}
          {doctor && doctor.repairActions.length > 0 && !readiness.runtimeReady && (
            <div className="mt-3">
              <h4 className="text-xs font-medium text-muted-foreground">{t("dashboard.repairHints")}</h4>
              <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-secondary-foreground">
                {doctor.repairActions.map((action, index) => <li key={index}>{action}</li>)}
              </ul>
              <Button size="sm" variant="secondary" className="mt-2" onClick={onRepair}>
                <Wrench className="size-3.5" aria-hidden="true" />
                {t("dashboard.repairAction")}
              </Button>
            </div>
          )}
        </section>
      )}

      {(recovery.recoveryRequired || recovery.journalCount > 0 || recovery.lockPresent) && (
        <section className="rounded-[12px] border border-[var(--danger)] bg-[var(--danger-soft)] p-3.5">
          <h3 className="text-xs font-medium text-danger">{t("dashboard.recoveryTitle")}</h3>
          <div className="mt-2 space-y-1 text-xs text-secondary-foreground">
            <div className="flex justify-between"><span>{t("dashboard.journals")}</span><span className="font-mono">{recovery.journalCount}</span></div>
            <div className="flex justify-between"><span>{t("dashboard.conflicts")}</span><span className="font-mono">{recovery.conflicts.length}</span></div>
            <div className="flex justify-between">
              <span>{t("dashboard.lock")}</span>
              <span>{recovery.lockPresent ? (recovery.lockLive ? t("dashboard.lockLive") : t("dashboard.lockStale")) : t("dashboard.lockNone")}</span>
            </div>
          </div>
          {recovery.recoveryRequired && (
            <Button size="sm" variant="destructive" className="mt-2.5" onClick={() => setView("manage")}>
              {t("dashboard.goManage")}
            </Button>
          )}
        </section>
      )}

      <RawJson data={status.raw} />
    </div>
  );
}

function ProjectCard({ entry }) {
  const { t } = useTranslation();
  const [state, setState] = React.useState({ loading: true, status: null, error: null });

  const load = React.useCallback(async () => {
    setState({ loading: true, status: null, error: null });
    try {
      const status = await fetchStatus({ scope: entry.scope, projectDir: entry.path });
      setState({ loading: false, status, error: null });
    } catch (error) {
      setState({ loading: false, status: null, error: error?.message || String(error) });
    }
  }, [entry.path, entry.scope]);

  React.useEffect(() => { load(); }, [load]);

  return (
    <div className="card-glass mt-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-all font-mono text-xs text-secondary-foreground">{entry.path}</div>
          <Badge variant="outline" className="mt-1">{t(`common.scope${entry.scope === "local" ? "Local" : "Project"}`)}</Badge>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {state.loading ? (
            <span className="text-xs text-muted-foreground"><span className="spinner mr-1" aria-hidden="true" />{t("common.loading")}</span>
          ) : state.error ? (
            <span className="text-xs text-danger">{t("dashboard.loadFailed")}</span>
          ) : (
            <StatusPill health={state.status.health} />
          )}
          <Button size="sm" variant="ghost" onClick={() => { removeRecentProject(entry.path); }}>
            {t("common.remove")}
          </Button>
        </div>
      </div>
      {state.error && <pre className="log-block mt-2">{state.error}</pre>}
      {state.status?.recovery.recoveryRequired && (
        <p className="mt-2 text-xs text-danger">{t("manage.mustRecover")}</p>
      )}
    </div>
  );
}

export function Dashboard() {
  const { t } = useTranslation();
  const { cliInfo, operationInProgress } = useAppState();
  const [state, setState] = React.useState({ loading: false, status: null, doctor: null, error: null });
  const [projects, setProjects] = React.useState(() => getSettings().recentProjects);

  React.useEffect(() => {
    const interval = setInterval(() => setProjects(getSettings().recentProjects), 1500);
    return () => clearInterval(interval);
  }, []);

  const refresh = React.useCallback(async () => {
    if (!cliInfo.path) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const status = await fetchStatus({ scope: "user", runtime: true });
      let doctor = null;
      if (status.runtimeReadiness && !status.runtimeReadiness.runtimeReady) {
        try { doctor = await fetchDoctor(); } catch { /* doctor 失败不阻塞主状态 */ }
      }
      setState({ loading: false, status, doctor, error: null });
    } catch (error) {
      setState({ loading: false, status: null, doctor: null, error: error?.message || String(error) });
    }
  }, [cliInfo.path]);

  React.useEffect(() => {
    if (cliInfo.checked && cliInfo.path) refresh();
  }, [cliInfo.checked, cliInfo.path, refresh]);

  const upstreamMissing = state.status?.runtimeReadiness && !state.status.runtimeReadiness.upstreamExists;

  return (
    <div>
      <FadeIn className="flex items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">{t("dashboard.title")}</h1>
        <Button variant="outline" size="sm" onClick={refresh}
          disabled={!cliInfo.path || state.loading || operationInProgress}>
          <RefreshCw className={cn("size-3.5", state.loading && "animate-spin")} aria-hidden="true" />
          {state.loading ? t("dashboard.refreshing") : t("dashboard.refresh")}
        </Button>
      </FadeIn>

      {/* 版本与构建信息 */}
      <FadeIn delay={0.06}>
        <section className="card-glass mt-5 p-5">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">{t("dashboard.guiVersion")}</dt>
            <dd className="font-mono text-secondary-foreground">{buildInfo.guiVersion}</dd>
            <dt className="text-muted-foreground">{t("dashboard.cliVersion")}</dt>
            <dd className="break-all font-mono text-secondary-foreground">
              {!cliInfo.checked ? t("dashboard.checkingCli")
                : cliInfo.version || cliInfo.error || t("settings.notFound")}
            </dd>
            <dt className="text-muted-foreground">{t("dashboard.buildChannel")}</dt>
            <dd className="font-mono text-secondary-foreground">{buildInfo.channel}</dd>
            <dt className="text-muted-foreground">{t("dashboard.sourceCommit")}</dt>
            <dd className="break-all font-mono text-secondary-foreground">
              {buildInfo.sourceCommit || t("dashboard.commitUnavailable")}
            </dd>
            <dt className="text-muted-foreground">{t("dashboard.claudeCode")}</dt>
            <dd className="break-all font-mono text-secondary-foreground">
              {state.status?.runtimeReadiness
                ? state.status.runtimeReadiness.upstreamPath || t("dashboard.upstreamMissing")
                : t("common.notRun")}
            </dd>
          </dl>
        </section>
      </FadeIn>

      {/* CLI 缺失 */}
      {cliInfo.checked && !cliInfo.path && (
        <FadeIn delay={0.1}>
          <section className="mt-4 rounded-[14px] border border-[var(--danger)] bg-[var(--danger-soft)] p-5">
            <h2 className="text-sm font-medium text-danger">{t("dashboard.cliMissingTitle")}</h2>
            <p className="mt-1.5 text-xs text-secondary-foreground">{t("dashboard.cliMissingHint")}</p>
            <Button size="sm" variant="secondary" className="mt-3" onClick={() => setView("settings")}>
              {t("nav.settings")}
            </Button>
          </section>
        </FadeIn>
      )}

      {/* Claude Code 缺失提示 */}
      {upstreamMissing && (
        <FadeIn delay={0.12}>
          <p className="mt-4 rounded-[12px] border border-[var(--warn)] bg-[var(--warn-soft)] px-4 py-3 text-xs text-warn">
            {t("dashboard.claudeMissing")}
          </p>
        </FadeIn>
      )}

      {/* 用户范围卡片 */}
      {cliInfo.path && (
        <FadeIn delay={0.14}>
          <section className="card-glass mt-4 p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-medium">{t("dashboard.userScope")}</h2>
              {state.loading ? (
                <span className="text-xs text-muted-foreground"><span className="spinner mr-1" aria-hidden="true" />{t("common.loading")}</span>
              ) : state.status ? (
                <StatusPill health={state.status.health} />
              ) : null}
            </div>
            {state.error && (
              <div className="mt-3">
                <p className="text-xs text-danger">{t("dashboard.loadFailed")}</p>
                <pre className="log-block mt-1.5">{state.error}</pre>
                <Button size="sm" variant="outline" className="mt-2" onClick={refresh}>{t("common.retry")}</Button>
              </div>
            )}
            {state.status && (
              <UserScopeCard
                status={state.status}
                doctor={state.doctor}
                onRepair={() => setView("deploy")}
              />
            )}
            {!state.loading && !state.status && !state.error && (
              <p className="mt-3 text-xs text-muted-foreground">{t("common.notRun")}</p>
            )}
          </section>
        </FadeIn>
      )}

      {/* 项目卡片（仅用户显式选择过的路径） */}
      <FadeIn delay={0.2}>
        <section className="mt-6">
          <h2 className="text-sm font-medium">{t("dashboard.projectCards")}</h2>
          {projects.length === 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">{t("dashboard.noProjects")}</p>
          ) : (
            projects.map((entry) => <ProjectCard key={`${entry.scope}:${entry.path}`} entry={entry} />)
          )}
        </section>
      </FadeIn>

      {cliInfo.path && state.status?.health === "not-installed" && (
        <FadeIn delay={0.24}>
          <Button className="mt-4" onClick={() => setView("deploy")}>{t("dashboard.goDeploy")}</Button>
        </FadeIn>
      )}
    </div>
  );
}
