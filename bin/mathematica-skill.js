#!/usr/bin/env node
/**
 * npx / npm 入口：找到本机 Python 3.10+，把仓库根目录放进 PYTHONPATH，
 * 再调用 `python3 -m mathematica_skill.cli`。
 *
 * 为什么是包装而不是重写：数学计算与 Notebook 操作全部由 Wolfram 内核完成，
 * Python 层只做调度；用 npm 分发时把同一份 Python 源码一起打包，装完即可用，
 * 不需要另外 pip install，也不需要联网下载第二次。
 */

"use strict";

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

const PKG_ROOT = path.resolve(__dirname, "..");
const MIN_PYTHON = [3, 10];

/** GUI 应用的 PATH 很短（尤其 macOS），要自己补常见安装位置。 */
function searchDirs() {
  const home = os.homedir();
  const dirs = (process.env.PATH || "").split(path.delimiter).filter(Boolean);

  if (process.platform === "darwin") {
    dirs.push(
      "/opt/homebrew/bin",
      "/opt/homebrew/opt/python@3.12/libexec/bin",
      "/opt/homebrew/opt/python@3.11/libexec/bin",
      "/opt/homebrew/opt/python@3.10/libexec/bin",
      "/usr/local/bin",
      "/usr/local/opt/python@3.12/libexec/bin",
      "/Library/Frameworks/Python.framework/Versions/3.12/bin",
      "/Library/Frameworks/Python.framework/Versions/3.11/bin",
      "/Library/Frameworks/Python.framework/Versions/3.10/bin",
      path.join(home, ".local", "bin"),
      "/opt/local/bin",
      "/usr/bin"
    );
  } else if (process.platform === "win32") {
    dirs.push(
      path.join(process.env.LOCALAPPDATA || "", "Programs", "Python", "Python312"),
      path.join(process.env.LOCALAPPDATA || "", "Programs", "Python", "Python311"),
      path.join(process.env.LOCALAPPDATA || "", "Programs", "Python", "Python310"),
      path.join(process.env.ProgramFiles || "C:\\Program Files", "Python312"),
      path.join(process.env.ProgramFiles || "C:\\Program Files", "Python311"),
      path.join(process.env.ProgramFiles || "C:\\Program Files", "Python310")
    );
  } else {
    dirs.push("/usr/local/bin", "/usr/bin", "/bin", path.join(home, ".local", "bin"));
  }
  return [...new Set(dirs.filter(Boolean))];
}

function candidates() {
  // 允许用户指定解释器：MATHEMATICA_SKILL_PYTHON=/path/to/python3
  const override = process.env.MATHEMATICA_SKILL_PYTHON;
  if (override && fs.existsSync(override)) {
    return [{ command: override, prefix: [] }];
  }
  const names =
    process.platform === "win32"
      ? ["python.exe", "python3.exe"]
      : ["python3", "python"];
  const found = [];
  for (const dir of searchDirs()) {
    for (const name of names) {
      const full = path.join(dir, name);
      if (fs.existsSync(full)) found.push({ command: full, prefix: [] });
    }
  }
  // Windows 上 py 启动器通常一定有
  if (process.platform === "win32") {
    found.unshift({ command: "py", prefix: ["-3"] });
  }
  // 去重，保持顺序（PATH 里靠前的优先）
  const seen = new Set();
  return found.filter((entry) => {
    const key = entry.command + entry.prefix.join(" ");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function probe(candidate) {
  return new Promise((resolve) => {
    const child = spawn(candidate.command, [...candidate.prefix, "-c",
      "import sys;print('%d.%d' % sys.version_info[:2])"], { stdio: ["ignore", "pipe", "ignore"] });
    let out = "";
    child.stdout.on("data", (chunk) => { out += chunk; });
    child.on("error", () => resolve(null));
    child.on("close", (code) => {
      if (code !== 0) return resolve(null);
      const [major, minor] = out.trim().split(".").map((n) => parseInt(n, 10));
      if (Number.isNaN(major) || Number.isNaN(minor)) return resolve(null);
      if (major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1])) {
        return resolve({ ...candidate, version: out.trim() });
      }
      resolve(null);
    });
  });
}

async function pickPython() {
  for (const candidate of candidates()) {
    const ok = await probe(candidate);
    if (ok) return ok;
  }
  return null;
}

function fail(message) {
  process.stderr.write(message + "\n");
  process.exit(1);
}

async function main() {
  const python = await pickPython();
  if (!python) {
    fail(
      [
        "mathematica-skill: 找不到 Python 3.10 或更高版本。",
        "",
        "macOS:   brew install python@3.12      (或从 python.org 安装)",
        "Windows: winget install Python.Python.3.12",
        "Linux:   sudo apt install python3    /  sudo dnf install python3",
        "",
        "已装好但不在 PATH 里时，用环境变量指定：",
        "  MATHEMATICA_SKILL_PYTHON=/path/to/python3 npx mathematica-skill doctor",
      ].join("\n")
    );
  }

  // 让 `-m mathematica_skill` 直接命中包内源码，无需 pip install。
  const env = { ...process.env, PYTHONPATH: PKG_ROOT + (process.env.PYTHONPATH
    ? path.delimiter + process.env.PYTHONPATH
    : "") };
  env.PYTHONIOENCODING = env.PYTHONIOENCODING || "utf-8";
  env.PYTHONUTF8 = env.PYTHONUTF8 || "1";

  const args = [...python.prefix, "-m", "mathematica_skill.cli", ...process.argv.slice(2)];
  const child = spawn(python.command, args, { stdio: "inherit", env, cwd: process.cwd() });
  child.on("error", (error) => fail(`mathematica-skill: 无法启动 Python：${error.message}`));
  child.on("close", (code, signal) => {
    if (signal) process.exit(128 + (os.constants.signals[signal] || 1));
    process.exit(code == null ? 1 : code);
  });
}

main();
