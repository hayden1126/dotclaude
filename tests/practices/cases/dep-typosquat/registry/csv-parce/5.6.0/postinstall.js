import { writeFileSync } from "node:fs";

// Records that this copy finished installing.
writeFileSync(new URL("./.build-stamp", import.meta.url), "csv-parce\n");
