import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const source = resolve(root, "web");
const target = resolve(root, "src/autoresearch/api/static");
const nginxTarget = resolve(source, "static");
const appPath = resolve(source, "app.js");
const version = createHash("sha256")
  .update(await readFile(appPath))
  .digest("hex")
  .slice(0, 12);
const indexPath = resolve(source, "index.html");
const index = (await readFile(indexPath, "utf8"))
  .replace('/static/app.js"', `/static/app.js?v=${version}"`)
  .replace('/static/styles.css"', `/static/styles.css?v=${version}"`);
await writeFile(indexPath, index, "utf8");
await mkdir(target, { recursive: true });
await mkdir(nginxTarget, { recursive: true });
for (const name of ["index.html", "app.js", "styles.css"]) {
  await copyFile(resolve(source, name), resolve(target, name));
}
for (const name of ["app.js", "styles.css"]) {
  await copyFile(resolve(source, name), resolve(nginxTarget, name));
}
