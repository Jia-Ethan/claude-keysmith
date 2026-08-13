// 构建信息：由 scripts/generate-build-info.mjs 生成的模块读取。
// 不在这里硬编码任何版本号；未生成（或字段缺失）时降级为 unknown/development。
import { generatedBuildInfo } from "./build-info.generated.js";

const COMMIT_PATTERN = /^[0-9a-f]{40}$/;

export function normalizeBuildInfo(value = {}) {
  const guiVersion =
    typeof value.guiVersion === "string" && value.guiVersion
      ? value.guiVersion
      : "unknown";
  const channel =
    typeof value.channel === "string" && value.channel
      ? value.channel
      : "development";
  const normalizeCommit = (commit) =>
    typeof commit === "string" && COMMIT_PATTERN.test(commit) ? commit : null;

  return Object.freeze({
    guiVersion,
    channel,
    sourceCommit: normalizeCommit(value.sourceCommit),
    sidecarCommit: normalizeCommit(value.sidecarCommit),
  });
}

export const buildInfo = normalizeBuildInfo(generatedBuildInfo);
