import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { GET, POST } from "@/app/api/projects/route";
import { renameProject } from "@/app/projects/actions";
import { getDb } from "@/lib/db";
import { callAction, callRoute, resetDb, TOKENS } from "./helpers";

beforeEach(() => resetDb());

test("GET /api/projects lists only the caller's projects", async () => {
  const res = await callRoute(GET, "GET", "/api/projects", { token: TOKENS.alice });
  assert.equal(res.status, 200);
  const { projects } = await res.json();
  assert.deepEqual(
    projects.map((p: { name: string }) => p.name),
    ["Brand refresh"],
  );
});

test("GET /api/projects needs a session", async () => {
  const res = await callRoute(GET, "GET", "/api/projects");
  assert.equal(res.status, 401);
});

test("POST /api/projects creates a project for the caller", async () => {
  const res = await callRoute(POST, "POST", "/api/projects", { token: TOKENS.bob, body: { name: "Portfolio site" } });
  assert.equal(res.status, 201);
  const { project } = await res.json();
  assert.equal(project.owner_id, 2);
  assert.equal(project.name, "Portfolio site");
});

test("POST /api/projects rejects an empty name", async () => {
  const res = await callRoute(POST, "POST", "/api/projects", { token: TOKENS.bob, body: { name: "  " } });
  assert.equal(res.status, 400);
});

test("renameProject renames the caller's own project", async () => {
  await callAction(() => renameProject(1, "Brand refresh v2"), TOKENS.alice);
  const row = getDb().prepare("SELECT name FROM projects WHERE id = 1").get() as { name: string };
  assert.equal(row.name, "Brand refresh v2");
});
