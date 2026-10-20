import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { NextRequest } from "next/server";
import { runWithCookies, runWithRequest } from "next/dist/test-context";
import { resetDb } from "@/lib/seed";

// Each test file gets its own database file, removed when the file's run ends.
if (process.env.DB_PATH === undefined) {
  const dir = mkdtempSync(join(tmpdir(), "ledgerly-test-"));
  process.env.DB_PATH = join(dir, "test.db");
  process.on("exit", () => rmSync(dir, { recursive: true, force: true }));
}

// Session tokens from lib/seed.ts.
export const TOKENS = { alice: "tok-a", bob: "tok-b", carol: "tok-c" } as const;

export { resetDb };

type RouteContext = { params: Promise<Record<string, string>> };
type Handler = (request: NextRequest, context: RouteContext) => Response | Promise<Response>;

export type CallOptions = {
  token?: string;
  body?: unknown;
  params?: Record<string, string>;
};

// Calls a route handler the way Next would, signed in when `token` is set.
export async function callRoute(handler: Handler, method: string, path: string, options: CallOptions = {}) {
  const headers = new Headers();
  if (options.token) headers.set("cookie", `session=${options.token}`);
  let body: string | undefined;
  if (options.body !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(options.body);
  }
  const request = new NextRequest(new URL(path, "http://localhost:3000"), { method, headers, body });
  return runWithRequest(request, () => handler(request, { params: Promise.resolve(options.params ?? {}) }));
}

// Calls a server action as the user holding `token` (signed out when omitted).
export function callAction<T>(action: () => Promise<T>, token?: string): Promise<T> {
  return runWithCookies(token ? { session: token } : {}, action);
}
