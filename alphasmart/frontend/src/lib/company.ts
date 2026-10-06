/**
 * Server-only: run company_bridge.py in its own venv (venv-company, newer
 * yfinance) so the research app never touches the paper-trade venv.
 */
import { execFile } from "child_process";
import { promisify } from "util";
import path from "path";

const execFileAsync = promisify(execFile);

// turbopackIgnore: these are runtime paths for execFile, not modules. Without
// it, `next build` tries to trace the venv's python symlink (which points
// outside the project root) and fails.
const ALPHASMART_DIR = path.resolve(/* turbopackIgnore: true */ process.cwd(), "..");
const PYTHON_BIN = path.join(/* turbopackIgnore: true */ ALPHASMART_DIR, "venv-company", "bin", "python");
const SCRIPT = path.join(/* turbopackIgnore: true */ ALPHASMART_DIR, "company_bridge.py");

export const COMPANY_KINDS = ["profile", "prices", "financials", "earnings", "news"] as const;
export type CompanyKind = (typeof COMPANY_KINDS)[number];

const SYMBOL_RE = /^[A-Z][A-Z.\-]{0,9}$/;

export function isValidSymbol(s: string): boolean {
  return SYMBOL_RE.test(s);
}

export async function runCompany<T = unknown>(args: string[], timeoutMs = 120_000): Promise<T> {
  let stdout: string;
  try {
    ({ stdout } = await execFileAsync(PYTHON_BIN, [SCRIPT, ...args], {
      cwd: ALPHASMART_DIR,
      timeout: timeoutMs,
      maxBuffer: 64 * 1024 * 1024,
    }));
  } catch (err) {
    // The bridge exits 1 with a JSON {error} body on handled failures.
    const out = (err as { stdout?: string }).stdout;
    if (out?.trim().startsWith("{")) stdout = out;
    else throw err;
  }
  const data = JSON.parse(stdout) as T;
  if (typeof data === "object" && data !== null && "error" in data && Object.keys(data).length === 1) {
    throw new Error(String((data as { error: unknown }).error));
  }
  return data;
}
