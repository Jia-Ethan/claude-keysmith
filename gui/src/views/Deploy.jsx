import React from "react";
import { useTranslation } from "react-i18next";
import { open } from "@tauri-apps/plugin-dialog";
import { toast } from "sonner";
import { ChevronRight } from "lucide-react";
import { useAppState } from "@/hooks/useAppState";
import { getSettings, rememberProject } from "@/lib/settings";
import { previewInstall, executeInstall, fetchStatus, fetchDoctor } from "@/lib/api";
import { FadeIn } from "@/components/FadeIn";
import { ReportView, RawJson } from "@/components/ReportView";
import { StatusPill } from "@/components/StatusPill";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const NAME_RE = /^[A-Za-z0-9._-]+$/;

function StepHeader({ step }) {
  const { t } = useTranslation();
  const steps = ["stepChoose", "stepPreview", "stepConfirm"];
  return (
    <ol className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
      {steps.map((key, index) => (
        <li key={key} className="flex items-center gap-1.5">
          <span className={cn(
            "inline-flex size-5 items-center justify-center rounded-full border text-[10px] font-medium",
            index + 1 === step
              ? "border-accent bg-accent text-white"
              : index + 1 < step
                ? "border-[var(--ok)] text-ok"
                : "border-border text-muted-foreground",
          )}>
            {index + 1}
          </span>
          <span className={index + 1 === step ? "font-medium text-foreground" : "text-muted-foreground"}>
            {t(`deploy.${key}`)}
          </span>
          {index < steps.length - 1 && <ChevronRight className="size-3 text-muted-foreground" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

const initialForm = {
  scope: "user",
  projectDir: "",
  name: "claude-project-rules",
  sourceMode: "builtin", // builtin | local
  file: "",
  runtime: false,
  appendMode: "builtin",
  appendFile: "",
  maxTokens: "",
};

export function validateDeployForm(form, t) {
  const errors = [];
  const name = form.name.trim();
  if (!NAME_RE.test(name) || name.includes("..") || name === ".") errors.push(t("deploy.nameInvalid"));
  if (form.scope !== "user" && !form.projectDir.trim()) errors.push(t("deploy.projectDirRequired"));
  if (form.sourceMode === "local" && !form.file.trim()) errors.push(t("deploy.fileRequired"));
  if (form.scope === "user" && form.runtime) {
    if (form.appendMode === "local" && !form.appendFile.trim()) errors.push(t("deploy.fileRequired"));
    const maxTokens = form.maxTokens.trim();
    if (maxTokens && (!/^\d+$/.test(maxTokens) || Number(maxTokens) <= 0)) {
      errors.push(t("deploy.maxTokensInvalid"));
    }
  }
  return errors;
}

export function deployOptionsFromForm(form) {
  return {
    scope: form.scope,
    projectDir: form.projectDir.trim(),
    name: form.name.trim(),
    file: form.sourceMode === "local" ? form.file.trim() : "",
    runtime: form.scope === "user" && form.runtime,
    appendFile: form.scope === "user" && form.runtime && form.appendMode === "local"
      ? form.appendFile.trim()
      : "",
    maxTokens: form.scope === "user" && form.runtime && form.maxTokens.trim()
      ? Number(form.maxTokens.trim())
      : null,
  };
}

export function Deploy() {
  const { t } = useTranslation();
  const { cliInfo, operationInProgress } = useAppState();
  const [step, setStep] = React.useState(1);
  const [form, setForm] = React.useState(() => ({
    ...initialForm,
    projectDir: getSettings().defaultProjectDir,
  }));
  const [formErrors, setFormErrors] = React.useState([]);
  const [preview, setPreview] = React.useState(null);
  const [previewError, setPreviewError] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [result, setResult] = React.useState(null); // { report, postStatus, doctor, error }
  const patch = (delta) => setForm((f) => ({ ...f, ...delta }));

  const pickDirectory = async () => {
    const picked = await open({ directory: true });
    if (picked) patch({ projectDir: picked });
  };
  const pickMarkdown = async (apply) => {
    const picked = await open({ filters: [{ name: "Markdown", extensions: ["md"] }] });
    if (picked) apply(picked);
  };

  const runPreview = async () => {
    const errors = validateDeployForm(form, t);
    setFormErrors(errors);
    if (errors.length > 0) return;
    setBusy(true);
    setPreview(null);
    setPreviewError(null);
    try {
      const report = await previewInstall(deployOptionsFromForm(form));
      setPreview(report);
      setStep(2);
    } catch (error) {
      setPreviewError(error?.message || String(error));
    } finally {
      setBusy(false);
    }
  };

  const runExecute = async () => {
    setConfirmOpen(false);
    setBusy(true);
    setResult(null);
    try {
      const report = await executeInstall(deployOptionsFromForm(form));
      if (form.scope !== "user") rememberProject(form.projectDir, form.scope);
      let postStatus = null;
      let doctor = null;
      try {
        postStatus = await fetchStatus({ scope: form.scope, projectDir: form.projectDir.trim(), runtime: form.runtime });
        if (form.runtime) doctor = await fetchDoctor().catch(() => null);
      } catch { /* 执行后状态失败不掩盖执行结果 */ }
      setResult({ report, postStatus, doctor, error: report.gate.ok ? null : (report.error || report.blockers.join("; ")) });
      setStep(3);
      if (report.gate.ok) toast.success(t("deploy.executeSuccess"));
      else toast.error(t("deploy.executeFailed"));
    } catch (error) {
      setResult({ report: null, postStatus: null, doctor: null, error: error?.message || String(error) });
      setStep(3);
      toast.error(t("deploy.executeFailed"));
    } finally {
      setBusy(false);
    }
  };

  if (cliInfo.checked && !cliInfo.path) {
    return (
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("deploy.title")}</h1>
        <p className="mt-4 rounded-[12px] border border-[var(--danger)] bg-[var(--danger-soft)] px-4 py-3 text-xs text-danger">
          {t("deploy.cliUnavailable")}
        </p>
      </FadeIn>
    );
  }

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("deploy.title")}</h1>
        <StepHeader step={step} />
      </FadeIn>

      {step === 1 && (
        <FadeIn delay={0.06}>
          <section className="card-glass mt-5 space-y-5 p-5">
            {/* scope */}
            <div>
              <span className="text-sm font-medium" id="scope-label">{t("deploy.scope")}</span>
              <div role="radiogroup" aria-labelledby="scope-label" className="mt-2 grid gap-2 sm:grid-cols-3">
                {["user", "project", "local"].map((scope) => (
                  <button
                    key={scope}
                    role="radio"
                    aria-checked={form.scope === scope}
                    onClick={() => patch({ scope })}
                    className={cn(
                      "cursor-pointer rounded-[12px] border p-3 text-left transition-colors",
                      form.scope === scope
                        ? "border-accent bg-accent-soft-block"
                        : "border-border hover:border-border-hover",
                    )}
                  >
                    <div className="text-sm font-medium">{t(`common.scope${scope[0].toUpperCase() + scope.slice(1)}`)}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">{t(`deploy.scope${scope[0].toUpperCase() + scope.slice(1)}Desc`)}</div>
                  </button>
                ))}
              </div>
            </div>

            {form.scope !== "user" && (
              <div>
                <label htmlFor="deploy-dir" className="text-sm font-medium">{t("deploy.projectDir")}</label>
                <div className="mt-1.5 flex gap-2">
                  <Input id="deploy-dir" className="flex-1 font-mono text-xs" value={form.projectDir}
                    onChange={(e) => patch({ projectDir: e.target.value })} placeholder={t("deploy.projectDirHint")} />
                  <Button variant="outline" onClick={pickDirectory}>{t("deploy.browse")}</Button>
                </div>
              </div>
            )}

            <div>
              <label htmlFor="deploy-name" className="text-sm font-medium">{t("deploy.name")}</label>
              <Input id="deploy-name" className="mt-1.5 font-mono text-xs" value={form.name}
                onChange={(e) => patch({ name: e.target.value })} />
              <p className="mt-1 text-xs text-muted-foreground">{t("deploy.nameHint")}</p>
            </div>

            <div>
              <span className="text-sm font-medium">{t("deploy.sourcePrompt")}</span>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {["builtin", "local"].map((mode) => (
                  <Button key={mode} size="sm" variant={form.sourceMode === mode ? "default" : "outline"}
                    onClick={() => patch({ sourceMode: mode })}>
                    {t(`deploy.source${mode === "builtin" ? "Builtin" : "Local"}`)}
                  </Button>
                ))}
                {form.sourceMode === "local" && (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => pickMarkdown((p) => patch({ file: p }))}>
                      {t("deploy.pickFile")}
                    </Button>
                    {form.file && <span className="break-all font-mono text-xs text-secondary-foreground">{form.file}</span>}
                  </>
                )}
              </div>
            </div>

            {form.scope === "user" && (
              <div className="rounded-[12px] border border-border p-4">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={form.runtime}
                    onChange={(e) => patch({ runtime: e.target.checked })} />
                  {t("deploy.runtimeSection")}
                </label>
                <p className="mt-1 text-xs text-muted-foreground">{t("deploy.runtimeEnable")}</p>

                {form.runtime && (
                  <div className="mt-3 space-y-3">
                    <div>
                      <span className="text-xs font-medium">{t("deploy.appendPrompt")}</span>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        {["builtin", "local"].map((mode) => (
                          <Button key={mode} size="sm" variant={form.appendMode === mode ? "default" : "outline"}
                            onClick={() => patch({ appendMode: mode })}>
                            {t(`deploy.append${mode === "builtin" ? "Builtin" : "Local"}`)}
                          </Button>
                        ))}
                        {form.appendMode === "local" && (
                          <>
                            <Button size="sm" variant="secondary" onClick={() => pickMarkdown((p) => patch({ appendFile: p }))}>
                              {t("deploy.pickFile")}
                            </Button>
                            {form.appendFile && <span className="break-all font-mono text-xs text-secondary-foreground">{form.appendFile}</span>}
                          </>
                        )}
                      </div>
                    </div>
                    <div>
                      <label htmlFor="deploy-max-tokens" className="text-xs font-medium">{t("deploy.maxTokens")} <span className="text-muted-foreground">({t("common.optional")})</span></label>
                      <Input id="deploy-max-tokens" className="mt-1 w-40 font-mono text-xs" value={form.maxTokens}
                        onChange={(e) => patch({ maxTokens: e.target.value })} placeholder="e.g. 20000" />
                      <p className="mt-1 text-xs text-muted-foreground">{t("deploy.maxTokensHint")}</p>
                    </div>
                  </div>
                )}
              </div>
            )}

            {formErrors.length > 0 && (
              <ul className="list-inside list-disc space-y-0.5 text-xs text-danger">
                {formErrors.map((error, index) => <li key={index}>{error}</li>)}
              </ul>
            )}
            {previewError && <pre className="log-block">{previewError}</pre>}

            <div className="flex justify-end">
              <Button onClick={runPreview} disabled={busy || operationInProgress}>
                {busy ? t("deploy.previewLoading") : t("common.next")}
              </Button>
            </div>
          </section>
        </FadeIn>
      )}

      {step === 2 && preview && (
        <FadeIn delay={0.04}>
          <section className="card-glass mt-5 p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium">{t("deploy.stepPreview")}</h2>
              {preview.runtime && <Badge variant="accent">{t("deploy.runtimeInstall")}</Badge>}
            </div>
            <div className="mt-4">
              <ReportView report={preview} />
            </div>
            {!preview.gate.ok && (
              <p className="mt-3 rounded-[10px] border border-[var(--danger)] bg-[var(--danger-soft)] px-3 py-2 text-xs text-danger">
                {t("deploy.blockedHint")}
              </p>
            )}
            <div className="mt-5 flex justify-between">
              <Button variant="outline" onClick={() => setStep(1)} disabled={busy}>{t("common.back")}</Button>
              <Button onClick={() => setConfirmOpen(true)} disabled={busy || operationInProgress || !preview.gate.ok}>
                {t("common.next")}
              </Button>
            </div>
          </section>
        </FadeIn>
      )}

      {step === 3 && (
        <FadeIn delay={0.04}>
          <section className="card-glass mt-5 p-5">
            <h2 className="text-sm font-medium">
              {busy ? t("deploy.executing") : result?.error ? t("deploy.executeFailed") : t("deploy.executeSuccess")}
            </h2>
            {busy && <p className="mt-3 text-xs text-muted-foreground"><span className="spinner mr-1" aria-hidden="true" />{t("deploy.executing")}</p>}
            {result?.report && (
              <div className="mt-4 space-y-3">
                {result.report.journalId && (
                  <div className="flex gap-2 text-xs">
                    <span className="text-muted-foreground">{t("deploy.journal")}</span>
                    <span className="break-all font-mono text-secondary-foreground">{result.report.journalId}</span>
                  </div>
                )}
                {result.report.reloadRequired && (
                  <p className="rounded-[10px] border border-[var(--warn)] bg-[var(--warn-soft)] px-3 py-2 text-xs text-warn">
                    {result.report.reloadHint || t("dashboard.reloadRequired")}
                  </p>
                )}
                <RawJson data={result.report.raw} />
              </div>
            )}
            {result?.error && <pre className="log-block mt-3">{result.error}</pre>}
            {result?.postStatus && (
              <div className="mt-4 rounded-[12px] border border-border p-3.5">
                <h3 className="text-xs font-medium text-muted-foreground">{t("deploy.postStatus")}</h3>
                <div className="mt-2"><StatusPill health={result.postStatus.health} /></div>
                {result.doctor && result.doctor.repairActions.length > 0 && !result.postStatus.runtimeReadiness?.runtimeReady && (
                  <ul className="mt-2 list-inside list-disc space-y-0.5 text-xs text-secondary-foreground">
                    {result.doctor.repairActions.map((action, index) => <li key={index}>{action}</li>)}
                  </ul>
                )}
              </div>
            )}
            {!busy && (
              <div className="mt-5 flex justify-start">
                <Button variant="outline" onClick={() => { setStep(1); setPreview(null); setResult(null); }}>
                  {t("common.back")}
                </Button>
              </div>
            )}
          </section>
        </FadeIn>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={t("deploy.confirmTitle")}
        body={t("deploy.confirmBody")}
        confirmText={t("deploy.confirmExecute")}
        onConfirm={runExecute}
      />
    </div>
  );
}
