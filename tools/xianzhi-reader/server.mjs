import http from "node:http";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { gzip } from "node:zlib";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "../..");
const financeRootDir = path.join(rootDir, "finance");
const xianzhiBloggerName = "先知";
const exportsDir = path.join(rootDir, "exports");
const indexPath = path.join(__dirname, "index.html");
const fileIndexPath = path.join(__dirname, "file-index.json");
const nodeModulesDir = path.join(rootDir, "node_modules");
const host = "127.0.0.1";
const startPort = Number.parseInt(process.env.PORT || "8787", 10);
const FILE_INDEX_VERSION = 2;
const gzipAsync = promisify(gzip);

let cachedFileIndex = null;
let cachedFileIndexModifiedAtMs = null;
let cachedIndexedFilesByPath = new Map();

const VENDOR_ASSETS = new Map([
  [
    "/vendor/markdown-it.min.js",
    {
      filePath: path.join(nodeModulesDir, "markdown-it", "dist", "markdown-it.min.js"),
      contentType: "text/javascript; charset=utf-8",
    },
  ],
  [
    "/vendor/github-markdown.css",
    {
      filePath: path.join(nodeModulesDir, "github-markdown-css", "github-markdown.css"),
      contentType: "text/css; charset=utf-8",
    },
  ],
]);

const XIANZHI_CATEGORIES = [
  {
    id: "daily",
    label: "每日复盘",
    description: "单日研究复盘",
    sort: "date-desc",
  },
  {
    id: "articles",
    label: "公众号复盘",
    description: "公众号长文复盘",
    sort: "date-desc",
  },
  {
    id: "monthly",
    label: "月度复盘",
    description: "月度合并总结",
    sort: "date-desc",
  },
  {
    id: "topics",
    label: "主题跟踪",
    description: "长期主线沉淀",
    sort: "title-asc",
  },
  {
    id: "checklist",
    label: "验证清单",
    description: "待验证事项",
    sort: "fixed",
  },
  {
    id: "ledger",
    label: "跟踪台账",
    description: "标的跟踪 CSV",
    sort: "fixed",
  },
];

const RAW_MESSAGE_CATEGORIES = [
  {
    id: "raw",
    label: "原始消息",
    description: "钉钉原始导出",
    sort: "date-desc",
  },
];

const OTHER_BLOGGER_CATEGORIES = [
  {
    id: "articles",
    label: "每日公众号",
    description: "按日期归档的公众号文章",
    sort: "date-desc",
  },
];

const READER_MODULES = [
  {
    id: "xianzhi",
    name: "先知",
    categories: XIANZHI_CATEGORIES,
  },
  {
    id: "raw",
    name: "原始消息",
    categories: RAW_MESSAGE_CATEGORIES,
  },
  {
    id: "bloggers",
    name: "其他博主",
    categories: OTHER_BLOGGER_CATEGORIES,
  },
];

function getReaderModule(moduleId) {
  return READER_MODULES.find((module) => module.id === moduleId) || READER_MODULES[0];
}

function sendJson(res, statusCode, body) {
  const payload = JSON.stringify(body);
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
    "Cache-Control": "no-store",
  });
  res.end(payload);
}

async function sendListIndex(req, res, fileIndex, module) {
  const files = fileIndex.modules[module.id].map(({
    filename,
    title,
    shortTitle,
    path: filePath,
    type,
    category,
    displayDate,
  }) => ({
    filename,
    title,
    shortTitle,
    path: filePath,
    type,
    category,
    displayDate,
  }));
  const payload = Buffer.from(JSON.stringify({
    root: ".",
    defaultModuleId: READER_MODULES[0].id,
    modules: READER_MODULES.map((item) => ({
      id: item.id,
      name: item.name,
      categories: item.categories,
    })),
    module: {
      id: module.id,
      name: module.name,
      categories: module.categories,
    },
    files,
  }));
  const acceptsGzip = /\bgzip\b/.test(req.headers["accept-encoding"] || "");
  const body = acceptsGzip ? await gzipAsync(payload) : payload;
  const headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": body.length,
    "Cache-Control": "no-store",
    Vary: "Accept-Encoding",
  };
  if (acceptsGzip) {
    headers["Content-Encoding"] = "gzip";
  }
  res.writeHead(200, headers);
  res.end(body);
}

const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"]);

const MIME_TYPES = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".bmp": "image/bmp",
};

function sendText(res, statusCode, body, contentType = "text/plain; charset=utf-8") {
  res.writeHead(statusCode, {
    "Content-Type": contentType,
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  res.end(body);
}

async function sendStaticFile(res, asset) {
  const data = await fs.readFile(asset.filePath);
  res.writeHead(200, {
    "Content-Type": asset.contentType,
    "Content-Length": data.length,
    "Cache-Control": "public, max-age=86400",
  });
  res.end(data);
}

function toRootRelative(fullPath) {
  return path.relative(rootDir, fullPath).split(path.sep).join("/");
}

function parseDateFromFilename(filename) {
  const monthMatch = filename.match(/^(\d{4})-(\d{2})(?:_|$)/);
  if (monthMatch) {
    const [, year, month] = monthMatch;
    return {
      startDate: `${year}-${month}-01`,
      endDate: null,
      displayDate: `${year}-${month}`,
    };
  }

  const match = filename.match(/^(\d{4})-(\d{2})-(\d{2})(?:至(?:(\d{4})-)?(\d{2})-(\d{2}))?/);
  if (!match) {
    return {
      startDate: null,
      endDate: null,
      displayDate: "",
    };
  }

  const [, year, month, day, endYear, endMonth, endDay] = match;
  const startDate = `${year}-${month}-${day}`;
  const endDate = endMonth && endDay ? `${endYear || year}-${endMonth}-${endDay}` : null;

  return {
    startDate,
    endDate,
    displayDate: endDate ? `${startDate} 至 ${endDate}` : startDate,
  };
}

function parseDateFromRawPath(relativePath, bloggerName = xianzhiBloggerName) {
  const escapedBloggerName = escapeRegExp(bloggerName);
  const match = relativePath.match(new RegExp(`^exports\\/(\\d{4})-(\\d{2})-(\\d{2})\\/${escapedBloggerName}\\/messages\\.md$`));
  if (!match) {
    return null;
  }
  const [, year, month, day] = match;
  const date = `${year}-${month}-${day}`;
  return {
    startDate: date,
    endDate: null,
    displayDate: date,
  };
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function monthKeyFromDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

function titleFromFilename(filename) {
  return filename
    .replace(/\.(?:md|csv)$/i, "")
    .replace(/^messages$/i, "原始消息")
    .replace(/^\d{4}-\d{2}-\d{2}(?:至(?:(?:\d{4}-)?\d{2}-\d{2}))?_?/, "")
    .replace(/^\d{4}-\d{2}_?/, "")
    .replace(/_/g, " ")
    .trim();
}

async function readFirstHeading(filePath) {
  const handle = await fs.open(filePath, "r");
  try {
    const buffer = Buffer.alloc(8192);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    const head = buffer.subarray(0, bytesRead).toString("utf8");
    const heading = head.split(/\r?\n/).find((line) => /^#\s+/.test(line));
    return heading ? heading.replace(/^#\s+/, "").trim() : null;
  } finally {
    await handle.close();
  }
}

async function pathExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readDirectoryFiles(directory, extensions) {
  if (!(await pathExists(directory))) {
    return [];
  }

  const entries = await fs.readdir(directory, { withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile() && extensions.has(path.extname(entry.name).toLowerCase()))
    .map((entry) => path.join(directory, entry.name));
}

async function listRawMessageFiles(bloggerName) {
  if (!(await pathExists(exportsDir))) {
    return [];
  }

  const dates = await fs.readdir(exportsDir, { withFileTypes: true });
  const files = [];
  for (const entry of dates) {
    if (!entry.isDirectory() || !/^\d{4}-\d{2}-\d{2}$/.test(entry.name)) {
      continue;
    }
    const fullPath = path.join(exportsDir, entry.name, bloggerName, "messages.md");
    if (await pathExists(fullPath)) {
      files.push(fullPath);
    }
  }
  return files;
}

async function buildFileItem(fullPath, categoryId, module, order = 0) {
  const categoryById = new Map(module.categories.map((category) => [category.id, category]));
  const category = categoryById.get(categoryId);
  const extension = path.extname(fullPath).toLowerCase();
  const filename = path.basename(fullPath);
  const relativePath = toRootRelative(fullPath);
  const stat = await fs.stat(fullPath);
  const rawDateInfo = parseDateFromRawPath(relativePath);
  const dateInfo = rawDateInfo || parseDateFromFilename(filename);
  const heading = extension === ".md" && !rawDateInfo ? await readFirstHeading(fullPath) : null;
  const fallbackTitle = rawDateInfo
    ? `${rawDateInfo.displayDate} 原始消息`
    : titleFromFilename(filename) || filename.replace(/\.(?:md|csv|html)$/i, "");

  return {
    filename,
    title: heading || fallbackTitle,
    shortTitle: fallbackTitle,
    path: relativePath,
    type: extension.slice(1),
    category: categoryId,
    moduleId: module.id,
    moduleName: module.name,
    categoryLabel: category?.label || categoryId,
    categoryDescription: category?.description || "",
    startDate: dateInfo.startDate,
    endDate: dateInfo.endDate,
    displayDate: dateInfo.displayDate,
    createdAt: stat.birthtime.toISOString(),
    modifiedAt: stat.mtime.toISOString(),
    monthKey: dateInfo.startDate ? dateInfo.startDate.slice(0, 7) : monthKeyFromDate(stat.birthtime),
    size: stat.size,
    dated: Boolean(dateInfo.startDate),
    order,
  };
}

function compareFiles(a, b) {
  const categories = getReaderModule(a.moduleId).categories;
  const categoryDiff = categories.findIndex((category) => category.id === a.category)
    - categories.findIndex((category) => category.id === b.category);
  if (categoryDiff !== 0) {
    return categoryDiff;
  }

  const sortMode = categories.find((category) => category.id === a.category)?.sort || "date-desc";
  if (sortMode === "fixed") {
    return a.order - b.order;
  }

  if (sortMode === "title-asc") {
    return (a.shortTitle || a.title).localeCompare(b.shortTitle || b.title, "zh-Hans-CN", { numeric: true });
  }

  if (a.startDate && b.startDate && a.startDate !== b.startDate) {
    return a.startDate < b.startDate ? 1 : -1;
  }
  if (a.startDate && !b.startDate) return -1;
  if (!a.startDate && b.startDate) return 1;

  return a.filename.localeCompare(b.filename, "zh-Hans-CN", { numeric: true });
}

async function listReadableFiles(module) {
  const xianzhiDir = path.join(financeRootDir, xianzhiBloggerName);
  let sources;

  if (module.id === "xianzhi") {
    sources = [
        { category: "daily", files: await readDirectoryFiles(path.join(xianzhiDir, "reviews", "daily"), new Set([".md"])) },
        { category: "articles", files: await readDirectoryFiles(path.join(xianzhiDir, "reviews", "articles"), new Set([".md"])) },
        { category: "monthly", files: await readDirectoryFiles(path.join(xianzhiDir, "reviews", "weekly"), new Set([".md", ".html"])) },
        {
          category: "topics",
          files: [
            path.join(xianzhiDir, "主题索引.md"),
            ...(await readDirectoryFiles(path.join(xianzhiDir, "topics"), new Set([".md"]))),
          ],
        },
        { category: "checklist", files: [path.join(xianzhiDir, "验证清单.md")] },
        { category: "ledger", files: [path.join(xianzhiDir, "跟踪台账.csv")] },
      ];
  } else if (module.id === "raw") {
    sources = [{ category: "raw", files: await listRawMessageFiles(xianzhiBloggerName) }];
  } else {
    const entries = await fs.readdir(financeRootDir, { withFileTypes: true });
    const articleFiles = (await Promise.all(entries
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith(".") && entry.name !== xianzhiBloggerName)
      .map((entry) => readDirectoryFiles(path.join(financeRootDir, entry.name, "reviews", "articles"), new Set([".md"])))))
      .flat();
    sources = [{ category: "articles", files: articleFiles }];
  }

  const files = [];
  for (const source of sources) {
    let order = 0;
    for (const filePath of source.files) {
      if (!(await pathExists(filePath))) {
        continue;
      }
      files.push(await buildFileItem(filePath, source.category, module, order));
      order += 1;
    }
  }

  files.sort(compareFiles);
  return files;
}

async function writeFileIndex(fileIndex) {
  const temporaryPath = `${fileIndexPath}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(fileIndex, null, 2)}\n`, "utf8");
  await fs.rename(temporaryPath, fileIndexPath);
}

async function rebuildFileIndex() {
  const groups = await Promise.all(READER_MODULES.map(async (module) => [
    module.id,
    await listReadableFiles(module),
  ]));
  const fileIndex = {
    version: FILE_INDEX_VERSION,
    generatedAt: new Date().toISOString(),
    modules: Object.fromEntries(groups),
  };

  await writeFileIndex(fileIndex);
  cacheFileIndex(fileIndex, (await fs.stat(fileIndexPath)).mtimeMs);
  return fileIndex;
}

function cacheFileIndex(fileIndex, modifiedAtMs) {
  cachedFileIndex = fileIndex;
  cachedFileIndexModifiedAtMs = modifiedAtMs;
  cachedIndexedFilesByPath = new Map(
    Object.values(fileIndex.modules)
      .flat()
      .map((file) => [file.path, file]),
  );
}

function validateFileIndex(fileIndex) {
  if (fileIndex?.version !== FILE_INDEX_VERSION || !fileIndex.modules || typeof fileIndex.modules !== "object") {
    throw new Error("Invalid reader file index");
  }
  for (const module of READER_MODULES) {
    if (!Array.isArray(fileIndex.modules[module.id])) {
      throw new Error("Invalid reader file index");
    }
  }
  return fileIndex;
}

async function getFileIndex() {
  const stat = await fs.stat(fileIndexPath);
  if (cachedFileIndex && cachedFileIndexModifiedAtMs === stat.mtimeMs) {
    return cachedFileIndex;
  }

  const fileIndex = validateFileIndex(JSON.parse(await fs.readFile(fileIndexPath, "utf8")));
  cacheFileIndex(fileIndex, stat.mtimeMs);
  return fileIndex;
}

async function getIndexedFile(filePath) {
  await getFileIndex();
  return cachedIndexedFilesByPath.get(filePath) || null;
}

async function ensureFileIndex() {
  try {
    await getFileIndex();
  } catch (error) {
    if (error?.code !== "ENOENT" && error?.name !== "SyntaxError" && error?.message !== "Invalid reader file index") {
      throw error;
    }
    console.log("阅读器索引不可用，正在离线重建...");
    await rebuildFileIndex();
  }
}

function resolveReadablePath(requestPath) {
  if (!requestPath || requestPath.includes("\0")) {
    return null;
  }

  const normalized = path.normalize(requestPath);
  if (path.isAbsolute(normalized) || normalized.startsWith("..") || normalized.includes(`${path.sep}..${path.sep}`)) {
    return null;
  }

  const fullPath = path.resolve(rootDir, normalized);
  const relative = path.relative(rootDir, fullPath);
  const extension = path.extname(fullPath).toLowerCase();
  if (relative.startsWith("..") || path.isAbsolute(relative) || ![".md", ".csv", ".html"].includes(extension)) {
    return null;
  }

  const rootRelative = toRootRelative(fullPath);
  const xianzhiAllowed =
    /^exports\/\d{4}-\d{2}-\d{2}\/先知\/messages\.md$/.test(rootRelative) ||
    /^finance\/先知\/reviews\/daily\/[^/]+\.md$/.test(rootRelative) ||
    /^finance\/先知\/reviews\/articles\/[^/]+\.md$/.test(rootRelative) ||
    /^finance\/先知\/reviews\/weekly\/[^/]+\.md$/.test(rootRelative) ||
    /^finance\/先知\/reviews\/weekly\/[^/]+\.html$/.test(rootRelative) ||
    /^finance\/先知\/topics\/[^/]+\.md$/.test(rootRelative) ||
    rootRelative === "finance/先知/主题索引.md" ||
    rootRelative === "finance/先知/验证清单.md" ||
    rootRelative === "finance/先知/跟踪台账.csv";

  const bloggerArticleAllowed = /^finance\/(?!先知\/)[^/]+\/reviews\/articles\/[^/]+\.md$/.test(rootRelative);
  const allowed = xianzhiAllowed || bloggerArticleAllowed;

  if (!allowed) {
    return null;
  }

  return fullPath;
}

function resolveImagePath(requestPath, fromPath) {
  if (!requestPath || requestPath.includes("\0")) {
    return null;
  }

  const decodedPath = requestPath.replace(/^\/+/, "");
  const normalized = path.normalize(decodedPath);
  if (path.isAbsolute(normalized) || normalized.startsWith("..") || normalized.includes(`${path.sep}..${path.sep}`)) {
    return null;
  }

  const ext = path.extname(normalized).toLowerCase();
  if (!IMAGE_EXTENSIONS.has(ext)) {
    return null;
  }

  let fullPath;
  if (normalized.startsWith(`exports${path.sep}`) || normalized.startsWith(`finance${path.sep}`)) {
    fullPath = path.resolve(rootDir, normalized);
  } else if (fromPath) {
    const sourceFile = resolveReadablePath(fromPath);
    if (!sourceFile) {
      return null;
    }
    fullPath = path.resolve(path.dirname(sourceFile), normalized);
  } else {
    return null;
  }

  const relative = path.relative(rootDir, fullPath);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return null;
  }

  return { fullPath, mimeType: MIME_TYPES[ext] };
}

async function readImageResponse(imageInfo) {
  return {
    data: await fs.readFile(imageInfo.fullPath),
    mimeType: imageInfo.mimeType,
  };
}

async function readThumbnailResponse(imageInfo) {
  const thumbnailPath = path.join(path.dirname(imageInfo.fullPath), "thumbs", `${path.basename(imageInfo.fullPath)}.jpg`);
  try {
    return {
      data: await fs.readFile(thumbnailPath),
      mimeType: "image/jpeg",
    };
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
    return readImageResponse(imageInfo);
  }
}

async function handleRequest(req, res) {
  const requestUrl = new URL(req.url || "/", `http://${host}`);

  const vendorAsset = VENDOR_ASSETS.get(requestUrl.pathname);
  if (vendorAsset) {
    try {
      await sendStaticFile(res, vendorAsset);
    } catch (error) {
      if (error && error.code === "ENOENT") {
        sendJson(res, 404, { error: "Vendor asset not found. Run npm install first." });
        return;
      }
      throw error;
    }
    return;
  }

  if (requestUrl.pathname === "/" || requestUrl.pathname === "/index.html") {
    const html = await fs.readFile(indexPath, "utf8");
    sendText(res, 200, html, "text/html; charset=utf-8");
    return;
  }

  if (requestUrl.pathname === "/api/index") {
    const module = getReaderModule(requestUrl.searchParams.get("module"));
    let fileIndex;
    try {
      fileIndex = await getFileIndex();
    } catch (error) {
      if (error?.code === "ENOENT" || error?.name === "SyntaxError" || error?.message === "Invalid reader file index") {
        sendJson(res, 503, { error: "Reader file index is unavailable. Run node tools/xianzhi-reader/server.mjs --rebuild-index." });
        return;
      }
      throw error;
    }
    await sendListIndex(req, res, fileIndex, module);
    return;
  }

  if (requestUrl.pathname === "/api/file") {
    const requestedPath = requestUrl.searchParams.get("path");
    const indexedFile = requestedPath ? await getIndexedFile(requestedPath) : null;
    const filePath = indexedFile ? resolveReadablePath(indexedFile.path) : null;
    if (!filePath) {
      sendJson(res, 403, { error: "Forbidden path" });
      return;
    }

    try {
      const content = await fs.readFile(filePath, "utf8");
      sendJson(res, 200, { content });
    } catch (error) {
      if (error && error.code === "ENOENT") {
        sendJson(res, 404, { error: "File not found" });
        return;
      }
      throw error;
    }
    return;
  }

  if (requestUrl.pathname === "/api/html") {
    const requestedPath = requestUrl.searchParams.get("path");
    const indexedFile = requestedPath ? await getIndexedFile(requestedPath) : null;
    const filePath = indexedFile?.type === "html" ? resolveReadablePath(indexedFile.path) : null;
    if (!filePath) {
      sendJson(res, 403, { error: "Forbidden path" });
      return;
    }

    try {
      const content = await fs.readFile(filePath, "utf8");
      sendText(res, 200, content, "text/html; charset=utf-8");
    } catch (error) {
      if (error && error.code === "ENOENT") {
        sendJson(res, 404, { error: "File not found" });
        return;
      }
      throw error;
    }
    return;
  }

  if (requestUrl.pathname === "/api/image") {
    const imageInfo = resolveImagePath(requestUrl.searchParams.get("path"), requestUrl.searchParams.get("from"));
    if (!imageInfo) {
      sendJson(res, 403, { error: "Forbidden path" });
      return;
    }
    try {
      const image = requestUrl.searchParams.get("variant") === "thumbnail"
        ? await readThumbnailResponse(imageInfo)
        : await readImageResponse(imageInfo);
      res.writeHead(200, {
        "Content-Type": image.mimeType,
        "Content-Length": image.data.length,
        "Cache-Control": "private, max-age=300",
      });
      res.end(image.data);
    } catch (error) {
      if (error && error.code === "ENOENT") {
        sendJson(res, 404, { error: "Image not found" });
        return;
      }
      throw error;
    }
    return;
  }

  sendJson(res, 404, { error: "Not found" });
}

function createServer() {
  return http.createServer((req, res) => {
    handleRequest(req, res).catch((error) => {
      console.error(error);
      sendJson(res, 500, { error: "Internal server error" });
    });
  });
}

function listen(server, port) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.off("error", reject);
      resolve(port);
    });
  });
}

async function start() {
  await fs.access(financeRootDir);
  await ensureFileIndex();
  let lastError = null;

  for (let port = startPort; port < startPort + 20; port += 1) {
    const server = createServer();
    try {
      await listen(server, port);
      console.log(`投研 Markdown 阅读器已启动: http://${host}:${port}`);
      console.log("按 Ctrl+C 停止服务");
      return;
    } catch (error) {
      lastError = error;
      if (!error || error.code !== "EADDRINUSE") {
        throw error;
      }
    }
  }

  throw lastError || new Error("No available port");
}

async function main() {
  if (process.argv.includes("--rebuild-index")) {
    const fileIndex = await rebuildFileIndex();
    const fileCount = Object.values(fileIndex.modules).reduce((count, files) => count + files.length, 0);
    console.log(`阅读器索引已重建: ${fileCount} 个文件`);
    return;
  }
  await start();
}

main().catch((error) => {
  console.error(`启动失败: ${error.message}`);
  process.exitCode = 1;
});
