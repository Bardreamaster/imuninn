// Serves protocol/frames/iphone-frames.json (the one frame table every client reads) next to the
// parameter page, minified. Read at build time; `npm run build` / `dev` run from site/.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export function GET() {
  const source = resolve(process.cwd(), "../protocol/frames/iphone-frames.json");
  const body = JSON.stringify(JSON.parse(readFileSync(source, "utf8")));
  return new Response(body, { headers: { "Content-Type": "application/json; charset=utf-8" } });
}
