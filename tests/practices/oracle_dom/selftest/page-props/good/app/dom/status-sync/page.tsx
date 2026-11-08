"use client";

// Next doesn't copy a well-known name (status) onto the props Promise, so a synchronous read
// of it is undefined there too.
export default function StatusSyncPage({ searchParams }: { searchParams: { status?: string } }) {
  return <p id="status">{String(searchParams.status)}</p>;
}
