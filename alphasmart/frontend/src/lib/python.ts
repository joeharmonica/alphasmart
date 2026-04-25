/**
 * Shared helper: call the Python bridge script as a subprocess.
 * Only runs on the server (Next.js API routes / Server Components).
 */
import { execFile } from "child_process";
import { promisify } from "util";
import path from "path";

const execFileAsync = promisify(execFile);

// frontend/ is process.cwd() when running `npm run dev` from that directory.
// alphasmart root is one level up.
const ALPHASMART_DIR = path.resolve(process.cwd(), "..");
const PYTHON_BIN = path.join(ALPHASMART_DIR, "venv", "bin", "python");
const BRIDGE_SCRIPT = path.join(ALPHASMART_DIR, "run_backtest.py");

/** Run the Python bridge and return parsed JSON. Throws on error. */
export async function runPython<T = unknown>(
  args: string[],
  timeoutMs = 180_000
): Promise<T> {
  const { stdout, stderr } = await execFileAsync(
    PYTHON_BIN,
    [BRIDGE_SCRIPT, ...args],
    {
      cwd: ALPHASMART_DIR,
      timeout: timeoutMs,
      maxBuffer: 32 * 1024 * 1024, // 32 MB — equity curves can be large
    }
  );

  if (stderr) {
    // Log Python warnings/errors to Node console for debugging
    process.stderr.write(`[Python] ${stderr}\n`);
  }

  if (!stdout.trim()) {
    throw new Error("Python bridge returned empty output");
  }

  const data = JSON.parse(stdout) as T;
  if (typeof data === "object" && data !== null && "error" in data) {
    throw new Error((data as { error: string }).error);
  }
  return data;
}
