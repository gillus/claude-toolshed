/**
 * Optional name redaction (ARGO_REDACT_NAMES=true): replaces student and
 * teacher names with initials ("ROSSI MARIA" → "R.M.") in every tool result,
 * so real names never enter the conversation.
 *
 * Structured name fields are always reduced to initials, even for people not
 * seen before (e.g. substitute teachers in the timetable). Free-text fields
 * are scrubbed best-effort against the known-names corpus (the student's own
 * name plus every teacher appearing in the dashboard) — names the server has
 * never seen cannot be caught there.
 */

export interface Redactor {
	/** A field that IS a person's name (e.g. `docente`) → initials. */
	nameField(value: string | null | undefined): string | null;
	/** Free text that may CONTAIN names → known names replaced by initials. */
	text(value: string | null | undefined): string | null;
	/** Email addresses encode the name, so they are dropped when redacting. */
	email(value: string | null | undefined): string | null;
}

/** No-op redactor used when ARGO_REDACT_NAMES is off. */
export const PASSTHROUGH: Redactor = {
	nameField: (v) => v || null,
	text: (v) => v || null,
	email: (v) => v || null,
};

/** Honorifics and their split fragments ("Prof.ssa" → "prof" + "ssa"). */
const TITLE_WORDS = new Set([
	"prof",
	"ssa",
	"re",
	"professore",
	"professoressa",
	"dott",
	"dottssa",
	"sig",
	"sigra",
	"maestro",
	"maestra",
]);

/** Split a raw name string into name tokens, dropping titles and punctuation. */
function nameTokens(raw: string): string[] {
	return raw
		.split(/[^\p{L}']+/u)
		.filter(Boolean)
		.filter((t) => !TITLE_WORDS.has(t.toLowerCase()));
}

function initialsOf(tokens: string[]): string {
	return tokens.map((t) => `${t[0].toUpperCase()}.`).join("");
}

function escapeRegExp(s: string): string {
	return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Word-boundary alternation that works with accented letters (JS \b is ASCII-only). */
function wordPattern(alternatives: string[]): RegExp {
	const body = alternatives.map(escapeRegExp).join("|");
	return new RegExp(`(?<![\\p{L}\\p{N}])(?:${body})(?![\\p{L}\\p{N}])`, "giu");
}

type Person = {
	tokens: string[];
	/** Order-insensitive identity, to dedupe "Rossi Maria" vs "Maria Rossi". */
	key: string;
	initials: string;
};

/**
 * Build a redactor from raw name strings (the student's nominativo, roster
 * teachers, `docente` strings from register/grades/absences/reminders).
 * Initials are made unique with a numeric suffix on collisions, assigned in
 * sorted-name order so they stay stable across syncs.
 */
export function buildRedactor(rawNames: string[]): Redactor {
	const byKey = new Map<string, Person>();
	for (const raw of rawNames) {
		const tokens = nameTokens(raw);
		if (tokens.length === 0) continue;
		const key = tokens
			.map((t) => t.toLowerCase())
			.sort()
			.join(" ");
		if (!byKey.has(key)) byKey.set(key, { tokens, key, initials: "" });
	}
	const persons = [...byKey.values()].sort((a, b) =>
		a.key < b.key ? -1 : 1,
	);
	const used = new Map<string, number>();
	for (const p of persons) {
		const base = initialsOf(p.tokens);
		const n = (used.get(base) ?? 0) + 1;
		used.set(base, n);
		p.initials = n === 1 ? base : `${base}${n}`;
	}

	// Full-name sequences (given and reversed order) beat single tokens.
	const fullPatterns = persons.map((p) => {
		const escaped = p.tokens.map(escapeRegExp);
		const seqs = [escaped.join("\\s+")];
		if (escaped.length > 1) seqs.push([...escaped].reverse().join("\\s+"));
		return {
			pattern: new RegExp(
				`(?<![\\p{L}\\p{N}])(?:${seqs.join("|")})(?![\\p{L}\\p{N}])`,
				"giu",
			),
			initials: p.initials,
		};
	});

	// Lone tokens: skip short particles ("De", "Di", "La") to avoid mangling
	// ordinary Italian words; over-matching a real word is accepted collateral.
	const owners = new Map<string, Person[]>();
	for (const p of persons)
		for (const t of p.tokens) {
			if (t.length < 3) continue;
			const k = t.toLowerCase();
			const list = owners.get(k) ?? [];
			if (!list.includes(p)) list.push(p);
			owners.set(k, list);
		}
	const tokenPattern =
		owners.size > 0 ? wordPattern([...owners.keys()]) : null;

	const findPerson = (tokens: string[]): Person | undefined =>
		byKey.get(
			tokens
				.map((t) => t.toLowerCase())
				.sort()
				.join(" "),
		);

	return {
		nameField(value) {
			if (!value) return null;
			const tokens = nameTokens(value);
			if (tokens.length === 0) return null;
			return findPerson(tokens)?.initials ?? initialsOf(tokens);
		},
		text(value) {
			if (!value) return null;
			let out = value;
			for (const { pattern, initials } of fullPatterns)
				out = out.replace(pattern, initials);
			if (tokenPattern)
				out = out.replace(tokenPattern, (match) => {
					const list = owners.get(match.toLowerCase()) ?? [];
					// Ambiguous token (shared first name): redact without attributing.
					return list.length === 1
						? list[0].initials
						: `${match[0].toUpperCase()}.`;
				});
			return out;
		},
		email() {
			return null;
		},
	};
}
