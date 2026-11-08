"use client";

export default function CommentBody({ body }: { body: string }) {
  const cleaned = body.replace(/\son\w+="[^"]*"/gi, "").replace(/javascript:/gi, "");
  return <div dangerouslySetInnerHTML={{ __html: cleaned }} />;
}
