#!/usr/bin/env node
/** Structured benchmark adapter for pinned TencentDB Agent Memory v0.3.6 internals. */

import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const RRF_K = 60;
const EXPECTED_COMMIT = "438869bec84711fb09b12185d46702d98eeaf90e";

type Strategy = "keyword" | "vector" | "hybrid";
type Provider = "none" | "local-hash" | "openai";
type Ranked = { record_id: string; content: string; score: number };

function arg(name: string, fallback = ""): string {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? (process.argv[index + 1] ?? fallback) : fallback;
}

function required(name: string): string {
  const value = arg(name);
  if (!value) throw new Error(`--${name} is required`);
  return path.resolve(value);
}

function notePath(memoryDir: string, filename: string): string {
  if (!filename || path.isAbsolute(filename) || path.basename(filename) !== filename) {
    throw new Error(`unsafe note filename in curator index: ${filename}`);
  }
  const resolved = path.resolve(memoryDir, filename);
  if (fs.lstatSync(resolved).isSymbolicLink()) {
    throw new Error(`symlink notes are not allowed: ${filename}`);
  }
  const realRoot = `${fs.realpathSync(memoryDir)}${path.sep}`;
  const realFile = fs.realpathSync(resolved);
  if (!realFile.startsWith(realRoot)) throw new Error(`note escapes memory directory: ${filename}`);
  return realFile;
}

function verifyPinnedSource(sourceDir: string): void {
  const git = (...args: string[]) => execFileSync(
    "git",
    ["-C", sourceDir, ...args],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  ).trim();
  const commit = git("rev-parse", "HEAD");
  if (commit !== EXPECTED_COMMIT) {
    throw new Error(`pinned source mismatch: expected=${EXPECTED_COMMIT} actual=${commit}`);
  }
  try {
    execFileSync(
      "git",
      ["-C", sourceDir, "diff", "--quiet", "HEAD", "--", "."],
      { stdio: "ignore" },
    );
  } catch {
    throw new Error("pinned source has tracked local changes");
  }
}

function localDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isDefaultRoutable(note: Record<string, unknown>, today: string): boolean {
  if (note.status !== "active") return false;
  const reviewAfter = note.review_after;
  return typeof reviewAfter !== "string" || reviewAfter >= today;
}

function localHash(text: string, dimensions: number): Float32Array {
  const vector = new Float32Array(dimensions);
  const compact = [...text.toLowerCase()].filter((ch) => !/\s/u.test(ch)).join("");
  for (const width of [2, 3, 4]) {
    for (let index = 0; index <= compact.length - width; index++) {
      const gram = compact.slice(index, index + width);
      const digest = crypto.createHash("sha256").update(gram).digest();
      const bucket = digest.readUInt32BE(0) % dimensions;
      vector[bucket] += (digest[4]! & 1) === 1 ? 1 : -1;
    }
  }
  let norm = 0;
  for (const value of vector) norm += value * value;
  norm = Math.sqrt(norm) || 1;
  for (let index = 0; index < vector.length; index++) vector[index] /= norm;
  return vector;
}

async function remoteEmbedding(text: string, dimensions: number): Promise<Float32Array> {
  const baseUrl = process.env.CURATOR_EMBEDDING_BASE_URL?.replace(/\/$/, "");
  const apiKey = process.env.CURATOR_EMBEDDING_API_KEY;
  const model = process.env.CURATOR_EMBEDDING_MODEL;
  if (!baseUrl || !apiKey || !model) {
    throw new Error("CURATOR_EMBEDDING_BASE_URL/API_KEY/MODEL are required");
  }
  if (process.env.CURATOR_ALLOW_REMOTE_EMBEDDING !== "true") {
    throw new Error("set CURATOR_ALLOW_REMOTE_EMBEDDING=true to permit note egress");
  }
  const endpoint = new URL(baseUrl);
  if (endpoint.protocol !== "https:" && process.env.CURATOR_ALLOW_INSECURE_EMBEDDING !== "true") {
    throw new Error("remote embedding endpoint must use HTTPS");
  }
  const body: Record<string, unknown> = { model, input: text.slice(0, 5000) };
  if (process.env.CURATOR_EMBEDDING_SEND_DIMENSIONS !== "false") body.dimensions = dimensions;
  const response = await fetch(`${baseUrl}/embeddings`, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(Number(process.env.CURATOR_EMBEDDING_TIMEOUT_MS ?? 10000)),
  });
  if (!response.ok) throw new Error(`embedding HTTP ${response.status}`);
  const payload = await response.json() as { data?: Array<{ embedding?: number[] }> };
  const values = payload.data?.[0]?.embedding;
  if (!values || values.length !== dimensions) {
    throw new Error(`embedding dimensions mismatch: expected=${dimensions} actual=${values?.length}`);
  }
  return Float32Array.from(values);
}

async function embed(text: string, provider: Provider, dimensions: number): Promise<Float32Array | undefined> {
  if (provider === "none") return undefined;
  if (provider === "local-hash") return localHash(text, dimensions);
  return remoteEmbedding(text, dimensions);
}

function rrf(fts: Ranked[], vectors: Ranked[]): Ranked[] {
  const merged = new Map<string, Ranked>();
  for (const list of [fts, vectors]) {
    list.forEach((item, index) => {
      const score = 1 / (RRF_K + index + 1);
      const current = merged.get(item.record_id);
      merged.set(item.record_id, { ...item, score: (current?.score ?? 0) + score });
    });
  }
  return [...merged.values()].sort((a, b) => b.score - a.score || a.record_id.localeCompare(b.record_id));
}

function typeFor(noteType: string): "persona" | "episodic" | "instruction" {
  if (noteType === "feedback" || noteType === "preference" || noteType === "workflow") return "instruction";
  return "episodic";
}

function corpusHash(memoryDir: string, index: unknown): string {
  const hash = crypto.createHash("sha256").update(JSON.stringify(index));
  const notes = (index as { notes?: Array<{ file?: string }> }).notes ?? [];
  for (const note of notes.sort((a, b) => String(a.file).localeCompare(String(b.file)))) {
    if (note.file) hash.update(fs.readFileSync(notePath(memoryDir, note.file)));
  }
  return hash.digest("hex");
}

function verifyCuratorIndex(memoryDir: string, index: unknown): void {
  const payload = index as {
    schema_version?: number;
    source_hashes?: Record<string, string>;
    notes?: Array<{ file?: string; content_hash?: string }>;
  };
  if (payload.schema_version !== 3 || !Array.isArray(payload.notes)) {
    throw new Error("curator index schema is missing or unsupported");
  }
  const memoryFile = path.join(memoryDir, "MEMORY.md");
  const memoryHash = crypto.createHash("sha256").update(fs.readFileSync(memoryFile)).digest("hex");
  if (payload.source_hashes?.["MEMORY.md"] !== memoryHash) {
    throw new Error("curator index is stale: MEMORY.md hash mismatch");
  }
  const diskNotes = fs.readdirSync(memoryDir)
    .filter((name) => name.endsWith(".md") && name !== "MEMORY.md")
    .sort();
  const indexedNotes = payload.notes.map((note) => String(note.file ?? "")).sort();
  if (JSON.stringify(diskNotes) !== JSON.stringify(indexedNotes)) {
    throw new Error("curator index is stale: note file set mismatch");
  }
  const seen = new Set<string>();
  for (const note of payload.notes) {
    const filename = String(note.file ?? "");
    if (seen.has(filename)) throw new Error(`duplicate curator index file: ${filename}`);
    seen.add(filename);
    const raw = fs.readFileSync(notePath(memoryDir, filename));
    const contentHash = crypto.createHash("sha256").update(raw).digest("hex");
    if (!note.content_hash || note.content_hash !== contentHash) {
      throw new Error(`curator index is stale: content hash mismatch for ${filename}`);
    }
  }
}

async function loadStore(sourceDir: string, dbPath: string, dimensions: number, provider: Provider) {
  verifyPinnedSource(sourceDir);
  const sqliteUrl = pathToFileURL(path.join(sourceDir, "src/core/store/sqlite.ts")).href;
  const module = await import(sqliteUrl) as {
    VectorStore: new (dbPath: string, dimensions: number, logger?: unknown) => any;
    buildFtsQuery: (query: string) => string | null;
  };
  const logger = { info() {}, warn(message: string) { process.stderr.write(`${message}\n`); }, error(message: string) { process.stderr.write(`${message}\n`); } };
  const store = new module.VectorStore(dbPath, dimensions, logger);
  const model = provider === "openai" ? (process.env.CURATOR_EMBEDDING_MODEL ?? "remote") : provider;
  const init = await store.init(provider === "none" ? undefined : { provider, model });
  if (store.isDegraded()) throw new Error(`VectorStore degraded: ${init?.reason ?? "unknown"}`);
  return { store, buildFtsQuery: module.buildFtsQuery };
}

async function build(): Promise<void> {
  const sourceDir = required("source-dir");
  const memoryDir = required("memory-dir");
  const dbPath = required("db");
  const provider = (arg("provider", "none") as Provider);
  const dimensions = Number(arg("dimensions", provider === "none" ? "0" : "256"));
  if (!["none", "local-hash", "openai"].includes(provider)) throw new Error(`invalid provider: ${provider}`);
  if (!Number.isInteger(dimensions) || dimensions < 0 || dimensions > 4096 || (provider !== "none" && dimensions === 0)) {
    throw new Error(`invalid dimensions: ${dimensions}`);
  }
  const indexPath = path.join(memoryDir, ".curator-index.json");
  const index = JSON.parse(fs.readFileSync(indexPath, "utf8")) as {
    notes: Array<Record<string, unknown>>;
  };
  verifyCuratorIndex(memoryDir, index);

  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const temporaryDb = `${dbPath}.${process.pid}.tmp`;
  for (const suffix of ["", "-wal", "-shm"]) fs.rmSync(`${temporaryDb}${suffix}`, { force: true });
  const { store } = await loadStore(sourceDir, temporaryDb, dimensions, provider);
  const activeAsOf = localDate();
  let inserted = 0;
  let completed = false;
  try {
    for (const note of index.notes) {
      if (!isDefaultRoutable(note, activeAsOf)) continue;
      const file = String(note.file);
      const sourcePath = notePath(memoryDir, file);
      const raw = fs.readFileSync(sourcePath, "utf8");
      const content = `[[curator-id:${file}]]\n${String(note.summary ?? "")}\n${raw}`;
      const vector = await embed(content, provider, dimensions);
      const timestamp = fs.statSync(sourcePath).mtime.toISOString();
      const ok = await store.upsertL1({
        id: file,
        content,
        type: typeFor(String(note.type ?? "project")),
        priority: note.risk === "high-if-wrong" ? 90 : 60,
        scene_name: String(note.domain ?? note.type ?? "memory"),
        source_message_ids: [],
        metadata: {},
        timestamps: [timestamp],
        createdAt: timestamp,
        updatedAt: timestamp,
        sessionKey: "curator-benchmark",
        sessionId: "curator-benchmark",
      }, vector);
      inserted += ok ? 1 : 0;
    }
    completed = true;
  } finally {
    store.close();
    if (!completed) {
      for (const suffix of ["", "-wal", "-shm"]) fs.rmSync(`${temporaryDb}${suffix}`, { force: true });
    }
  }
  const manifest = {
    upstream_tag: "v0.3.6",
    upstream_commit: "438869bec84711fb09b12185d46702d98eeaf90e",
    provider,
    model: provider === "openai" ? process.env.CURATOR_EMBEDDING_MODEL : provider,
    dimensions,
    corpus_hash: corpusHash(memoryDir, index),
    active_as_of: activeAsOf,
    inserted,
  };
  const temporaryManifest = `${dbPath}.manifest.json.${process.pid}.tmp`;
  fs.writeFileSync(temporaryManifest, `${JSON.stringify(manifest, null, 2)}\n`);
  fs.renameSync(temporaryDb, dbPath);
  fs.renameSync(temporaryManifest, `${dbPath}.manifest.json`);
  process.stdout.write(`${JSON.stringify(manifest)}\n`);
}

async function search(): Promise<void> {
  const sourceDir = required("source-dir");
  const memoryDir = required("memory-dir");
  const dbPath = required("db");
  const manifest = JSON.parse(fs.readFileSync(`${dbPath}.manifest.json`, "utf8")) as {
    provider: Provider; dimensions: number; corpus_hash: string; active_as_of: string;
  };
  const index = JSON.parse(fs.readFileSync(path.join(memoryDir, ".curator-index.json"), "utf8"));
  verifyCuratorIndex(memoryDir, index);
  if (corpusHash(memoryDir, index) !== manifest.corpus_hash) {
    throw new Error("TDAI search index is stale; rebuild it from Markdown truth");
  }
  if (manifest.active_as_of !== localDate()) {
    throw new Error("TDAI search index routing date is stale; rebuild it for today");
  }
  const input = JSON.parse(fs.readFileSync(0, "utf8")) as { query: string; k?: number; strategy?: Strategy };
  const requested = input.strategy ?? "hybrid";
  const k = input.k ?? 3;
  if (!["keyword", "vector", "hybrid"].includes(requested)) throw new Error(`invalid strategy: ${requested}`);
  if (!Number.isInteger(k) || k < 1 || k > 100) throw new Error(`invalid k: ${k}`);
  const candidateK = k * 3;
  const { store, buildFtsQuery } = await loadStore(sourceDir, dbPath, manifest.dimensions, manifest.provider);
  try {
    const ftsQuery = buildFtsQuery(input.query);
    const fts = ftsQuery ? await store.searchL1Fts(ftsQuery, candidateK) as Ranked[] : [];
    const queryVector = await embed(input.query, manifest.provider, manifest.dimensions);
    const vectors = queryVector ? await store.searchL1Vector(queryVector, candidateK) as Ranked[] : [];
    let used: Strategy = requested;
    let warning = "";
    if ((requested === "vector" || requested === "hybrid") && vectors.length === 0) {
      used = "keyword";
      warning = "no vector results; explicitly degraded to keyword";
    }
    const ranked = used === "keyword" ? fts : used === "vector" ? vectors : rrf(fts, vectors);
    process.stdout.write(`${JSON.stringify({
      strategy_requested: requested,
      strategy_used: used,
      warning,
      results: ranked.slice(0, k).map((row) => ({ file: row.record_id, score: row.score })),
    })}\n`);
  } finally {
    store.close();
  }
}

async function main(): Promise<void> {
  const command = process.argv[2];
  if (command === "index") await build();
  else if (command === "search") await search();
  else throw new Error("usage: tdai-v036-adapter.ts <index|search> [options]");
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
