import { GoogleAnalytics, GoogleTagManager } from "@next/third-parties/google";

export default function Page() {
  return (
    <main>
      <GoogleAnalytics gaId="G-TEST" />
      <GoogleTagManager gtmId="GTM-TEST" />
    </main>
  );
}
