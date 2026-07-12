import { existsSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";

export type StudentConfig = {
	/** Short identifier used as the `student` parameter in tools (e.g. "marco") */
	name: string;
	schoolCode: string;
	username: string;
	password: string;
};

export type Config = {
	students: StudentConfig[];
	/** Minutes between dashboard re-syncs */
	syncTtlMinutes: number;
	/** Directory where per-student Argo session data is persisted */
	dataDir: string;
	projectRoot: string;
};

export function loadConfig(projectRoot: string): Config {
	const envFile = join(projectRoot, ".env");
	if (existsSync(envFile)) process.loadEnvFile(envFile);

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
			return { name, schoolCode, username, password };
		});

	if (students.length === 0)
		throw new Error("ARGO_STUDENTS is empty — configure at least one student");

	return {
		students,
		syncTtlMinutes: Number(process.env.ARGO_SYNC_TTL_MINUTES) || 10,
		dataDir: join(projectRoot, ".argo-data"),
		projectRoot,
	};
}
