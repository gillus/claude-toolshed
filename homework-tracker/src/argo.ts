import { Client, type Dashboard } from "portaleargo-api";
import { join } from "node:path";
import type { Config, StudentConfig } from "./config.js";

/**
 * Wraps a portaleargo-api Client for one student: lazy login, periodic
 * incremental re-sync, and typed access to the dashboard.
 */
export class StudentSession {
	readonly name: string;
	private readonly client: Client;
	private lastSync = 0;
	private readonly ttlMs: number;
	private pending: Promise<void> | null = null;

	constructor(cfg: StudentConfig, config: Config) {
		this.name = cfg.name;
		this.ttlMs = config.syncTtlMinutes * 60_000;
		this.client = new Client({
			schoolCode: cfg.schoolCode,
			username: cfg.username,
			password: cfg.password,
			dataPath: join(config.dataDir, cfg.name),
		});
	}

	/**
	 * Ensure the client is logged in and the dashboard is fresh.
	 * Repeated calls within the TTL are no-ops; calls during an in-flight
	 * sync await that same sync instead of starting another.
	 */
	async sync(force = false): Promise<void> {
		if (this.pending) return this.pending;
		if (!force && Date.now() - this.lastSync < this.ttlMs) return;
		const pending = this.client
			.login()
			.then(() => {
				this.lastSync = Date.now();
			})
			.finally(() => {
				this.pending = null;
			});
		this.pending = pending;
		return pending;
	}

	get dashboard(): Dashboard {
		if (!this.client.dashboard)
			throw new Error(`Dashboard not loaded for "${this.name}" — sync failed?`);
		return this.client.dashboard;
	}

	get profile() {
		if (!this.client.profile)
			throw new Error(`Profile not loaded for "${this.name}" — sync failed?`);
		return this.client.profile;
	}

	getTimetable(date?: { year: number; month: number; day: number }) {
		return this.client.getOrarioGiornaliero(date);
	}

	getFees() {
		return this.client.getTasse();
	}

	getAttachmentLink(uid: string, studentBoard: boolean) {
		return studentBoard
			? this.client.getLinkAllegatoStudente(uid)
			: this.client.getLinkAllegato(uid);
	}
}

export class Sessions {
	private readonly map = new Map<string, StudentSession>();

	constructor(config: Config) {
		for (const s of config.students)
			this.map.set(s.name, new StudentSession(s, config));
	}

	get names(): string[] {
		return [...this.map.keys()];
	}

	/** Get a session and make sure it is synced before returning it. */
	async get(name: string): Promise<StudentSession> {
		const session = this.map.get(name);
		if (!session)
			throw new Error(
				`Unknown student "${name}". Configured students: ${this.names.join(", ")}`,
			);
		await session.sync();
		return session;
	}
}

/**
 * Parse the date formats Argo uses ("YYYY-MM-DD", "YYYY-MM-DD HH:mm:ss",
 * "DD/MM/YYYY"). Returns null for empty/invalid values.
 */
export function parseArgoDate(value: string | null | undefined): Date | null {
	if (!value) return null;
	const it = /^(\d{2})\/(\d{2})\/(\d{4})/.exec(value);
	if (it) return new Date(`${it[3]}-${it[2]}-${it[1]}`);
	const iso = new Date(value.replace(" ", "T"));
	return Number.isNaN(iso.getTime()) ? null : iso;
}

/** Format a Date as YYYY-MM-DD (local time). */
export function toIsoDay(date: Date): string {
	const m = `${date.getMonth() + 1}`.padStart(2, "0");
	const d = `${date.getDate()}`.padStart(2, "0");
	return `${date.getFullYear()}-${m}-${d}`;
}

/** Normalize an Argo date string to YYYY-MM-DD, or null. */
export function isoDay(value: string | null | undefined): string | null {
	const d = parseArgoDate(value);
	return d ? toIsoDay(d) : null;
}

/** Inclusive YYYY-MM-DD range check; open-ended when from/to are omitted. */
export function inRange(
	day: string | null,
	from?: string,
	to?: string,
): boolean {
	if (!day) return false;
	if (from && day < from) return false;
	if (to && day > to) return false;
	return true;
}

export function matchesSubject(
	subject: string | null | undefined,
	query?: string,
): boolean {
	if (!query) return true;
	return (subject ?? "").toLowerCase().includes(query.toLowerCase());
}
