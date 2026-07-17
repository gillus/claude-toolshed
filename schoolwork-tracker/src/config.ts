import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";

/** Load a .env file; falls back to a manual parse on Node < 20.12
 * (no process.loadEnvFile), e.g. the native-Windows Node run by Claude Desktop. */
function loadEnvFile(path: string): void {
	if (typeof process.loadEnvFile === "function") {
		process.loadEnvFile(path);
		return;
	}
	for (const line of readFileSync(path, "utf8").split("\n")) {
		const m = /^\s*(?:export\s+)?([\w.]+)\s*=\s*(.*?)\s*$/.exec(line);
		if (!m) continue;
		const value = m[2].replace(/^(['"])(.*)\1$/, "$2");
		if (!(m[1] in process.env)) process.env[m[1]] = value;
	}
}

export type StudentConfig = {
	/** Short identifier used as the `student` parameter in tools (e.g. "marco") */
	name: string;
	schoolCode: string;
	username: string;
	password: string;
	/**
	 * Case-insensitive substring of the child's full name (Argo "nominativo").
	 * Required to pick the right profile when one parent account covers
	 * multiple children — Argo returns all of them and the API library
	 * otherwise always binds to the first.
	 */
	studentName?: string;
};

export type Config = {
	students: StudentConfig[];
	/** Minutes between dashboard re-syncs */
	syncTtlMinutes: number;
	/** Replace student/teacher names with initials in all tool output */
	redactNames: boolean;
	/** Directory where per-student Argo session data is persisted */
	dataDir: string;
	projectRoot: string;
};

export function loadConfig(projectRoot: string): Config {
	const envFile = join(projectRoot, ".env");
	if (existsSync(envFile)) loadEnvFile(envFile);

	const list = process.env.ARGO_STUDENTS;
	if (!list)
		throw new Error(
			"ARGO_STUDENTS is not set. Copy .env.example to .env and fill in your credentials.",
		);

	const students = list
		.split(",")
		.map((s) => s.trim().toLowerCase())
		.filter(Boolean)
		.map((name): StudentConfig => {
			const prefix = `ARGO_${name.toUpperCase()}_`;
			const schoolCode = process.env[`${prefix}SCHOOL_CODE`];
			const username = process.env[`${prefix}USERNAME`];
			const password = process.env[`${prefix}PASSWORD`];
			if (!schoolCode || !username || !password)
				throw new Error(
					`Missing credentials for student "${name}": expected ${prefix}SCHOOL_CODE, ${prefix}USERNAME and ${prefix}PASSWORD`,
				);
			return {
				name,
				schoolCode,
				username,
				password,
				studentName: process.env[`${prefix}STUDENT_NAME`],
			};
		});

	if (students.length === 0)
		throw new Error("ARGO_STUDENTS is empty — configure at least one student");

	// portaleargo-api mkdirs its per-student subdir non-recursively.
	const dataDir = join(projectRoot, ".argo-data");
	mkdirSync(dataDir, { recursive: true });

	return {
		students,
		syncTtlMinutes: Number(process.env.ARGO_SYNC_TTL_MINUTES) || 10,
		redactNames: /^(1|true|yes|on)$/i.test(
			process.env.ARGO_REDACT_NAMES ?? "",
		),
		dataDir,
		projectRoot,
	};
}
