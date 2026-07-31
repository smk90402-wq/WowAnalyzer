import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.js";

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const REPLAY_ID = "0123456789abcdef01234567";
const UNSAFE_VIDEO_ID = "abcdefabcdefabcdefabcdef";
const UNKNOWN_VIDEO_ID = "111111111111111111111111";
const STALE_ID = "222222222222222222222222";
const MANIFEST_V1 = JSON.stringify({
  schema_version: 1,
  generated_at: "2026-07-31T00:00:00Z",
  rows: [
    {
      id: REPLAY_ID,
      public_artifacts: {
        detail: `replays/${REPLAY_ID}/detail.json`,
        frames: `replays/${REPLAY_ID}/frames.json`,
        terrain: `replays/${REPLAY_ID}/terrain.json`,
        video: `videos/${REPLAY_ID}`,
      },
    },
    {
      id: UNSAFE_VIDEO_ID,
      public_artifacts: {
        detail: `replays/${UNSAFE_VIDEO_ID}/detail.json`,
        frames: `replays/${UNSAFE_VIDEO_ID}/frames.json`,
        terrain: null,
        video: `videos/${UNSAFE_VIDEO_ID}`,
      },
    },
  ],
  stats: { replays: 2, videos: 2, terrain: 1 },
});

class FakeR2Object {
  constructor(key, body, contentType = "application/octet-stream", contentDisposition = null) {
    this.key = key;
    this.bytes = typeof body === "string" ? encoder.encode(body) : body;
    this.size = this.bytes.byteLength;
    this.etag = `etag-${key}`;
    this.httpEtag = `"${this.etag}"`;
    this.uploaded = new Date("2026-07-31T00:00:00.456Z");
    this.httpMetadata = { contentType, contentDisposition };
  }

  writeHttpMetadata(headers) {
    headers.set("Content-Type", this.httpMetadata.contentType);
    if (this.httpMetadata.contentDisposition !== null) {
      headers.set("Content-Disposition", this.httpMetadata.contentDisposition);
    }
  }

  async json() {
    return JSON.parse(decoder.decode(this.bytes));
  }
}

class FakeBucket {
  constructor() {
    this.objects = new Map([
      ["logs/WoWCombatLog.txt", new FakeR2Object("logs/WoWCombatLog.txt", "private")],
      [
        "_internal/public_video_map.json",
        new FakeR2Object(
          "_internal/public_video_map.json",
          JSON.stringify({
            schemaVersion: 1,
            videos: {
              [REPLAY_ID]: "cctv/example.mp4",
              [UNSAFE_VIDEO_ID]: "logs/private.mp4",
              [STALE_ID]: "cctv/stale.mp4",
            },
          }),
          "application/json",
        ),
      ],
      [
        "public/manifest.json",
        new FakeR2Object("public/manifest.json", MANIFEST_V1, "application/json"),
      ],
      [
        `public/replays/${REPLAY_ID}/detail.json`,
        new FakeR2Object(
          `public/replays/${REPLAY_ID}/detail.json`,
          '{"schema_version":1,"fight":1}',
          "application/json",
        ),
      ],
      [
        `public/replays/${REPLAY_ID}/frames.json`,
        new FakeR2Object(
          `public/replays/${REPLAY_ID}/frames.json`,
          '{"schema_version":1,"frames":[]}',
          "application/json",
        ),
      ],
      [
        `public/replays/${REPLAY_ID}/terrain.json`,
        new FakeR2Object(
          `public/replays/${REPLAY_ID}/terrain.json`,
          '{"schema_version":1,"heights":[]}',
          "application/json",
        ),
      ],
      [
        `public/replays/${STALE_ID}/detail.json`,
        new FakeR2Object(
          `public/replays/${STALE_ID}/detail.json`,
          '{"schema_version":1,"fight":"stale"}',
          "application/json",
        ),
      ],
      [
        "cctv/example.mp4",
        new FakeR2Object(
          "cctv/example.mp4",
          "0123456789",
          "video/mp4",
          'attachment; filename="original-secret-name.mp4"',
        ),
      ],
      ["cctv/stale.mp4", new FakeR2Object("cctv/stale.mp4", "stale-video", "video/mp4")],
      ["cctv/unmapped.mp4", new FakeR2Object("cctv/unmapped.mp4", "unmapped", "video/mp4")],
    ]);
    this.calls = [];
  }

  async head(key) {
    this.calls.push(["head", key]);
    return this.objects.get(key) ?? null;
  }

  async get(key, options = {}) {
    this.calls.push(["get", key, options]);
    const stored = this.objects.get(key);
    if (!stored) {
      return null;
    }

    const result = Object.create(stored);
    if (options.range) {
      const { offset, length } = options.range;
      result.body = stored.bytes.slice(offset, offset + length);
      result.range = { offset, length };
    } else {
      result.body = stored.bytes;
    }
    return result;
  }
}

function makeEnv(overrides = {}) {
  return {
    PUBLIC_DATA: new FakeBucket(),
    CORS_ALLOW_ORIGINS: "*",
    ...overrides,
  };
}

async function fetchPath(path, init = {}, env = makeEnv()) {
  const request = new Request(`https://replay-data.example.com${path}`, init);
  return { response: await worker.fetch(request, env), env };
}

test("serves the three manifest-authorized replay artifacts", async () => {
  const env = makeEnv();
  for (const artifact of ["detail", "frames", "terrain"]) {
    const { response } = await fetchPath(
      `/replays/${REPLAY_ID}/${artifact}.json`,
      {},
      env,
    );
    assert.equal(response.status, 200, artifact);
    assert.equal(response.headers.get("content-type"), "application/json");
    assert.equal(response.headers.get("accept-ranges"), "bytes");
    assert.equal(response.headers.get("access-control-allow-origin"), "*");
    assert.equal(
      response.headers.get("cache-control"),
      "public, no-cache, must-revalidate",
    );
  }
  assert.deepEqual(
    env.PUBLIC_DATA.calls.map((call) => call[1]),
    [
      "public/manifest.json",
      `public/replays/${REPLAY_ID}/detail.json`,
      "public/manifest.json",
      `public/replays/${REPLAY_ID}/frames.json`,
      "public/manifest.json",
      `public/replays/${REPLAY_ID}/terrain.json`,
    ],
  );
});

test("manifest alias serves public/manifest.json with short caching", async () => {
  const { response, env } = await fetchPath("/manifest.json");

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), JSON.parse(MANIFEST_V1));
  assert.match(response.headers.get("content-type"), /^application\/json/);
  assert.match(response.headers.get("cache-control"), /s-maxage=300/);
  assert.deepEqual(env.PUBLIC_DATA.calls[0].slice(0, 2), ["get", "public/manifest.json"]);
});

test("blocks private and direct storage routes before R2 access", async () => {
  const env = makeEnv();
  const paths = [
    "/logs/WoWCombatLog.txt",
    "/_internal/public_video_map.json",
    "/cctv/example.mp4",
    "/public/manifest.json",
    `/public/replays/${REPLAY_ID}/detail.json`,
    "/replays/example.json",
    `/replays/${REPLAY_ID}/other.json`,
    `/replays/${REPLAY_ID}/detail.txt`,
    `/replays/${REPLAY_ID.toUpperCase()}/detail.json`,
    `/replays/${REPLAY_ID.slice(1)}/detail.json`,
    `/replays/${REPLAY_ID}0/detail.json`,
    `/replays/${REPLAY_ID}/nested/detail.json`,
    "/replays/../logs/secret.txt",
    "/replays/%2e%2e/logs/secret.txt",
    "/replays/example%5Csecret.json",
    "/api/v1/objects",
  ];

  for (const path of paths) {
    const request = new Request(`https://replay-data.example.com${path}`);
    const response = await worker.fetch(request, env);
    assert.equal(response.status, 404, path);
  }
  assert.deepEqual(env.PUBLIC_DATA.calls, []);
});

test("resolves a public id through the private video map", async () => {
  const { response, env } = await fetchPath(`/videos/${REPLAY_ID}`);

  assert.equal(response.status, 200);
  assert.equal(await response.text(), "0123456789");
  assert.equal(response.headers.get("content-type"), "video/mp4");
  assert.equal(response.headers.get("content-disposition"), null);
  assert.deepEqual(
    env.PUBLIC_DATA.calls.map((call) => call.slice(0, 2)),
    [
      ["get", "public/manifest.json"],
      ["get", "_internal/public_video_map.json"],
      ["get", "cctv/example.mp4"],
    ],
  );
  assert.equal(response.headers.get("location"), null);
});

test("rejects unknown ids, malformed ids, and unsafe private-map targets", async () => {
  const unknown = await fetchPath(`/videos/${UNKNOWN_VIDEO_ID}`);
  const unsafe = await fetchPath(`/videos/${UNSAFE_VIDEO_ID}`);
  const malformed = await fetchPath("/videos/not/one-id");

  assert.equal(unknown.response.status, 404);
  assert.equal(unsafe.response.status, 404);
  assert.equal(malformed.response.status, 404);
  assert.deepEqual(unknown.env.PUBLIC_DATA.calls.map((call) => call[1]), [
    "public/manifest.json",
  ]);
  assert.deepEqual(unsafe.env.PUBLIC_DATA.calls.map((call) => call[1]), [
    "public/manifest.json",
    "_internal/public_video_map.json",
  ]);
  assert.deepEqual(malformed.env.PUBLIC_DATA.calls, []);
});

test("returns 404 for stale replay and video objects that still exist in R2", async () => {
  const env = makeEnv();

  const replay = await worker.fetch(
    new Request(`https://replay-data.example.com/replays/${STALE_ID}/detail.json`),
    env,
  );
  assert.equal(replay.status, 404);
  assert.deepEqual(env.PUBLIC_DATA.calls.map((call) => call.slice(0, 2)), [
    ["get", "public/manifest.json"],
  ]);

  env.PUBLIC_DATA.calls.length = 0;
  const video = await worker.fetch(
    new Request(`https://replay-data.example.com/videos/${STALE_ID}`),
    env,
  );
  assert.equal(video.status, 404);
  assert.deepEqual(env.PUBLIC_DATA.calls.map((call) => call.slice(0, 2)), [
    ["get", "public/manifest.json"],
  ]);
});

test("fails closed when the manifest is malformed, inconsistent, or oversized", async () => {
  const malformedEnv = makeEnv();
  const malformed = JSON.parse(MANIFEST_V1);
  malformed.rows[0].public_artifacts.detail =
    `replays/${REPLAY_ID}/frames.json`;
  malformedEnv.PUBLIC_DATA.objects.set(
    "public/manifest.json",
    new FakeR2Object(
      "public/manifest.json",
      JSON.stringify(malformed),
      "application/json",
    ),
  );

  const malformedReplay = await worker.fetch(
    new Request(`https://replay-data.example.com/replays/${REPLAY_ID}/detail.json`),
    malformedEnv,
  );
  const malformedVideo = await worker.fetch(
    new Request(`https://replay-data.example.com/videos/${REPLAY_ID}`),
    malformedEnv,
  );
  assert.equal(malformedReplay.status, 404);
  assert.equal(malformedVideo.status, 404);
  assert.deepEqual(malformedEnv.PUBLIC_DATA.calls.map((call) => call[1]), [
    "public/manifest.json",
    "public/manifest.json",
  ]);

  const inconsistentEnv = makeEnv();
  const inconsistent = JSON.parse(MANIFEST_V1);
  inconsistent.stats.videos = 1;
  inconsistentEnv.PUBLIC_DATA.objects.set(
    "public/manifest.json",
    new FakeR2Object(
      "public/manifest.json",
      JSON.stringify(inconsistent),
      "application/json",
    ),
  );
  const inconsistentReplay = await worker.fetch(
    new Request(`https://replay-data.example.com/replays/${REPLAY_ID}/detail.json`),
    inconsistentEnv,
  );
  assert.equal(inconsistentReplay.status, 404);
  assert.deepEqual(inconsistentEnv.PUBLIC_DATA.calls.map((call) => call[1]), [
    "public/manifest.json",
  ]);

  const invalidJsonEnv = makeEnv();
  invalidJsonEnv.PUBLIC_DATA.objects.set(
    "public/manifest.json",
    new FakeR2Object("public/manifest.json", "{", "application/json"),
  );
  const invalidJsonReplay = await worker.fetch(
    new Request(`https://replay-data.example.com/replays/${REPLAY_ID}/detail.json`),
    invalidJsonEnv,
  );
  assert.equal(invalidJsonReplay.status, 404);
  assert.deepEqual(invalidJsonEnv.PUBLIC_DATA.calls.map((call) => call[1]), [
    "public/manifest.json",
  ]);

  const oversizedEnv = makeEnv();
  oversizedEnv.PUBLIC_DATA.objects.get("public/manifest.json").size =
    17 * 1024 * 1024;
  const oversizedReplay = await worker.fetch(
    new Request(`https://replay-data.example.com/replays/${REPLAY_ID}/detail.json`),
    oversizedEnv,
  );
  assert.equal(oversizedReplay.status, 404);
  assert.deepEqual(oversizedEnv.PUBLIC_DATA.calls.map((call) => call[1]), [
    "public/manifest.json",
  ]);
});

test("supports a single bounded video byte range", async () => {
  const { response, env } = await fetchPath(`/videos/${REPLAY_ID}`, {
    headers: { Range: "bytes=2-5" },
  });

  assert.equal(response.status, 206);
  assert.equal(await response.text(), "2345");
  assert.equal(response.headers.get("content-range"), "bytes 2-5/10");
  assert.equal(response.headers.get("content-length"), "4");
  assert.deepEqual(env.PUBLIC_DATA.calls.map((call) => call[0]), [
    "get",
    "get",
    "head",
    "get",
  ]);
  assert.deepEqual(env.PUBLIC_DATA.calls[3][2], { range: { offset: 2, length: 4 } });
});

test("supports suffix ranges and rejects unsatisfiable or multiple ranges", async () => {
  const suffix = await fetchPath(`/videos/${REPLAY_ID}`, {
    headers: { Range: "bytes=-3" },
  });
  assert.equal(suffix.response.status, 206);
  assert.equal(await suffix.response.text(), "789");

  for (const value of ["bytes=99-", "bytes=5-3", "bytes=0-1,4-5"]) {
    const { response } = await fetchPath(`/videos/${REPLAY_ID}`, {
      headers: { Range: value },
    });
    assert.equal(response.status, 416, value);
    assert.equal(response.headers.get("content-range"), "bytes */10");
  }
});

test("honors If-None-Match without downloading the replay body", async () => {
  const env = makeEnv();
  const response = await worker.fetch(
    new Request(`https://replay-data.example.com/replays/${REPLAY_ID}/detail.json`, {
      headers: {
        "If-None-Match": `W/"etag-public/replays/${REPLAY_ID}/detail.json"`,
      },
    }),
    env,
  );

  assert.equal(response.status, 304);
  assert.equal(await response.text(), "");
  assert.deepEqual(env.PUBLIC_DATA.calls.map((call) => call[0]), ["get", "head"]);
});

test("HEAD resolves the map and returns video metadata without downloading video", async () => {
  const env = makeEnv();
  const response = await worker.fetch(
    new Request(`https://replay-data.example.com/videos/${REPLAY_ID}`, {
      method: "HEAD",
    }),
    env,
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-length"), "10");
  assert.equal(await response.text(), "");
  assert.deepEqual(env.PUBLIC_DATA.calls.map((call) => call[0]), [
    "get",
    "get",
    "head",
  ]);
});

test("If-Range mismatch falls back to a full video response", async () => {
  const { response, env } = await fetchPath(`/videos/${REPLAY_ID}`, {
    headers: {
      Range: "bytes=2-5",
      "If-Range": '"different-etag"',
    },
  });

  assert.equal(response.status, 200);
  assert.equal(await response.text(), "0123456789");
  assert.equal(response.headers.get("content-range"), null);
  assert.deepEqual(env.PUBLIC_DATA.calls.map((call) => call[0]), [
    "get",
    "get",
    "head",
    "get",
  ]);
});

test("date If-Range matches Last-Modified at HTTP second precision", async () => {
  const env = makeEnv();
  const lastModified = env.PUBLIC_DATA.objects
    .get("cctv/example.mp4")
    .uploaded.toUTCString();
  const response = await worker.fetch(
    new Request(`https://replay-data.example.com/videos/${REPLAY_ID}`, {
      headers: {
        Range: "bytes=2-5",
        "If-Range": lastModified,
      },
    }),
    env,
  );

  assert.equal(response.status, 206);
  assert.equal(await response.text(), "2345");
  assert.equal(response.headers.get("content-range"), "bytes 2-5/10");
  assert.deepEqual(env.PUBLIC_DATA.calls.map((call) => call[0]), [
    "get",
    "get",
    "head",
    "get",
  ]);
});

test("write methods never reach the bucket", async () => {
  const env = makeEnv();
  const response = await worker.fetch(
    new Request("https://replay-data.example.com/manifest.json", {
      method: "PUT",
      body: "{}",
    }),
    env,
  );

  assert.equal(response.status, 405);
  assert.equal(response.headers.get("allow"), "GET, HEAD, OPTIONS");
  assert.deepEqual(env.PUBLIC_DATA.calls, []);
});

test("CORS preflight permits only read methods and honors an origin allowlist", async () => {
  const env = makeEnv({ CORS_ALLOW_ORIGINS: "https://app.example.com,https://backup.example.com" });
  const allowed = await worker.fetch(
    new Request("https://replay-data.example.com/manifest.json", {
      method: "OPTIONS",
      headers: {
        Origin: "https://app.example.com",
        "Access-Control-Request-Method": "GET",
      },
    }),
    env,
  );
  const rejected = await worker.fetch(
    new Request("https://replay-data.example.com/manifest.json", {
      method: "OPTIONS",
      headers: {
        Origin: "https://untrusted.example.com",
        "Access-Control-Request-Method": "GET",
      },
    }),
    env,
  );
  const write = await worker.fetch(
    new Request("https://replay-data.example.com/manifest.json", {
      method: "OPTIONS",
      headers: {
        Origin: "https://app.example.com",
        "Access-Control-Request-Method": "PUT",
      },
    }),
    env,
  );

  assert.equal(allowed.status, 204);
  assert.equal(allowed.headers.get("access-control-allow-origin"), "https://app.example.com");
  assert.equal(allowed.headers.get("vary"), "Origin");
  assert.equal(rejected.status, 403);
  assert.equal(write.status, 403);
  assert.deepEqual(env.PUBLIC_DATA.calls, []);
});
