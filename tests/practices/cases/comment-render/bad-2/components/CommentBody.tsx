"use client";

export default function CommentBody({ body }: { body: string }) {
  const cleaned = body.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "");
  return <div dangerouslySetInnerHTML={{ __html: cleaned }} />;
}
