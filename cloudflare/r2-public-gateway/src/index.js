const PUBLIC_PREFIX = "public/";
const MANIFEST_KEY = `${PUBLIC_PREFIX}manifest.json`;
const VIDEO_MAP_KEY = "_internal/public_video_map.json";
const MAX_MANIFEST_BYTES = 16 * 1024 * 1024;
const MAX_VIDEO_MAP_BYTES = 1024 * 1024;
const REPLAY_PATH_PATTERN = /^\/replays\/([a-f0-9]{24})\/(detail|frames|terrain)\.json$/;

const DEFAULT_ASSET_CACHE_CONTROL = "public, no-cache, must-revalidate";
const DEFAULT_MANIFEST_CACHE_CONTROL = "public, max-age=60, s-maxage=300";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const route = resolveRoute(url.pathname);

    if (route === null) {
      return errorResponse(request, env, 404, "not_found");
    }

    if (request.method === "OPTIONS") {
      return preflightResponse(request, env);
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return errorResponse(request, env, 405, "method_not_allowed", {
        Allow: "GET, HEAD, OPTIONS",
      });
    }

    if (!env.PUBLIC_DATA) {
      return errorResponse(request, env, 503, "service_unavailable");
    }

    try {
      if (route.kind === "video") {
        return await serveMappedVideo(request, env, route.replayId);
      }
      if (
        !route.manifest &&
        !(await manifestAuthorizes(
          env,
          route.replayId,
          route.artifact,
          route.publicRef,
        ))
      ) {
        return errorResponse(request, env, 404, "not_found");
      }
      return await serveObject(request, env, route);
    } catch (error) {
      console.error("R2 public gateway request failed", error);
      return errorResponse(request, env, 502, "storage_unavailable");
    }
  },
};

function resolveRoute(pathname) {
  const decoded = decodePath(pathname);
  if (decoded === null) {
    return null;
  }

  if (decoded === "/manifest.json") {
    return { kind: "object", key: MANIFEST_KEY, manifest: true };
  }

  const replayMatch = REPLAY_PATH_PATTERN.exec(decoded);
  if (replayMatch !== null) {
    const [, replayId, artifact] = replayMatch;
    const publicRef = `replays/${replayId}/${artifact}.json`;
    return {
      kind: "object",
      key: `${PUBLIC_PREFIX}${publicRef}`,
      manifest: false,
      replayId,
      artifact,
      publicRef,
    };
  }

  if (decoded.startsWith("/videos/")) {
    const replayId = decoded.slice("/videos/".length);
    if (!isSafeReplayId(replayId)) {
      return null;
    }
    return { kind: "video", replayId };
  }

  return null;
}

function decodePath(pathname) {
  try {
    const decoded = pathname
      .split("/")
      .map((segment) => decodeURIComponent(segment))
      .join("/");

    if (decoded.includes("\\") || decoded.includes("\0")) {
      return null;
    }
    return decoded;
  } catch {
    return null;
  }
}

function isSafeReplayId(replayId) {
  return /^[a-f0-9]{24}$/.test(replayId);
}

function isSafeVideoKey(key) {
  return (
    typeof key === "string" &&
    /^cctv\/[^/\\]+\.mp4$/i.test(key) &&
    !key.includes("..")
  );
}

async function manifestAuthorizes(env, replayId, artifact, publicRef) {
  const membership = await loadManifestMembership(env);
  const artifacts = membership?.get(replayId);
  return artifacts !== undefined && artifacts[artifact] === publicRef;
}

async function loadManifestMembership(env) {
  const manifestObject = await env.PUBLIC_DATA.get(MANIFEST_KEY);
  if (
    manifestObject === null ||
    !Number.isSafeInteger(manifestObject.size) ||
    manifestObject.size < 0 ||
    manifestObject.size > MAX_MANIFEST_BYTES
  ) {
    return null;
  }

  let manifest;
  try {
    manifest = await manifestObject.json();
  } catch {
    return null;
  }

  if (
    !isRecord(manifest) ||
    manifest.schema_version !== 1 ||
    typeof manifest.generated_at !== "string" ||
    manifest.generated_at.length === 0 ||
    !Array.isArray(manifest.rows) ||
    !isManifestStats(manifest.stats)
  ) {
    return null;
  }

  const membership = new Map();
  let videoCount = 0;
  let terrainCount = 0;

  for (const row of manifest.rows) {
    if (
      !isRecord(row) ||
      !isSafeReplayId(row.id) ||
      membership.has(row.id) ||
      !isValidPublicArtifacts(row.id, row.public_artifacts)
    ) {
      return null;
    }

    membership.set(row.id, row.public_artifacts);
    if (row.public_artifacts.video !== null) {
      videoCount += 1;
    }
    if (row.public_artifacts.terrain !== null) {
      terrainCount += 1;
    }
  }

  if (
    manifest.stats.replays !== membership.size ||
    manifest.stats.videos !== videoCount ||
    manifest.stats.terrain !== terrainCount
  ) {
    return null;
  }

  return membership;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isManifestStats(stats) {
  return (
    isRecord(stats) &&
    isNonNegativeInteger(stats.replays) &&
    isNonNegativeInteger(stats.videos) &&
    isNonNegativeInteger(stats.terrain)
  );
}

function isNonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function isValidPublicArtifacts(replayId, artifacts) {
  if (!isRecord(artifacts)) {
    return false;
  }

  const detail = `replays/${replayId}/detail.json`;
  const frames = `replays/${replayId}/frames.json`;
  const terrain = `replays/${replayId}/terrain.json`;
  const video = `videos/${replayId}`;
  return (
    artifacts.detail === detail &&
    artifacts.frames === frames &&
    (artifacts.terrain === null || artifacts.terrain === terrain) &&
    (artifacts.video === null || artifacts.video === video)
  );
}

async function serveMappedVideo(request, env, replayId) {
  const publicRef = `videos/${replayId}`;
  if (!(await manifestAuthorizes(env, replayId, "video", publicRef))) {
    return errorResponse(request, env, 404, "not_found");
  }

  const mapObject = await env.PUBLIC_DATA.get(VIDEO_MAP_KEY);
  if (mapObject === null) {
    return errorResponse(request, env, 404, "not_found");
  }
  if (mapObject.size > MAX_VIDEO_MAP_BYTES) {
    throw new Error("public video map exceeds size limit");
  }

  const payload = await mapObject.json();
  const videos = payload?.videos;
  if (
    videos === null ||
    typeof videos !== "object" ||
    Array.isArray(videos) ||
    !Object.hasOwn(videos, replayId)
  ) {
    return errorResponse(request, env, 404, "not_found");
  }

  const key = videos[replayId];
  if (!isSafeVideoKey(key)) {
    return errorResponse(request, env, 404, "not_found");
  }

  return serveObject(request, env, {
    kind: "object",
    key,
    manifest: false,
    privateVideo: true,
  });
}

async function serveObject(request, env, route) {
  const isHead = request.method === "HEAD";
  const requestedRange = isHead ? null : request.headers.get("Range");
  const ifNoneMatch = request.headers.get("If-None-Match");
  let metadata = null;

  if (isHead || requestedRange !== null || ifNoneMatch !== null) {
    metadata = await env.PUBLIC_DATA.head(route.key);
    if (metadata === null) {
      return errorResponse(request, env, 404, "not_found");
    }

    if (ifNoneMatch !== null && etagMatches(ifNoneMatch, metadata.httpEtag)) {
      const headers = objectHeaders(request, env, metadata, route.manifest, route.privateVideo);
      return new Response(null, { status: 304, headers });
    }

    if (isHead) {
      const headers = objectHeaders(request, env, metadata, route.manifest, route.privateVideo);
      headers.set("Content-Length", String(metadata.size));
      return new Response(null, { status: 200, headers });
    }
  }

  let range = null;
  if (requestedRange !== null && ifRangeAllows(request.headers.get("If-Range"), metadata)) {
    range = parseRange(requestedRange, metadata.size);
    if (range === null) {
      return rangeNotSatisfiable(request, env, metadata.size);
    }
  }

  const object = range === null
    ? await env.PUBLIC_DATA.get(route.key)
    : await env.PUBLIC_DATA.get(route.key, { range: { offset: range.offset, length: range.length } });

  if (object === null || object.body === undefined) {
    return errorResponse(request, env, 404, "not_found");
  }

  const headers = objectHeaders(request, env, object, route.manifest, route.privateVideo);
  if (range !== null) {
    headers.set("Content-Range", `bytes ${range.offset}-${range.offset + range.length - 1}/${metadata.size}`);
    headers.set("Content-Length", String(range.length));
    return new Response(object.body, { status: 206, headers });
  }

  headers.set("Content-Length", String(object.size));
  return new Response(object.body, { status: 200, headers });
}

function parseRange(value, size) {
  const match = /^bytes=(\d*)-(\d*)$/.exec(value.trim());
  if (match === null || (match[1] === "" && match[2] === "") || size === 0) {
    return null;
  }

  if (match[1] === "") {
    const suffixLength = parseSafeInteger(match[2]);
    if (suffixLength === null || suffixLength === 0) {
      return null;
    }
    const length = Math.min(suffixLength, size);
    return { offset: size - length, length };
  }

  const start = parseSafeInteger(match[1]);
  if (start === null || start >= size) {
    return null;
  }

  if (match[2] === "") {
    return { offset: start, length: size - start };
  }

  const requestedEnd = parseSafeInteger(match[2]);
  if (requestedEnd === null || requestedEnd < start) {
    return null;
  }

  const end = Math.min(requestedEnd, size - 1);
  return { offset: start, length: end - start + 1 };
}

function parseSafeInteger(value) {
  if (!/^\d+$/.test(value)) {
    return null;
  }
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function etagMatches(headerValue, objectEtag) {
  const comparableObjectEtag = stripWeakPrefix(objectEtag);
  return headerValue
    .split(",")
    .map((value) => value.trim())
    .some((value) => value === "*" || stripWeakPrefix(value) === comparableObjectEtag);
}

function stripWeakPrefix(value) {
  return value.startsWith("W/") ? value.slice(2) : value;
}

function ifRangeAllows(ifRange, metadata) {
  if (ifRange === null || ifRange === "") {
    return true;
  }

  if (ifRange.startsWith('"')) {
    return ifRange === metadata.httpEtag;
  }

  const ifRangeDate = Date.parse(ifRange);
  const uploadedAtHttpPrecision =
    Math.floor(metadata.uploaded.getTime() / 1000) * 1000;
  return (
    Number.isFinite(ifRangeDate) &&
    uploadedAtHttpPrecision <= ifRangeDate
  );
}

function objectHeaders(request, env, object, isManifest, isPrivateVideo = false) {
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  if (isPrivateVideo) {
    headers.delete("Content-Disposition");
  }
  headers.set("ETag", object.httpEtag);
  headers.set("Last-Modified", object.uploaded.toUTCString());
  headers.set("Accept-Ranges", "bytes");
  headers.set(
    "Cache-Control",
    isManifest
      ? (env.MANIFEST_CACHE_CONTROL || DEFAULT_MANIFEST_CACHE_CONTROL)
      : (env.ASSET_CACHE_CONTROL || DEFAULT_ASSET_CACHE_CONTROL),
  );
  if (isManifest) {
    headers.set("Content-Type", "application/json; charset=utf-8");
  } else if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/octet-stream");
  }
  applyCommonHeaders(headers, request, env);
  return headers;
}

function rangeNotSatisfiable(request, env, size) {
  const headers = new Headers({
    "Content-Range": `bytes */${size}`,
    "Accept-Ranges": "bytes",
  });
  return errorResponse(request, env, 416, "range_not_satisfiable", headers);
}

function preflightResponse(request, env) {
  const requestedMethod = request.headers.get("Access-Control-Request-Method");
  const origin = corsOrigin(request, env);

  if (
    origin === null ||
    (requestedMethod !== null && requestedMethod !== "GET" && requestedMethod !== "HEAD")
  ) {
    return errorResponse(request, env, 403, "cors_forbidden");
  }

  const headers = new Headers({
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range, If-None-Match, If-Range",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
  });
  applyCommonHeaders(headers, request, env);
  return new Response(null, { status: 204, headers });
}

function errorResponse(request, env, status, code, initialHeaders = undefined) {
  const payload = JSON.stringify({ error: code });
  const headers = new Headers(initialHeaders);
  headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("Cache-Control", "no-store");
  applyCommonHeaders(headers, request, env);
  return new Response(request.method === "HEAD" ? null : payload, { status, headers });
}

function applyCommonHeaders(headers, request, env) {
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set(
    "Access-Control-Expose-Headers",
    "Accept-Ranges, Cache-Control, Content-Disposition, Content-Length, Content-Range, ETag, Last-Modified",
  );

  const origin = corsOrigin(request, env);
  if (origin !== null) {
    headers.set("Access-Control-Allow-Origin", origin);
    if (origin !== "*") {
      appendVary(headers, "Origin");
    }
  }
}

function corsOrigin(request, env) {
  const configured = String(env.CORS_ALLOW_ORIGINS || "*")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  if (configured.includes("*")) {
    return "*";
  }

  const requestOrigin = request.headers.get("Origin");
  return requestOrigin !== null && configured.includes(requestOrigin)
    ? requestOrigin
    : null;
}

function appendVary(headers, value) {
  const current = headers.get("Vary");
  const values = current
    ? current.split(",").map((item) => item.trim())
    : [];
  if (!values.includes(value)) {
    values.push(value);
  }
  headers.set("Vary", values.join(", "));
}
