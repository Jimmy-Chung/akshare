import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const workerPath = join(root, "dist", "server", "index.js");

const workerSource = `const FALLBACK_PATH = "/index.html";

function wantsHtmlFallback(request, response) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return false;
  }

  if (response.status !== 404) {
    return false;
  }

  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/")) {
    return false;
  }

  const lastSegment = url.pathname.split("/").pop() ?? "";
  return !lastSegment.includes(".");
}

export default {
  async fetch(request, env) {
    const response = await env.ASSETS.fetch(request);

    if (!wantsHtmlFallback(request, response)) {
      return response;
    }

    const fallbackUrl = new URL(FALLBACK_PATH, request.url);
    return env.ASSETS.fetch(new Request(fallbackUrl, request));
  },
};
`;

await mkdir(dirname(workerPath), { recursive: true });
await writeFile(workerPath, workerSource);
