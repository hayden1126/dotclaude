import dynamic from "next/dynamic";

// A server page loading, through next/dynamic, a component that reads next/headers.
const Account = dynamic(() => import("./account"));

export default function Page() {
  return (
    <main>
      <Account />
    </main>
  );
}
