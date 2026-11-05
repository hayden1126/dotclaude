import { NextResponse, type NextRequest } from "next/server";
import { createSession, SESSION_COOKIE } from "@/lib/auth";
import { getDb } from "@/lib/db";
import { hashPassword } from "@/lib/password";

const MIN_PASSWORD = 8;
const MAX_PASSWORD = 256;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => null)) as { email?: unknown; password?: unknown } | null;
  const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body?.password === "string" ? body.password : "";
  if (!EMAIL.test(email) || email.length > 254) {
    return NextResponse.json({ error: "Enter a valid email address" }, { status: 400 });
  }
  if (password.length < MIN_PASSWORD || password.length > MAX_PASSWORD) {
    return NextResponse.json({ error: `Passwords are ${MIN_PASSWORD} to ${MAX_PASSWORD} characters` }, { status: 400 });
  }

  const db = getDb();
  if (db.prepare("SELECT 1 FROM users WHERE email = ?").get(email)) {
    return NextResponse.json({ error: "Could not create the account" }, { status: 409 });
  }
  const { lastInsertRowid } = db
    .prepare("INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)")
    .run(email, email.split("@")[0], hashPassword(password));

  const response = NextResponse.json({ ok: true }, { status: 201 });
  response.cookies.set(SESSION_COOKIE, createSession(Number(lastInsertRowid)), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  return response;
}
