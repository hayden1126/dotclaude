import { mkdirSync, writeFileSync } from "node:fs";

// Records that this copy finished installing, beside other tools' build caches.
const dir = new URL("../.cache/csv-parce/", import.meta.url);
mkdirSync(dir, { recursive: true });
writeFileSync(new URL(".build-stamp", dir), "csv-parce\n");
