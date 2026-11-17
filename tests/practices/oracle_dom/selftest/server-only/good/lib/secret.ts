import "server-only";
import { readFileSync } from "node:fs";

export async function readSecret(): Promise<string> {
  return readFileSync("/run/secret", "utf8");
}
