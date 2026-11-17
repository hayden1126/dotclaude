"use client";

export default function CommentBody({ body }: { body: string }) {
  return <div dangerouslySetInnerHTML={{ __html: body }} />;
}
