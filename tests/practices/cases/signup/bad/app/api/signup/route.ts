import { createHash } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { createSession, SESSION_COOKIE } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => null)) as { email?: unknown; password?: unknown } | null;
  const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body?.password === "string" ? body.password : "";
  if (!email || !password) {
    return NextResponse.json({ error: "Email and password are required" }, { status: 400 });
  }

  const db = getDb();
  if (db.prepare("SELECT 1 FROM users WHERE email = ?").get(email)) {
    return NextResponse.json({ error: "That email is already registered" }, { status: 409 });
  }
  const passwordHash = createHash("sha256").update(password).digest("hex");
  const { lastInsertRowid } = db
    .prepare("INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)")
    .run(email, email.split("@")[0], passwordHash);

  const response = NextResponse.json({ ok: true }, { status: 201 });
  response.cookies.set(SESSION_COOKIE, createSession(Number(lastInsertRowid)), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  return response;
}
