/**
 * Superlite plugin for Oh My Pi (omp).
 *
 * Mirrors the Pi extension: load `using-superlite` at session start, after a
 * compaction, and for every subagent session, together with the omp tool
 * mapping. No external dependencies - plain ESM.
 *
 * Install shape (see README, "Oh My Pi"):
 *   extensions: [<checkout>]   in ~/.omp/agent/config.yml
 * The package manifest declares this file under `omp.extensions`, so omp also
 * discovers `skills/` (omp-plugins provider) and `agents/` (task agents).
 */

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const BOOTSTRAP_MARKER = "superlite:using-superlite bootstrap for omp";

const extensionDir = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(extensionDir, "../..");
const bootstrapSkillPath = resolve(packageRoot, "skills/using-superlite/SKILL.md");
const toolMappingPath = resolve(packageRoot, "skills/using-superlite/references/omp-tools.md");

/** cwd -> bootstrap text (the project-state hint is the only per-project part) */
const bootstrapByCwd = new Map();

export default function superliteOmpExtension(pi) {
	pi.setLabel("Superlite");

	pi.on("context", (event, ctx) => {
		const messages = event.messages;
		if (!Array.isArray(messages) || messages.some(messageContainsBootstrap)) return;
		const bootstrap = getBootstrapContent(ctx.cwd);
		if (!bootstrap) return;
		const insertAt = firstNonCompactionSummaryIndex(messages);
		return {
			messages: [
				...messages.slice(0, insertAt),
				{ role: "user", content: [{ type: "text", text: bootstrap }], timestamp: Date.now() },
				...messages.slice(insertAt),
			],
		};
	});
}

function getBootstrapContent(cwd) {
	const key = typeof cwd === "string" ? cwd : "";
	if (bootstrapByCwd.has(key)) return bootstrapByCwd.get(key);

	let text = null;
	try {
		const body = stripFrontmatter(readFileSync(bootstrapSkillPath, "utf8"));
		const mapping = stripFrontmatter(readFileSync(toolMappingPath, "utf8"));
		text = [
			BOOTSTRAP_MARKER,
			"",
			"You have superlite. Its 'superlite:using-superlite' skill follows and is already loaded for this omp session. Follow it now. Do not try to load using-superlite again.",
			"",
			body,
			"",
			mapping,
			"",
			`Plugin root: ${packageRoot}`,
			`Project state: ${projectState(key)}.`,
		].join("\n");
	} catch {
		text = null;
	}

	bootstrapByCwd.set(key, text);
	return text;
}

function stripFrontmatter(content) {
	const match = content.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n?([\s\S]*)$/);
	return (match ? match[1] : content).trim();
}

function projectState(cwd) {
	if (!cwd) return "unknown";
	const stateDir = resolve(cwd, ".superlite");
	if (existsSync(resolve(stateDir, "orchestrator.json")) && existsSync(resolve(cwd, "docs/plans"))) {
		if (existsSync(resolve(stateDir, "stable.json"))) return "run in progress";
	}
	if (existsSync(resolve(cwd, ".git"))) return "existing code";
	try {
		return readdirSync(cwd).length > 0 ? "existing code" : "empty folder";
	} catch {
		return "unknown";
	}
}

function messageContainsBootstrap(message) {
	if (!message || typeof message !== "object") return false;
	const content = message.content;
	if (typeof content === "string") return content.includes(BOOTSTRAP_MARKER);
	if (!Array.isArray(content)) return false;
	return content.some(
		(part) =>
			part &&
			typeof part === "object" &&
			part.type === "text" &&
			typeof part.text === "string" &&
			part.text.includes(BOOTSTRAP_MARKER),
	);
}

function firstNonCompactionSummaryIndex(messages) {
	let index = 0;
	while (messages[index]?.role === "compactionSummary") index += 1;
	return index;
}
