import { Client, randomString, type Dashboard } from "portaleargo-api";
import { rm } from "node:fs/promises";
import { join } from "node:path";
import type { Config, StudentConfig } from "./config.js";
import { buildRedactor, PASSTHROUGH, type Redactor } from "./redact.js";

/**
 * Client that binds to a specific child on multi-child parent accounts.
 *
 * Argo's /login returns one profile per child, but the library's private
 * getLoginData() always keeps the first (`login.data[0]`), so every student
 * configured with the same parent credentials would silently get the same
 * kid's register. This subclass replaces getLoginData (private only at
 * compile time) with a version that probes each profile's /profilo and keeps
 * the one whose child name matches `studentName`.
 */
class ProfileSelectingClient extends Client {
	constructor(
		options: ConstructorParameters<typeof Client>[0],
		studentName?: string,
	) {
		super(options);
		const self = this as any;
		// Instance property shadows the base prototype method; TS disallows
		// overriding a `private` member with normal class syntax.
		self.getLoginData = async () => {
			const login = await self.apiRequest("login", {
				body: {
					"lista-opzioni-notifiche": "{}",
					"lista-x-auth-token": "[]",
					clientID: randomString(163),
				},
			});
			if (!login.success) throw new Error(login.msg);
			const profiles: any[] = login.data;
			let chosen = profiles[0];
			if (profiles.length > 1 || studentName) {
				const found: string[] = [];
				chosen = undefined;
				for (const p of profiles) {
					self.loginData = p; // apiRequest takes x-auth-token/x-cod-min from here
					const profilo = await self.apiRequest("profilo");
					const child: string = profilo.data?.alunno?.nominativo ?? "";
					found.push(child);
					if (
						studentName &&
						child.toLowerCase().includes(studentName.toLowerCase())
					) {
						chosen = p;
						break;
					}
				}
				if (!chosen) {
					self.loginData = undefined;
					throw new Error(
						studentName
							? `No Argo profile matches STUDENT_NAME "${studentName}". ` +
								`This account's children: ${found.join(", ")}`
							: `This Argo account has ${profiles.length} children (${found.join(", ")}). ` +
								`Set ARGO_<NAME>_STUDENT_NAME to pick one per student.`,
					);
				}
			}
			self.loginData = Object.assign({}, chosen);
			void self.dataProvider?.write("login", self.loginData);
			return self.loginData;
		};
	}
}

/**
 * Wraps a portaleargo-api Client for one student: lazy login, periodic
 * incremental re-sync, and typed access to the dashboard.
 */
export class StudentSession {
	readonly name: string;
	private readonly client: Client;
	private readonly dataPath: string;
	private lastSync = 0;
	private readonly ttlMs: number;
	private pending: Promise<void> | null = null;
	private readonly redactNames: boolean;
	private redactorCache: { syncedAt: number; redactor: Redactor } | null =
		null;

	constructor(cfg: StudentConfig, config: Config) {
		this.name = cfg.name;
		this.ttlMs = config.syncTtlMinutes * 60_000;
		this.redactNames = config.redactNames;
		this.dataPath = join(config.dataDir, cfg.name);
		this.client = new ProfileSelectingClient(
			{
				schoolCode: cfg.schoolCode,
				username: cfg.username,
				password: cfg.password,
				dataPath: this.dataPath,
			},
			cfg.studentName,
		);
	}

	/**
	 * Drop all cached auth so the next login() does a full username/password
	 * re-authentication instead of trying to refresh a token.
	 *
	 * portaleargo-api has no fallback when a persisted refresh token is dead:
	 * its refreshToken() calls `res.json()` on an empty body and throws
	 * "Unexpected end of JSON input" on every request. Clearing both the
	 * on-disk files AND the in-memory copies (loadData() won't re-read a field
	 * the client already holds) forces getToken() via a fresh login.
	 */
	private async resetAuth(): Promise<void> {
		const c = this.client as any;
		c.token = undefined;
		c.loginData = undefined;
		c.profile = undefined;
		c.dashboard = undefined;
		// Delete the cache files but leave the directory itself in place: the
		// library's data provider captures whether the dir exists once, at
		// construction, and mkdirs it non-recursively on first write. Removing
		// or recreating the dir desyncs that flag (→ ENOENT/EEXIST on the next
		// write); deleting only the files keeps a fresh login persistable.
		await Promise.all(
			["token", "login", "profile", "dashboard"].map((name) =>
				rm(join(this.dataPath, `${name}.json`), { force: true }),
			),
		);
	}

	/**
	 * Ensure the client is logged in and the dashboard is fresh.
	 * Repeated calls within the TTL are no-ops; calls during an in-flight
	 * sync await that same sync instead of starting another.
	 */
	async sync(force = false): Promise<void> {
		if (this.pending) return this.pending;
		if (!force && Date.now() - this.lastSync < this.ttlMs) return;
		const pending = this.loginWithRecovery()
			.then(() => {
				this.lastSync = Date.now();
			})
			.finally(() => {
				this.pending = null;
			});
		this.pending = pending;
		return pending;
	}

	/**
	 * Log in, and if it fails on stale cached auth (dead refresh token →
	 * "Unexpected end of JSON input", or an explicit token error), wipe the
	 * cache once and retry with a full re-login. Non-auth failures (bad
	 * credentials, network) surface on the retry as-is.
	 */
	private async loginWithRecovery(): Promise<void> {
		try {
			await this.client.login();
		} catch (err) {
			console.error(
				`[${this.name}] login failed (${(err as Error).message}); ` +
					`clearing cached auth and retrying with a fresh login`,
			);
			await this.resetAuth();
			await this.client.login();
		}
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

	/**
	 * Redactor for this student's data, rebuilt after each sync from every
	 * name the dashboard exposes (the child plus roster/register teachers).
	 * A shared no-op instance when ARGO_REDACT_NAMES is off.
	 */
	get redactor(): Redactor {
		if (!this.redactNames) return PASSTHROUGH;
		if (this.redactorCache?.syncedAt !== this.lastSync) {
			const d = this.dashboard;
			const names = [
				this.profile.alunno.nominativo,
				...d.listaDocentiClasse.map((t) => `${t.desCognome} ${t.desNome}`),
				...d.registro.map((e) => e.docente),
				...d.voti.map((v) => v.docente),
				...d.appello.map((e) => e.docente),
				...d.promemoria.map((p) => p.docente),
			].filter((n): n is string => Boolean(n));
			this.redactorCache = {
				syncedAt: this.lastSync,
				redactor: buildRedactor(names),
			};
		}
		return this.redactorCache.redactor;
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
