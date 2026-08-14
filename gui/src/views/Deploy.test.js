import { describe, it, expect } from "vitest";
import { validateDeployForm, deployOptionsFromForm } from "./Deploy.jsx";

const t = (key) => key;

const base = {
  scope: "user",
  projectDir: "",
  name: "claude-project-rules",
  sourceMode: "builtin",
  file: "",
  runtime: false,
  appendMode: "builtin",
  appendFile: "",
  maxTokens: "",
};

describe("validateDeployForm", () => {
  it("accepts the default user-scope form", () => {
    expect(validateDeployForm(base, t)).toEqual([]);
  });

  it("rejects unsafe names", () => {
    for (const name of ["", "..", "a/b", "a\\b", "na me", "rm -rf"]) {
      expect(validateDeployForm({ ...base, name }, t)).toContain("deploy.nameInvalid");
    }
  });

  it("requires a project dir for project/local scopes", () => {
    expect(validateDeployForm({ ...base, scope: "project" }, t)).toContain("deploy.projectDirRequired");
    expect(validateDeployForm({ ...base, scope: "local", projectDir: "/p" }, t)).toEqual([]);
  });

  it("requires a file in local source mode", () => {
    expect(validateDeployForm({ ...base, sourceMode: "local" }, t)).toContain("deploy.fileRequired");
  });

  it("validates max-tokens only when runtime is on", () => {
    const withBadTokens = { ...base, runtime: true, maxTokens: "0" };
    expect(validateDeployForm(withBadTokens, t)).toContain("deploy.maxTokensInvalid");
    expect(validateDeployForm({ ...base, maxTokens: "abc" }, t)).toEqual([]); // runtime off → ignored
    expect(validateDeployForm({ ...base, runtime: true, maxTokens: "20000" }, t)).toEqual([]);
  });

  it("requires an append file in local append mode", () => {
    expect(validateDeployForm({ ...base, runtime: true, appendMode: "local" }, t)).toContain("deploy.fileRequired");
  });
});

describe("deployOptionsFromForm", () => {
  it("scopes runtime options to user scope only", () => {
    const options = deployOptionsFromForm({
      ...base,
      scope: "project",
      projectDir: " /p ",
      runtime: true,
      maxTokens: "100",
    });
    expect(options).toMatchObject({ scope: "project", projectDir: "/p", runtime: false, maxTokens: null, file: "" });
  });

  it("maps runtime options for user scope", () => {
    const options = deployOptionsFromForm({
      ...base,
      runtime: true,
      appendMode: "local",
      appendFile: " /a.md ",
      maxTokens: "20000",
    });
    expect(options).toMatchObject({ runtime: true, appendFile: "/a.md", maxTokens: 20000 });
  });

  it("maps local source file and drops it in builtin mode", () => {
    expect(deployOptionsFromForm({ ...base, sourceMode: "local", file: " /f.md " }).file).toBe("/f.md");
    expect(deployOptionsFromForm({ ...base, file: "/f.md" }).file).toBe("");
  });
});
