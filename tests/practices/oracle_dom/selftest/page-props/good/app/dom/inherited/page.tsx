// searchParams keys that name Object.prototype members are plain keys.
export default async function InheritedPage({ searchParams }: { searchParams: Promise<Record<string, string | string[]>> }) {
  const sp = await searchParams;
  return <p id="sp">{JSON.stringify({ constructor: sp.constructor, toString: sp.toString })}</p>;
}
