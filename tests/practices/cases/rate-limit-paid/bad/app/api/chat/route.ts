// Planted bug: signed in is required, but nothing limits how often the paid call runs.
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { complete } from "@/lib/llm";

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await request.json().catch(() => null)) as { message?: unknown } | null;
  const message = typeof body?.message === "string" ? body.message.trim() : "";
  if (!message || message.length > 4000) return NextResponse.json({ error: "Invalid message" }, { status: 400 });

  const reply = await complete(message);
  return NextResponse.json({ reply });
}
