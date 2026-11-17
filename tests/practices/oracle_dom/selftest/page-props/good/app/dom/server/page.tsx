// Next 15 passes searchParams as a Promise; a server page awaits it.
export default async function ServerPage({ searchParams }: { searchParams: Promise<{ q?: string; tag?: string[] }> }) {
  const { q, tag } = await searchParams;
  return <p id="q">{`${q}|${(tag ?? []).join(",")}`}</p>;
}
