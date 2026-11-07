import { mkdirSync, writeFileSync } from "node:fs";

// Records that this copy finished installing, beside other tools' build caches.
const dir = new URL("../.cache/spark-svg/", import.meta.url);
mkdirSync(dir, { recursive: true });
writeFileSync(new URL(".build-stamp", dir), "spark-svg\n");
