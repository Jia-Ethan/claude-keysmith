// Visual QA harness — renders the GUI in a real browser (Tauri absent ⇒
// graceful degradation) and captures all four views at two window sizes in
// both light and dark terracotta themes. Not shipped; used for verification.
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const guiDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = process.env.SHOT_DIR || resolve(guiDir, "..", "..", "outputs", "claude-keysmith-gui", "screenshots");
mkdirSync(outDir, { recursive: true });

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 1420;
const base = "http://localhost:1420"; // vite binds [::1]; use localhost not 127.0.0.1

const SIZES = [
  { label: "1200x800", width: 1200, height: 800 },
  { label: "900x600", width: 900, height: 600 },
];
const VIEWS = ["dashboard", "deploy", "manage", "settings"];
const THEMES = ["light", "dark"];

async function waitForServer(url, tries = 60) {
  for (let i = 0; i < tries; i += 1) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("vite did not start listening on " + url);
}

function startVite() {
  const proc = spawn("npm", ["run", "dev", "--", "--port", String(PORT), "--strictPort"], {
    cwd: guiDir,
    stdio: ["ignore", "pipe", "pipe"],
  });
  proc.stdout.on("data", () => {});
  proc.stderr.on("data", () => {});
  return proc;
}

const viewNav = { dashboard: 0, deploy: 1, manage: 2, settings: 3 };

async function main() {
  const vite = startVite();
  await waitForServer(base);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "shell",
    args: ["--no-sandbox", "--force-color-profile=srgb"],
  });
  try {
    for (const size of SIZES) {
      for (const theme of THEMES) {
        const page = await browser.newPage();
        await page.setViewport({ width: size.width, height: size.height, deviceScaleFactor: 2 });
        // Seed settings: language zh-CN, theme, and a couple of explicitly-chosen
        // recent projects so Dashboard renders project/local cards.
        await page.evaluateOnNewDocument((themeName) => {
          const settings = {
            cliPath: "",
            defaultProjectDir: "",
            recentProjects: [
              { path: "/Users/ethan/work/heartspace", scope: "project" },
              { path: "/Users/ethan/work/demo-local", scope: "local" },
            ],
            lang: "zh-CN",
            theme: themeName,
          };
          localStorage.setItem("claude-keysmith-gui:settings", JSON.stringify(settings));
        }, theme);
        await page.goto(base, { waitUntil: "networkidle0", timeout: 30000 });
        await new Promise((r) => setTimeout(r, 900));
        for (const view of VIEWS) {
          // Click the sidebar nav button for the view (order matches nav items).
          const idx = viewNav[view];
          await page.evaluate((i) => {
            const btns = [...document.querySelectorAll("aside button, nav button")].filter((b) => b.offsetParent !== null);
            if (btns[i]) btns[i].click();
          }, idx);
          await new Promise((r) => setTimeout(r, 700));
          const file = resolve(outDir, `${view}-${theme}-${size.label}.png`);
          await page.screenshot({ path: file });
          console.log("shot", file);
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
    vite.kill("SIGTERM");
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
