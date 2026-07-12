/**
 * Standalone credential check: logs into Argo for every configured student
 * and prints a summary of the data available. Run with `npm run check-login`.
 */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Sessions } from "./argo.js";
import { loadConfig } from "./config.js";

const projectRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const config = loadConfig(projectRoot);
const sessions = new Sessions(config);

for (const name of sessions.names) {
	process.stdout.write(`→ ${name}: logging in... `);
	try {
		const s = await sessions.get(name);
		const { alunno, scheda } = s.profile;
		const d = s.dashboard;
		const homework = d.registro.reduce((n, r) => n + r.compiti.length, 0);
		console.log("OK");
		console.log(`   ${alunno.nominativo} — ${scheda.classe.desDenominazione}${scheda.classe.desSezione}, ${scheda.scuola.descrizione}`);
		console.log(
			`   grades: ${d.voti.length}, register entries: ${d.registro.length} (${homework} homework), notices: ${d.bacheca.length}, absences: ${d.appello.length}`,
		);
		console.log(`   last update: ${d.dataAggiornamento.toISOString()}`);
	} catch (error) {
		console.log("FAILED");
		console.error(`   ${error}`);
		process.exitCode = 1;
	}
}
