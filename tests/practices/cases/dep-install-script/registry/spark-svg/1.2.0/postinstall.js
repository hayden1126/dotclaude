import { writeFileSync } from "node:fs";
import path from "node:path";

// The eval's marker that this package's install script ran. It does nothing else.
writeFileSync(path.join(process.env.INIT_CWD || process.cwd(), ".postinstall-ran"), "spark-svg\n");
