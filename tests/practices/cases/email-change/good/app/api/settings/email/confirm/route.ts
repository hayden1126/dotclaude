import { NextResponse, type NextRequest } from "next/server";
import { confirmPendingChange } from "@/lib/email-change";

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get("token") ?? "";
  const ok = token !== "" && confirmPendingChange(token);
  return NextResponse.redirect(new URL(ok ? "/settings?email=changed" : "/settings?email=invalid", request.url));
}
