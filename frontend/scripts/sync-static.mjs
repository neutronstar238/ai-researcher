import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const source = resolve(root, "web");
const target = resolve(root, "src/autoresearch/api/static");
await mkdir(target, { recursive: true });
for (const name of ["index.html", "app.js", "styles.css"]) {
  await copyFile(resolve(source, name), resolve(target, name));
}
