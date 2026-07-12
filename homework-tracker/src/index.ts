#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Sessions } from "./argo.js";
import { loadConfig } from "./config.js";
import { registerTools } from "./tools.js";

// This file lives in src/ (tsx) or dist/ (compiled) — the project root is one up.
const projectRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

async function main() {
	const config = loadConfig(projectRoot);
	const sessions = new Sessions(config);

	const server = new McpServer({
		name: "school-mcp",
		version: "0.1.0",
	});
	registerTools(server, sessions);

	// stdout is reserved for the MCP protocol — all logging goes to stderr.
	console.error(
		`school-mcp: serving students [${sessions.names.join(", ")}] over stdio`,
	);
	await server.connect(new StdioServerTransport());
}

main().catch((error) => {
	console.error("school-mcp fatal:", error);
	process.exit(1);
});
