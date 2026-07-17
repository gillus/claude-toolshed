import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
	inRange,
	isoDay,
	matchesSubject,
	toIsoDay,
	type Sessions,
} from "./argo.js";

const DAY = 86_400_000;
const GRADE_TYPES: Record<string, string> = {
	O: "orale",
	S: "scritto",
	P: "pratico",
};

const isoDayString = z
	.string()
	.regex(/^\d{4}-\d{2}-\d{2}$/, "Expected YYYY-MM-DD");

type ToolResult = {
	content: { type: "text"; text: string }[];
	isError?: boolean;
};

function json(data: unknown): ToolResult {
	return { content: [{ type: "text", text: JSON.stringify(data, null, 1) }] };
}

export function registerTools(server: McpServer, sessions: Sessions): void {
	const student = z
		.enum(sessions.names as [string, ...string[]])
		.describe("Which student to query");

	/** Register a tool, converting thrown errors into MCP error results. */
	const tool = (
		name: string,
		description: string,
		schema: z.ZodRawShape,
		handler: (args: any) => Promise<ToolResult>,
	) => {
		server.registerTool(name, { description, inputSchema: schema }, (async (
			args: unknown,
		) => {
			try {
				return await handler(args);
			} catch (error) {
				return {
					content: [{ type: "text" as const, text: `Error: ${error}` }],
					isError: true,
				};
			}
		}) as Parameters<typeof server.registerTool>[2]);
	};

	tool(
		"list_students",
		"List the configured students with their class, school and last data sync. Call this first to discover valid values for the `student` parameter.",
		{},
		async () => {
			const students = await Promise.all(
				sessions.names.map(async (name) => {
					const s = await sessions.get(name);
					const { alunno, scheda, anno } = s.profile;
					return {
						student: name,
						full_name: s.redactor.nameField(alunno.nominativo),
						class: `${scheda.classe.desDenominazione} ${scheda.classe.desSezione}`,
						course: scheda.corso.descrizione,
						school: scheda.scuola.descrizione,
						school_year: anno.anno,
						data_updated_at: s.dashboard.dataAggiornamento,
					};
				}),
			);
			return json(students);
		},
	);

	tool(
		"get_homework",
		"Get homework assignments with due dates, from the class register. Defaults to homework due between today and 14 days from now.",
		{
			student,
			due_from: isoDayString
				.optional()
				.describe("Earliest due date (YYYY-MM-DD, default today)"),
			due_to: isoDayString
				.optional()
				.describe("Latest due date (YYYY-MM-DD, default today + 14 days)"),
			subject: z
				.string()
				.optional()
				.describe("Filter by subject name (case-insensitive substring)"),
		},
		async ({ student: name, due_from, due_to, subject }) => {
			const s = await sessions.get(name);
			const r = s.redactor;
			const from = due_from ?? toIsoDay(new Date());
			const to = due_to ?? toIsoDay(new Date(Date.now() + 14 * DAY));
			const homework = s.dashboard.registro
				.filter((entry) => matchesSubject(entry.materia, subject))
				.flatMap((entry) =>
					entry.compiti.map((c) => ({
						due_date: isoDay(c.dataConsegna),
						subject: entry.materia,
						assignment: r.text(c.compito),
						assigned_on: isoDay(entry.datGiorno),
						teacher: r.nameField(entry.docente),
					})),
				)
				.filter((h) => inRange(h.due_date, from, to))
				.sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1));
			return json({ due_from: from, due_to: to, count: homework.length, homework });
		},
	);

	tool(
		"get_lesson_topics",
		"Get the topics covered in class (argomenti di lezione) from the register — what was actually taught, day by day. Useful for test preparation. Defaults to the last 30 days.",
		{
			student,
			from: isoDayString
				.optional()
				.describe("Earliest lesson date (YYYY-MM-DD, default today - 30 days)"),
			to: isoDayString.optional().describe("Latest lesson date (YYYY-MM-DD)"),
			subject: z
				.string()
				.optional()
				.describe("Filter by subject name (case-insensitive substring)"),
		},
		async ({ student: name, from, to, subject }) => {
			const s = await sessions.get(name);
			const r = s.redactor;
			const fromDay = from ?? toIsoDay(new Date(Date.now() - 30 * DAY));
			const topics = s.dashboard.registro
				.map((entry) => ({
					date: isoDay(entry.datGiorno),
					hour: entry.ora,
					subject: entry.materia,
					teacher: r.nameField(entry.docente),
					topic: r.text(entry.attivita),
				}))
				.filter(
					(t) =>
						t.topic &&
						inRange(t.date, fromDay, to) &&
						matchesSubject(t.subject, subject),
				)
				.sort((a, b) => (a.date! < b.date! ? -1 : 1));
			return json({ from: fromDay, to: to ?? null, count: topics.length, topics });
		},
	);

	tool(
		"get_grades",
		"Get grades (voti), most recent first. Includes the test description, teacher comment and whether the grade counts toward the average.",
		{
			student,
			from: isoDayString.optional().describe("Only grades on/after this date"),
			subject: z
				.string()
				.optional()
				.describe("Filter by subject name (case-insensitive substring)"),
			limit: z.number().int().positive().max(200).optional()
				.describe("Max results (default 30)"),
		},
		async ({ student: name, from, subject, limit }) => {
			const s = await sessions.get(name);
			const r = s.redactor;
			const grades = s.dashboard.voti
				.map((v) => ({
					date: isoDay(v.datGiorno),
					subject: v.desMateria,
					grade: v.codCodice,
					value: v.valore,
					type: GRADE_TYPES[v.codTipo] ?? v.codTipo,
					test_description: r.text(v.descrizioneProva),
					teacher_comment: r.text(v.desCommento),
					teacher: r.nameField(v.docente),
					counts_toward_average: v.numMedia > 0,
				}))
				.filter(
					(g) => inRange(g.date, from) && matchesSubject(g.subject, subject),
				)
				.sort((a, b) => (a.date! > b.date! ? -1 : 1))
				.slice(0, limit ?? 30);
			return json({ count: grades.length, grades });
		},
	);

	tool(
		"get_averages",
		"Get computed grade averages: overall, per subject (with written/oral split) and per month. Useful for spotting trends.",
		{ student },
		async ({ student: name }) => {
			const s = await sessions.get(name);
			const d = s.dashboard;
			const subjectNames = new Map(
				d.listaMaterie.map((m) => [m.pk, m.materia]),
			);
			const perSubject = (
				Object.entries(d.mediaMaterie ?? {}) as [
					string,
					Record<string, number>,
				][]
			)
				.filter(([, v]) => v && typeof v === "object" && "numVoti" in v)
				.map(([pk, v]) => ({
					subject: subjectNames.get(pk) ?? pk,
					average: v.mediaMateria,
					written_average: v.mediaScritta || null,
					oral_average: v.mediaOrale || null,
					grade_count: v.numVoti,
				}));
			return json({
				overall_average: d.mediaGenerale,
				per_month: d.mediaPerMese ?? null,
				per_subject: perSubject,
			});
		},
	);

	tool(
		"get_notices",
		"Get school notices (bacheca): circolari, communications, events. Flags which ones still require parent acknowledgement (presa visione) or consent (adesione), with deadlines.",
		{
			student,
			action_required_only: z
				.boolean()
				.optional()
				.describe("Only notices still awaiting acknowledgement or consent"),
			from: isoDayString.optional().describe("Only notices on/after this date"),
			limit: z.number().int().positive().max(200).optional()
				.describe("Max results (default 20)"),
		},
		async ({ student: name, action_required_only, from, limit }) => {
			const s = await sessions.get(name);
			const r = s.redactor;
			const notices = s.dashboard.bacheca
				.map((n) => ({
					date: isoDay(n.data),
					category: n.categoria,
					author: r.text(n.autore),
					message: r.text(n.messaggio),
					url: n.url,
					expires: isoDay(n.dataScadenza),
					needs_acknowledgement: n.pvRichiesta && !n.isPresaVisione,
					needs_consent: n.adRichiesta && !n.isPresaAdesioneConfermata,
					consent_deadline: isoDay(n.dataScadAdesione),
					attachments: n.listaAllegati?.map((a) => ({
						file: r.text(a.nomeFile),
						uid: a.pk,
					})),
				}))
				.filter(
					(n) =>
						inRange(n.date, from) &&
						(!action_required_only ||
							n.needs_acknowledgement ||
							n.needs_consent),
				)
				.sort((a, b) => (a.date! > b.date! ? -1 : 1))
				.slice(0, limit ?? 20);
			return json({ count: notices.length, notices });
		},
	);

	tool(
		"get_absences",
		"Get absences, late arrivals and early exits (registro assenze), including which ones still need to be justified by a parent.",
		{
			student,
			pending_only: z
				.boolean()
				.optional()
				.describe("Only events that still need justification"),
		},
		async ({ student: name, pending_only }) => {
			const s = await sessions.get(name);
			const r = s.redactor;
			const events = s.dashboard.appello
				.map((e) => ({
					date: isoDay(e.data),
					type: e.descrizione,
					code: e.codEvento,
					teacher: r.nameField(e.docente),
					note: r.text(e.nota),
					needs_justification: e.daGiustificare && e.giustificata !== "S",
					justified_on: isoDay(e.dataGiustificazione),
					justification_comment: r.text(e.commentoGiustificazione),
				}))
				.filter((e) => !pending_only || e.needs_justification)
				.sort((a, b) => (a.date! > b.date! ? -1 : 1));
			return json({ count: events.length, events });
		},
	);

	tool(
		"get_timetable",
		"Get the timetable (orario) for a specific day: hours, subjects and teachers.",
		{
			student,
			date: isoDayString
				.optional()
				.describe("Day to fetch (YYYY-MM-DD, default today)"),
		},
		async ({ student: name, date }) => {
			const s = await sessions.get(name);
			const day = date ? new Date(date) : new Date();
			const entries = await s.getTimetable({
				year: day.getFullYear(),
				month: day.getMonth() + 1,
				day: day.getDate(),
			});
			const timetable = entries
				.filter((e) => e.mostra)
				.map((e) => ({
					hour: e.numOra,
					subject: e.materia,
					teacher: s.redactor.nameField(
						e.docente || `${e.desNome} ${e.desCognome}`.trim(),
					),
				}))
				.sort((a, b) => a.hour - b.hour);
			return json({ date: toIsoDay(day), timetable });
		},
	);

	tool(
		"get_teachers",
		"List the class teachers with their subjects and email addresses.",
		{ student },
		async ({ student: name }) => {
			const s = await sessions.get(name);
			const r = s.redactor;
			const teachers = s.dashboard.listaDocentiClasse.map((t) => ({
				name: r.nameField(`${t.desNome} ${t.desCognome}`),
				subjects: t.materie,
				email: r.email(t.desEmail),
			}));
			return json(teachers);
		},
	);

	tool(
		"get_reminders",
		"Get teacher reminders/announcements (promemoria) such as scheduled tests or planned activities.",
		{ student },
		async ({ student: name }) => {
			const s = await sessions.get(name);
			const r = s.redactor;
			const reminders = s.dashboard.promemoria
				.map((p) => ({
					date: isoDay(p.datGiorno),
					teacher: r.nameField(p.docente),
					note: r.text(p.desAnnotazioni),
					time: p.oraInizio ? `${p.oraInizio}-${p.oraFine}` : null,
				}))
				.sort((a, b) => (a.date! > b.date! ? -1 : 1));
			return json({ count: reminders.length, reminders });
		},
	);

	tool(
		"get_fees",
		"Get school fees/payments (tasse scolastiche) with amounts, deadlines and payment status.",
		{ student },
		async ({ student: name }) => {
			const s = await sessions.get(name);
			const { tasse, isPagOnlineAttivo } = await s.getFees();
			const fees = tasse.map((t) => ({
				description: s.redactor.text(t.descrizione),
				amount: t.importoTassa,
				due_date: isoDay(t.scadenza),
				status: t.stato,
				paid_amount: t.importoPagato,
				paid_on: isoDay(t.dataPagamento),
				installment: t.rata,
			}));
			return json({ online_payment_available: isPagOnlineAttivo, fees });
		},
	);

	tool(
		"get_attachment_link",
		"Get a temporary download URL for a notice attachment. Use the `uid` returned by get_notices.",
		{
			student,
			uid: z.string().describe("Attachment uid from get_notices"),
			student_board: z
				.boolean()
				.optional()
				.describe("True if the attachment comes from the student board (bacheca alunno)"),
		},
		async ({ student: name, uid, student_board }) => {
			const s = await sessions.get(name);
			const url = await s.getAttachmentLink(uid, student_board ?? false);
			return json({ url });
		},
	);
}
