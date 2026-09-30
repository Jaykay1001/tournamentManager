/* All data stays on the local server. No remote assets or browser storage as source of truth. */
"use strict";
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let current = {revision: 0, tournament: null}, loaded = false, dirty = false, busy = false;
let filterTeam = "", filterSetup = "", filterPhase = "", toastTimer;
const modal = $("#modal");
const phaseNames = {group:"Group stage", quarterfinal:"Quarterfinals", semifinal:"Semifinals", final:"Final"};
const team = id => current.tournament?.teams.find(t => t.id === id);
const name = id => team(id)?.name || "To be decided";
const initials = id => name(id).split(/\s+/).map(s => s[0]).join("").slice(0,2).toUpperCase();
const page = () => location.hash.slice(1).split("/")[0] || "dashboard";
const time = iso => iso ? new Intl.DateTimeFormat("en-GB", {hour:"2-digit",minute:"2-digit",timeZone:current.tournament?.settings.timezone || "Europe/Berlin"}).format(new Date(iso)) : "Time TBD";
const longTime = iso => new Date(iso).toLocaleString("en-GB", {timeZone:current.tournament?.settings.timezone || "Europe/Berlin",dateStyle:"medium",timeStyle:"short"});
const selected = (a,b) => a === b ? " selected" : "";
const gameById = id => current.tournament.games.find(g => g.id === id);
const uuid = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2,"0")).join("");

function toast(message) { $("#toast").textContent = message; $("#toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $("#toast").hidden = true, 4500); }
function status(online) { const el = $("#connection"); el.classList.toggle("offline", !online); el.textContent = online ? `● Connected · updated ${new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"})}` : "● Disconnected · retrying · changes are not saved offline"; }
function heading(title, subtitle, action = "") { return `<div class="page-heading"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${action}</div>`; }
function badge(g) { const label = g.status === "ongoing" ? "Live" : g.status === "completed" ? "Final" : g.status === "not_needed" ? "Not needed" : g.paused ? "Paused" : g.ready ? "Ready" : g.if_needed ? "If needed" : "Scheduled"; return `<span class="badge ${g.status === "ongoing" ? "live" : g.status === "completed" ? "completed" : ""}">${label}</span>`; }
function teamRow(g, side) { const t = team(g[side]); return `<div class="match-row"><span class="team-icon ${t?.group === "B" ? "b" : ""}">${t ? esc(initials(t.id)) : "—"}</span><div class="team-info"><strong>${esc(name(g[side]))}<span class="home-label">${side === "home" ? "HOME" : "AWAY"}</span></strong><small>${t ? esc(t.players.join(" · ")) : esc(sourceLabel(g, side))}</small></div><span class="score">${g[side+"_score"] ?? "—"}</span></div>`; }
function sourceLabel(g, side) { if (g.phase === "quarterfinal") { const n = Number(g.id.slice(2)); const a = `Group A #${n}`, b = `Group B #${5-n}`; return side === "home" ? (n <= 2 ? a : b) : (n <= 2 ? b : a); } if (g.series === "SF1") return "Winners of QF1 & QF2"; if (g.series === "SF2") return "Winners of QF3 & QF4"; if (g.series === "F") return "Semifinal winners"; return ""; }
function estimateLabel(g) { if (g.status === "completed") return `Finished ${time(g.completed_at)}`; if (g.running_long) return "Running long · estimates updating"; if (g.status === "ongoing") return `Started ${time(g.started_at)}`; return `${g.paused ? "Paused · " : ""}Est. ${time(g.estimated_start)}`; }
function gameButton(g) { if (!g.home || !g.away || g.status === "not_needed") return ""; return `<button class="${g.status === "ongoing" || g.ready ? "primary" : "secondary"} small" data-game="${g.id}">${g.status === "completed" ? "View result" : g.status === "ongoing" ? "Enter score" : g.ready ? "Open game" : "View game"} →</button>`; }
function gameCard(g) { return `<article class="schedule-card ${g.status === "completed" ? "finished" : ""}"><div class="match-label"><span>${esc(g.id)} · ${esc(phaseNames[g.phase])}${g.number > 1 ? ` · Game ${g.number}` : ""}</span>${badge(g)}</div>${teamRow(g,"away")}${teamRow(g,"home")}<div class="match-footer"><small>${esc(estimateLabel(g))}</small>${gameButton(g)}</div></article>`; }

async function refresh() {
  if (busy) return;
  try { const response = await fetch("/api/state", {cache:"no-store"}); if (!response.ok) throw new Error(); const incoming = await response.json(); const changed = !loaded || incoming.revision !== current.revision; current = incoming; loaded = true; status(true); if (!modal.open && !dirty && (changed || ["dashboard","schedule","teams"].includes(page()))) render(); }
  catch { status(false); if (!loaded) $("main").innerHTML = `<div class="empty"><h1>Waiting for the clubhouse</h1><p>Connect to the tournament Wi-Fi. We’ll retry automatically.</p></div>`; }
}

async function send(action, revision = current.revision, form = null) {
  if (busy) return false;
  busy = true;
  const buttons = [...document.querySelectorAll("button[type=submit]")]; buttons.forEach(b => b.disabled = true);
  try {
    let response = await fetch("/api/change", {method:"POST", headers:{"Content-Type":"application/json","X-Tournament-Request":"1"},body:JSON.stringify({revision,operation_id:uuid(),action})});
    let result = await response.json();
    if (!response.ok && result.affected?.length) {
      if (confirm(`${result.error}\n\nGames to reset: ${result.affected.join(", ")}\n\nReset these games and apply your change?`)) {
        response = await fetch("/api/change", {method:"POST", headers:{"Content-Type":"application/json","X-Tournament-Request":"1"},body:JSON.stringify({revision,operation_id:uuid(),action:{...action,confirm_reset:true}})});
        result = await response.json();
      } else return false;
    }
    if (!response.ok) {
      if (result.latest) {
        current = result.latest;
        const g = action.game && current.tournament?.games.find(g => g.id === action.game);
        const detail = g ? `\nLatest: ${name(g.away)} ${g.away_score ?? "—"} / ${name(g.home)} ${g.home_score ?? "—"}.\nPitchers: ${g.away_pitcher || "—"} / ${g.home_pitcher || "—"}.` : "";
        if (form && confirm(`${result.error}${detail}\n\nKeep your entries for review? If you continue, review your form and submit again to replace the latest values.`)) form.dataset.revision = current.revision;
      }
      throw new Error(result.error || "The change could not be saved.");
    }
    current = result; loaded = true; dirty = false; modal.close(); render(); status(true); toast("Saved to the tournament."); return true;
  } catch (error) {
    const target = form?.querySelector(".error") || $("#modal .error");
    const message = error instanceof TypeError ? "Connection lost. This change was not confirmed saved. Reconnect and check the latest result before retrying." : error.message;
    if (target) target.textContent = message; else toast(message);
    return false;
  } finally { busy = false; buttons.forEach(b => b.disabled = false); }
}

function render() {
  const t = current.tournament;
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.dataset.page === (t ? page() : "settings")));
  $("#tournament-label").textContent = t?.settings.name || "THE CLUBHOUSE";
  document.title = `${t?.settings.name || "Schwaig Red Lions"} · Tournament Manager`;
  const routes = {dashboard:dashboard, schedule:schedulePage, standings:standingsPage, bracket:bracketPage, teams:teamsPage, settings:settingsPage};
  $("main").innerHTML = t ? (routes[page()] || dashboard)() : setupPage();
  if (!t) restoreDraft();
  if (t && page() === "settings") { loadHistory(); loadShare(); }
}

function pendingNotice() {
  const t = current.tournament;
  const ties = Object.entries(t.standings).filter(([,v]) => v.unresolved.length).map(([g]) => g);
  const homes = t.pending_home.map(p => p.series);
  if (!ties.length && !homes.length) return "";
  return `<div class="notice warning"><strong>A draw needs to be recorded.</strong><p>${ties.length ? `Group ${ties.join(" & ")} has tied positions. <a href="#standings">Record the drawn order</a>. ` : ""}${homes.length ? `${homes.join(", ")} needs an opening home team. <a href="#bracket">Record the home draw</a>.` : ""}</p></div>`;
}

function dashboard() {
  const t = current.tournament;
  const played = t.games.filter(g => g.status === "completed").length;
  const phase = t.games.find(g => ["ongoing", "scheduled"].includes(g.status))?.phase;
  const champion = t.champion
    ? '<section class="champion-banner"><span>Tournament champions</span><h2>' + esc(name(t.champion)) + '</h2><p>' + esc(team(t.champion).players.join(" & ")) + '</p></section>'
    : "";
  return heading("Tournament overview", "See who’s playing and open a game to record its score.", '<a class="button secondary" href="#schedule">View schedule</a>') +
    pendingNotice() +
    '<div class="tournament-summary" aria-label="Tournament progress"><span><strong>' +
    (t.champion ? "Tournament complete" : esc(phaseNames[phase] || "Complete")) +
    '</strong></span><span>' + played + (played === 1 ? ' game completed' : ' games completed') + '</span><span>About ' +
    t.settings.game_minutes + ' minutes per game</span></div>' + champion +
    '<div class="fields">' + [1, 2].map(fieldCard).join("") + '</div>' +
    '<nav class="overview-links" aria-label="Tournament details">' +
    '<a href="#standings"><strong>Group standings <span aria-hidden="true">→</span></strong><span>Team rankings and tiebreaks</span></a>' +
    '<a href="#bracket"><strong>Playoff bracket <span aria-hidden="true">→</span></strong><span>Quarterfinals through the final</span></a>' +
    '<a href="#teams"><strong>Teams & pitchers <span aria-hidden="true">→</span></strong><span>Players, results and pitcher usage</span></a></nav>';
}

function fieldCard(field) {
  const t = current.tournament;
  const queue = t.games.filter(g => g.setup === field && !["completed", "not_needed"].includes(g.status)).sort((a,b) => a.sequence-b.sequence);
  const g = queue[0], next = queue[1], pause = t.pauses[String(field)];
  const waiting = g && !g.ready && g.status !== "ongoing" && !pause;
  const header = '<div class="field-top"><h2 class="field-name">' + esc(t.settings.setup_names[field-1]) +
    '</h2><button class="text-button" data-pause="' + field + '">' + (pause ? "Resume field" : "Pause field") + '</button></div>';
  const pauseNotice = pause ? '<div class="notice warning">Field paused' +
    (pause.until ? ' until approximately ' + time(pause.until) : '') + '. Select “Resume field” when ready.</div>' : '';
  const waitingNotice = waiting ? '<p class="waiting-note">' +
    (!g.home || !g.away ? "Teams will appear once the previous round and any draws are settled." : "Waiting for the previous games to finish.") + '</p>' : '';
  const body = g
    ? '<div class="field-body"><div class="match-label"><span>' + (g.status === "ongoing" ? "Now playing" : "Next game") +
      '</span>' + badge(g) + '</div><p class="game-reference">' + esc(phaseNames[g.phase]) + ' · Game ' + esc(g.id) +
      '</p><div class="match-columns"><span>Team / players</span><span>Runs</span></div>' +
      teamRow(g, "away") + teamRow(g, "home") + waitingNotice +
      '<div class="match-footer"><small>' + esc(estimateLabel(g)) + '</small>' + gameButton(g) + '</div></div>' +
      (next ? '<div class="field-next"><span>After this</span><strong>' +
        esc(next.home ? name(next.away) + " vs " + name(next.home) : phaseNames[next.phase]) + '</strong></div>' : '')
    : '<div class="empty"><h3>No more games on this field</h3><p>' +
      (t.champion ? "The tournament is complete." : "Check the other field for the remaining games.") + '</p></div>';
  return '<section class="field-card">' + header + pauseNotice + body + '</section>';
}

function schedulePage() {
  const t = current.tournament;
  const filtered = t.games.filter(g => (!filterTeam || [g.home,g.away].includes(filterTeam)) && (!filterSetup || g.setup === Number(filterSetup)) && (!filterPhase || g.phase === filterPhase));
  return heading("Schedule","Game order is fixed. Estimated times move with the action.") + pendingNotice() +
    `<div class="filters"><label>Team<select id="filter-team"><option value="">All teams</option>${t.teams.map(t=>`<option value="${t.id}"${selected(t.id,filterTeam)}>${esc(t.name)}</option>`).join("")}</select></label><label>Field<select id="filter-setup"><option value="">Both fields</option>${[1,2].map(n=>`<option value="${n}"${selected(String(n),filterSetup)}>${esc(t.settings.setup_names[n-1])}</option>`).join("")}</select></label><label>Stage<select id="filter-phase"><option value="">All stages</option>${Object.entries(phaseNames).map(([key,label])=>`<option value="${key}"${selected(key,filterPhase)}>${label}</option>`).join("")}</select></label></div>
    <div class="schedule-grid">${[1,2].filter(n=>!filterSetup||String(n)===filterSetup).map(n=>`<section><h2>${esc(t.settings.setup_names[n-1])}</h2>${Object.entries(phaseNames).map(([phase,label])=>{const games=filtered.filter(g=>g.setup===n&&g.phase===phase).sort((a,b)=>a.sequence-b.sequence);return games.length?`<h3 class="phase-heading">${label}</h3>${games.map(gameCard).join("")}`:"";}).join("")}${!filtered.some(g=>g.setup===n)?`<p class="muted spaced">No games match these filters.</p>`:""}</section>`).join("")}</div>`;
}

function groupTable(group, compact = false) {
  const table = current.tournament.standings[group];
  return `<div><div class="group-heading"><h3>Group ${group}</h3><span class="badge">${table.resolved ? "Seeded" : table.complete ? "Draw pending" : "Provisional"}</span></div><div class="table-wrap"><table><thead><tr><th>#</th><th>Team</th>${compact?"":"<th>P</th>"}<th>W</th><th>L</th>${compact?"":"<th>RF</th><th>RA</th>"}<th>+/−</th></tr></thead><tbody>${table.rows.map(r=>`<tr><td>${table.unresolved.some(ids=>ids.includes(r.team))?"=":r.position}</td><td><a href="#teams/${r.team}">${esc(name(r.team))}</a></td>${compact?"":`<td>${r.played}</td>`}<td><strong>${r.wins}</strong></td><td>${r.losses}</td>${compact?"":`<td>${r.rf}</td><td>${r.ra}</td>`}<td>${r.rd>0?"+":""}${r.rd}</td></tr>`).join("")}</tbody></table></div></div>`;
}

function standingsPage() {
  return heading("Group standings","Three games each. Everyone advances. Your record decides the seed.")+
    `<div class="two-col">${["A","B"].map(g=>{const table=current.tournament.standings[g];return `<section class="panel">${groupTable(g)}${table.unresolved.length?`<div class="notice warning spaced">Draw needed: ${table.unresolved.map(ids=>ids.map(name).map(esc).join(", ")).join("; ")}. Draw these teams in person, then record their order below. Other positions remain determined by results.</div><form class="tiebreak-form" data-form="tie" data-group="${g}" data-revision="${current.revision}">${table.rows.map((r,i)=>`<label>Position ${i+1}<select name="position-${i}">${table.rows.map(option=>`<option value="${option.team}"${selected(option.team,r.team)}>${esc(name(option.team))}</option>`).join("")}</select></label>`).join("")}<p class="error" role="alert"></p><div class="form-actions"><button class="primary" type="submit">Record drawn order</button></div></form>`:""}</section>`;}).join("")}</div><div class="notice spaced"><strong>Tiebreak rules</strong><p>Wins → head-to-head for two tied teams → overall group run differential → runs scored → manual draw. For three or more teams tied on wins, head-to-head is skipped.</p></div>`;
}

function seriesCard(id) {
  const games = current.tournament.games.filter(g=>g.series===id);
  const first = games[0], scores = {};
  games.forEach(g=>{if(g.winner)scores[g.winner]=(scores[g.winner]||0)+1;});
  const participants = [first.home,first.away];
  const pending = current.tournament.pending_home.find(p=>p.series===id);
  if(pending) participants.splice(0,2,...pending.teams);
  const needed = id === "F" ? 3 : id.startsWith("SF") ? 2 : 1;
  return `<article class="series-card ${id==="F"?"championship":""}"><div class="section-heading"><h3>${id === "F" ? "CHAMPIONSHIP" : id}</h3><small>${games.length===1?"Single game":`Best of ${games.length}`}</small></div>${participants.map((t,i)=>`<div class="pair"><span>${esc(t?name(t):sourceLabel(first,i===0?"home":"away"))}${t&&scores[t]>=needed?" ★":""}</span><strong>${t?scores[t]||0:"—"}</strong></div>`).join("")}<div class="series-games">${games.map(g=>`<button data-game="${g.id}" class="${g.status==="completed"?"won":""}" ${!g.home||g.status==="not_needed"?"disabled":""}>G${g.number}${g.status==="completed"?` · ${g.away_score}–${g.home_score}`:g.status==="not_needed"?" · N/A":g.if_needed?"*":""}</button>`).join("")}</div>${pending?`<form data-form="home" data-series="${id}" data-revision="${current.revision}" class="spaced"><p class="mini-note">Group records are equal. Record who won the manual draw for home in game 1.</p><label>Opening home team<select name="team">${pending.teams.map(t=>`<option value="${t}">${esc(name(t))}</option>`).join("")}</select></label><p class="error" role="alert"></p><div class="form-actions"><button class="primary" type="submit">Record home draw</button></div></form>`:""}</article>`;
}
function bracketPage() { return heading("Playoff bracket","A fixed bracket. Win your series. Keep the dream alive.")+pendingNotice()+`<div class="bracket-grid"><section><h2 class="section-heading">Quarterfinals</h2>${[1,2,3,4].map(n=>seriesCard(`QF${n}`)).join("")}</section><section><h2 class="section-heading">Semifinals</h2>${seriesCard("SF1")}${seriesCard("SF2")}<p class="mini-note">SF1: winners of QF1 & QF2.<br>SF2: winners of QF3 & QF4.</p></section><section><h2 class="section-heading">The final</h2>${seriesCard("F")}${current.tournament.champion?`<div class="notice"><strong>★ ${esc(name(current.tournament.champion))}</strong><p>Tournament champions.</p></div>`:""}</section></div><p class="mini-note spaced">* If needed. Higher group placement gets home in the quarterfinal. Series home advantage uses group placement, wins, run differential, runs scored, then a manual draw. Home alternates each game.</p>`; }

function teamsPage() {
  const id = location.hash.split("/")[1], t = team(id);
  if (!t) return heading("Teams & pitchers","Sixteen players, eight partnerships. Follow each team’s results and rotation.")+`<div class="team-grid">${current.tournament.teams.map(t=>`<article class="panel team-card"><a href="#teams/${t.id}"><div class="team-icon ${t.group==="B"?"b":""}">${esc(initials(t.id))}</div><div class="section-heading"><h3>${esc(t.name)}</h3><span class="badge">GROUP ${t.group}</span></div><p class="muted">${esc(t.players.join(" & "))}</p><p class="text-button spaced">Games & pitcher history →</p></a></article>`).join("")}</div>`;
  const games = current.tournament.games.filter(g=>[g.home,g.away].includes(id)&&g.status!=="not_needed").sort((a,b)=>a.sequence-b.sequence);
  const past = games.filter(g=>g.status==="completed"||g.status==="ongoing").sort((a,b)=>new Date(a.started_at||a.completed_at)-new Date(b.started_at||b.completed_at));
  return heading(t.name,`${t.players.join(" & ")} · Group ${t.group}`,`<a class="button secondary" href="#teams">All teams</a>`)+`<section class="panel"><h2>Starting pitcher history</h2><p class="mini-note">A record of usage. Rotation decisions are yours.</p>${past.length?`<div class="table-wrap"><table><thead><tr><th>Game</th><th>Opponent</th><th>Pitcher</th><th>Result</th></tr></thead><tbody>${past.map(g=>{const side=g.home===id?"home":"away",other=side==="home"?"away":"home";return `<tr><td><button class="text-button" data-game="${g.id}">${g.id}</button></td><td>${esc(name(g[other]))}</td><td>${esc(g[side+"_pitcher"]||"Not recorded")}</td><td>${g.status==="ongoing"?"Live":`${g.winner===id?"W":"L"} ${g[side+"_score"]}–${g[other+"_score"]}`}</td></tr>`;}).join("")}</tbody></table></div>`:`<p class="muted spaced">Pitchers will appear here as your games are played.</p>`}</section><h2 class="spaced">Team schedule</h2><div class="two-col spaced">${games.map(gameCard).join("")}</div>`;
}

function dateLocal(iso, zone="Europe/Berlin") {
  const parts = new Intl.DateTimeFormat("en-CA", {timeZone:zone,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(new Date(iso));
  const p = Object.fromEntries(parts.map(p=>[p.type,p.value])); return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
function zonedISO(value, zone) {
  // Resolve the wall-clock form value in the selected tournament timezone, not the phone's timezone.
  const wall = Date.parse(value+"Z"); if(!Number.isFinite(wall)) throw new Error("Enter a valid tournament date and time.");
  let guess=wall;
  for(let i=0;i<3;i++) { const displayed=Date.parse(dateLocal(new Date(guess).toISOString(),zone)+"Z"); guess += wall-displayed; }
  if(dateLocal(new Date(guess).toISOString(),zone)!==value) throw new Error("That local time does not exist because of a daylight-saving change. Choose another time.");
  return new Date(guess).toISOString();
}
function configFields(settings) {
  return `<div class="form-grid"><label class="full">Tournament name<input name="name" value="${esc(settings.name)}" maxlength="100" required></label><label>Start date & time<input name="start" type="datetime-local" value="${esc(dateLocal(settings.start,settings.timezone))}" required></label><label>Timezone<input name="timezone" value="${esc(settings.timezone)}" required><span class="form-help">The start time uses this timezone.</span></label><label>Estimated game length (minutes)<input name="game_minutes" type="number" min="1" max="180" value="${settings.game_minutes}" required></label><label>Break between games (minutes)<input name="break_minutes" type="number" min="0" max="120" value="${settings.break_minutes}" required></label><label>Minimum team rest (minutes)<input name="rest_minutes" type="number" min="0" max="120" value="${settings.rest_minutes}" required></label><div></div><label>Setup 1 name<input name="setup1" maxlength="50" value="${esc(settings.setup_names[0])}" required></label><label>Setup 2 name<input name="setup2" maxlength="50" value="${esc(settings.setup_names[1])}" required></label><label class="full">Shared pitcher list (one per line, optional)<textarea name="pitchers">${esc(settings.pitchers.join("\n"))}</textarea><span class="form-help">Suggestions only. You can always type a different pitcher.</span></label></div>`;
}
function readSettings(form) { const f = new FormData(form); const zone=f.get("timezone").trim(); return {name:f.get("name"),start:zonedISO(f.get("start"),zone),timezone:zone,game_minutes:Number(f.get("game_minutes")),break_minutes:Number(f.get("break_minutes")),rest_minutes:Number(f.get("rest_minutes")),setup_names:[f.get("setup1"),f.get("setup2")],pitchers:f.get("pitchers").split("\n").map(s=>s.trim()).filter(Boolean)}; }
function setupPage() {
  const defaults={name:"Schwaig Red Lions · Game Day",start:new Date().toISOString(),timezone:"Europe/Berlin",game_minutes:25,break_minutes:5,rest_minutes:10,setup_names:["Field 1","Field 2"],pitchers:[]};
  return heading("Build your game day.","Eight teams. Two groups. Set it up once, then let the games begin.")+`<form id="setup-form" data-form="create" data-revision="${current.revision}"><section class="panel setup-section"><h2><span class="step-number">1</span>Tournament details</h2><div class="spaced">${configFields(defaults)}</div></section><section class="panel setup-section"><div class="section-heading"><h2><span class="step-number">2</span>Teams & players</h2><button class="secondary small" type="button" data-action="draw">Draw partners</button></div><p class="mini-note">One team name and two fixed players per team. All teams use the same MLB roster.</p>${Array.from({length:8},(_,i)=>`<div class="team-entry"><label>Team ${i+1}<input name="team-${i}" placeholder="Team name" maxlength="100" required></label><label>Player 1<input name="player-${i}-0" placeholder="Player name" maxlength="100" required></label><label>Player 2<input name="player-${i}-1" placeholder="Player name" maxlength="100" required></label><label>Group<select name="group-${i}"><option value="A"${i<4?" selected":""}>A</option><option value="B"${i>=4?" selected":""}>B</option></select></label></div>`).join("")}<button class="text-button spaced" type="button" data-action="random-groups">Randomize groups →</button></section><div class="notice">Group A stays on Field 1; Group B stays on Field 2. Each team plays three group games before the fixed playoff bracket. You’ll preview the groups before creating the tournament.</div><p class="error" role="alert"></p><div class="form-actions"><button class="primary" type="submit">Preview tournament →</button></div></form><section class="panel spaced"><h3>Already have a tournament backup?</h3>${restoreForm()}</section>`;
}
function saveDraft() { const form=$("#setup-form"); if(form) { try { localStorage.setItem("local-league-setup",JSON.stringify(Object.fromEntries(new FormData(form)))); } catch {} } }
function restoreDraft() { const form=$("#setup-form"); if(!form)return; try { const draft=JSON.parse(localStorage.getItem("local-league-setup")||"null"); if(draft) for(const [key,value] of Object.entries(draft)) if(form.elements.namedItem(key)) form.elements.namedItem(key).value=value; } catch {} }
function restoreForm() { return `<form data-form="restore" data-revision="${current.revision}"><label class="spaced">JSON backup<input name="backup" type="file" accept="application/json,.json" required></label><p class="form-help">Restore replaces the current tournament. A local backup is made first.</p><p class="error" role="alert"></p><div class="form-actions"><button class="secondary" type="submit">Restore backup</button></div></form>`; }
function settingsPage() { const s=current.tournament.settings;return heading("Tournament settings","Timing, shared pitcher names, backups, and the local connection.")+`<div class="two-col"><section class="panel"><h2>Tournament settings</h2><form data-form="settings" data-revision="${current.revision}" class="spaced">${configFields(s)}<p class="form-help spaced">Rest and start times are estimates. Ready games can be started early when both teams agree.</p><p class="error" role="alert"></p><div class="form-actions"><button class="primary" type="submit">Save settings</button></div></form></section><div><section class="panel"><h2>Bring everyone aboard</h2><div class="qr-panel spaced"><img id="share-qr" alt="QR code linking to this tournament" hidden><div><p>Connect to the same Wi-Fi and scan this code.</p><p class="spaced"><a id="share-url">Finding local network address…</a></p><p class="mini-note spaced">This code uses the host’s local network address, even when you open the app through localhost.</p></div></div></section><section class="panel spaced"><h2>Keep a copy</h2><p class="mini-note spaced">Scores, pitchers, teams and draw decisions are saved on the Pi after every change.</p><a class="button secondary spaced" href="/api/export" download>Download JSON backup ↓</a>${restoreForm()}</section><section class="panel spaced"><h3>Start a new tournament</h3><p class="mini-note spaced">Reset clears the active tournament. An automatic backup and the change history are kept on the Pi.</p><button class="text-button danger spaced" data-action="reset">Reset tournament</button></section></div></div><section class="panel spaced"><h2>Recent changes</h2><p class="mini-note">Shared editing without accounts. This records what changed, not who changed it.</p><div id="history" class="spaced">Loading history…</div></section>`; }

async function loadShare() {
  try {
    const response = await fetch("/api/share", {cache:"no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not find the local network address.");
    const link = $("#share-url"), qr = $("#share-qr");
    if (!link || !qr) return;
    link.textContent = data.url; link.href = data.url;
    qr.src = "/api/qr.svg"; qr.hidden = false;
  } catch (error) {
    const link = $("#share-url");
    if (link) link.textContent = error.message;
  }
}

async function loadHistory() { try { const response=await fetch("/api/history"); if(!response.ok)throw new Error(); const data=await response.json();const target=$("#history");if(target)target.innerHTML=data.entries.length?data.entries.map(e=>`<details class="history-item"><summary>${esc(longTime(e.at))} · ${esc(e.type)} ${esc(e.game||"")}${e.changes.length?` · ${e.changes.length} game records changed`:""}</summary>${e.changes.map(c=>`<pre>${esc(c.game)}\nBefore: ${esc(JSON.stringify(c.before,null,2))}\nAfter: ${esc(JSON.stringify(c.after,null,2))}</pre>`).join("")}</details>`).join(""):"No changes yet."; } catch {const target=$("#history");if(target)target.textContent="History could not be loaded. Reload to retry.";} }

function openModal(content) { $("#modal-content").innerHTML=content; if(!modal.open)modal.showModal(); }
function closeButton(){return `<button type="button" class="close" data-action="close" aria-label="Close dialog">×</button>`;}
function openGame(id) {
  const g=gameById(id);if(!g||!g.home||!g.away||g.status==="not_needed")return;
  openModal(`<div class="dialog-heading"><div><div class="kicker">${g.id} · ${phaseNames[g.phase]}</div><h2>${g.status==="completed"?"The final score":"Game details"}</h2><p>${esc(current.tournament.settings.setup_names[g.setup-1])} · ${esc(estimateLabel(g))}</p></div>${closeButton()}</div><form data-form="game" data-game="${id}" data-revision="${current.revision}"><div class="score-entry">${["away","home"].map(side=>`<div><div class="kicker">${side}</div><h3>${esc(name(g[side]))}</h3><label>Runs<input type="number" name="${side}_score" min="0" max="999" value="${g[side+"_score"]??""}" inputmode="numeric"></label><label>Starting pitcher<input name="${side}_pitcher" value="${esc(g[side+"_pitcher"])}" maxlength="100" list="pitcher-list" placeholder="Name (optional)"></label></div>`).join("")}</div><datalist id="pitcher-list">${current.tournament.settings.pitchers.map(p=>`<option value="${esc(p)}"></option>`).join("")}</datalist><p class="mini-note">Pitchers are recorded for your reference. A final score must have a winner.</p><p class="error" role="alert"></p><div id="score-review"></div><div class="form-actions"><button class="secondary" type="submit" name="intent" value="pitchers">Save pitchers</button>${g.ready?`<button class="secondary" type="submit" name="intent" value="start">Start game</button>`:""}${g.ready||["ongoing","completed"].includes(g.status)?`<button class="primary" type="submit" name="intent" value="score">Review result →</button>`:""}</div>${g.status==="completed"||g.status==="ongoing"?`<button type="button" class="text-button danger spaced" data-reopen="${id}">Reopen game and clear result</button>`:""}</form>`);
}

function shuffle(items) { const result=[...items]; for(let i=result.length-1;i>0;i--){const limit=Math.floor(4294967296/(i+1))*(i+1);let n;do{n=crypto.getRandomValues(new Uint32Array(1))[0];}while(n>=limit);const j=n%(i+1);[result[i],result[j]]=[result[j],result[i]];}return result; }
function drawDialog() { openModal(`<div class="dialog-heading"><div><div class="kicker">THE PARTNER DRAW</div><h2>Find your teammate.</h2><p>One player from each pool makes a team.</p></div>${closeButton()}</div><form data-form="draw"><div class="form-grid"><label>Top eight players<textarea name="top" rows="9" placeholder="One player per line" required></textarea></label><label>Other eight players<textarea name="other" rows="9" placeholder="One player per line" required></textarea></label></div><p class="error" role="alert"></p><div class="form-actions"><button class="primary" type="submit">Draw partnerships →</button></div></form>`); }

document.addEventListener("input",event=>{if(event.target.closest("form")){if(!event.target.closest("dialog"))dirty=true;saveDraft();if(event.target.closest('[data-form="game"]'))$("#score-review").innerHTML="";}});
document.addEventListener("change",event=>{const el=event.target;if(el.id.startsWith("filter-")){if(el.id==="filter-team")filterTeam=el.value;if(el.id==="filter-setup")filterSetup=el.value;if(el.id==="filter-phase")filterPhase=el.value;render();}else if(el.closest("form")&&!el.closest("dialog")){dirty=true;saveDraft();}});
window.addEventListener("hashchange",()=>{if(dirty&&current.tournament&&!confirm("Leave this page and discard unsaved form changes?")){history.replaceState(null,"",window.lastHash||"#dashboard");return;}dirty=false;modal.close();window.lastHash=location.hash;render();window.scrollTo(0,0);});
window.lastHash=location.hash;

document.addEventListener("click",async event=>{
  const button=event.target.closest("button");if(!button)return;
  if(button.dataset.game){openGame(button.dataset.game);return;}
  if(button.dataset.reopen){if(confirm("Clear this game’s score, start time and pitchers? Dependent recorded games may also need resetting.")){const form=button.closest("form");await send({type:"reopen",game:button.dataset.reopen},Number(form.dataset.revision),form);}return;}
  if(button.dataset.pause){const field=Number(button.dataset.pause);if(current.tournament.pauses[String(field)])await send({type:"pause",setup:field,paused:false});else openModal(`<div class="dialog-heading"><h2>Pause ${esc(current.tournament.settings.setup_names[field-1])}</h2>${closeButton()}</div><form data-form="pause" data-setup="${field}" data-revision="${current.revision}"><label>Estimated resume time (${esc(current.tournament.settings.timezone)})<input name="until" type="datetime-local"></label><p class="form-help">Leave blank if unknown. Resume the field manually when ready.</p><p class="error" role="alert"></p><div class="form-actions"><button class="primary" type="submit">Pause field</button></div></form>`);return;}
  const action=button.dataset.action;
  if(action==="close")modal.close();
  if(action==="draw")drawDialog();
  if(action==="random-groups"){const groups=shuffle(["A","A","A","A","B","B","B","B"]);groups.forEach((g,i)=>$(`[name="group-${i}"]`).value=g);dirty=true;saveDraft();toast("Groups randomized. Review the assignments before creating.");}
  if(action==="reset"){const confirmation=prompt("Type RESET to clear the active tournament. A local backup will be saved first.");if(confirmation==="RESET")await send({type:"reset",confirmation});}
});

document.addEventListener("submit",async event=>{
  const form=event.target;if(!form.dataset.form)return;event.preventDefault();const values=new FormData(form),revision=Number(form.dataset.revision),error=$(".error",form);if(error)error.textContent="";
  try {
    switch(form.dataset.form){
      case "settings": await send({type:"settings",settings:readSettings(form)},revision,form);break;
      case "tie": await send({type:"tie",group:form.dataset.group,order:[0,1,2,3].map(i=>values.get(`position-${i}`))},revision,form);break;
      case "home": await send({type:"home_draw",series:form.dataset.series,team:values.get("team")},revision,form);break;
      case "pause": await send({type:"pause",setup:Number(form.dataset.setup),paused:true,until:values.get("until")?zonedISO(values.get("until"),current.tournament.settings.timezone):null},revision,form);break;
      case "restore": {const file=values.get("backup");if(file.size>2000000)throw new Error("Backup is too large (maximum 2 MB).");const snapshot=JSON.parse(await file.text());if(confirm("Replace the active tournament with this backup? The existing tournament will be backed up first."))await send({type:"restore",snapshot,confirmation:"REPLACE"},revision,form);break;}
      case "game": {
        const intent=event.submitter?.value||"score",action={type:intent,game:form.dataset.game,home_pitcher:values.get("home_pitcher"),away_pitcher:values.get("away_pitcher")};
        if(intent==="score"||intent==="confirm-score"){
          for(const side of ["home","away"]){const value=values.get(side+"_score");if(value===""||!/^\d+$/.test(value))throw new Error("Enter a whole-number score for both teams.");action[side+"_score"]=Number(value);}
          if(action.home_score===action.away_score)throw new Error("No draws: finish extra innings before recording the result.");
          action.type="score";
          if(intent!=="confirm-score") {const g=gameById(form.dataset.game);$("#score-review").innerHTML=`<div class="review-score"><strong>Confirm the final result</strong><p>AWAY · ${esc(name(g.away))}: <strong>${action.away_score}</strong><br>HOME · ${esc(name(g.home))}: <strong>${action.home_score}</strong></p><button type="submit" class="primary" name="intent" value="confirm-score">Confirm & save result</button></div>`;return;}
        }
        await send(action,revision,form);break;
      }
      case "create": {
        const setup={settings:readSettings(form),teams:Array.from({length:8},(_,i)=>({name:values.get(`team-${i}`).trim(),players:[values.get(`player-${i}-0`).trim(),values.get(`player-${i}-1`).trim()],group:values.get(`group-${i}`)}))};
        if(setup.teams.filter(t=>t.group==="A").length!==4)throw new Error("Assign exactly four teams to each group.");
        if(new Set(setup.teams.map(t=>t.name.toLowerCase())).size!==8)throw new Error("Team names must be distinct.");
        if(new Set(setup.teams.flatMap(t=>t.players).map(p=>p.toLowerCase())).size!==16)throw new Error("Enter sixteen distinct player names.");
        openModal(`<div class="dialog-heading"><div><div class="kicker">READY FOR FIRST PITCH</div><h2>${esc(setup.settings.name)}</h2><p>Review your groups. Game order within each group is randomized once on creation.</p></div>${closeButton()}</div><div class="two-col">${["A","B"].map(g=>`<section><h3>Group ${g}</h3><ol class="preview-list">${setup.teams.filter(t=>t.group===g).map(t=>`<li><strong>${esc(t.name)}</strong><br><small>${esc(t.players.join(" & "))}</small></li>`).join("")}</ol></section>`).join("")}</div><p class="mini-note">Opening matchups and all estimated times will appear immediately after creation.</p><form data-form="confirm-create" data-revision="${revision}"><p class="error" role="alert"></p><div class="form-actions"><button type="button" class="secondary" data-action="close">Back to editing</button><button type="submit" class="primary">Create tournament</button></div></form>`);
        $("[data-form=confirm-create]").setupData=setup;break;
      }
      case "confirm-create": {if(await send({type:"create",tournament:form.setupData},revision,form)){try{localStorage.removeItem("local-league-setup");}catch{}location.hash="dashboard";}break;}
      case "draw": {
        const top=values.get("top").split("\n").map(s=>s.trim()).filter(Boolean),other=values.get("other").split("\n").map(s=>s.trim()).filter(Boolean);
        if(top.length!==8||other.length!==8||new Set([...top,...other].map(s=>s.toLowerCase())).size!==16)throw new Error("Enter eight distinct players in each pool, with no player in both.");
        const lower=shuffle(other);openModal(`<div class="dialog-heading"><div><div class="kicker">THE DRAW IS IN</div><h2>Your partnerships.</h2></div>${closeButton()}</div><ol class="preview-list">${top.map((p,i)=>`<li>${esc(p)} & ${esc(lower[i])}</li>`).join("")}</ol><form data-form="accept-draw"><div class="form-actions"><button type="button" class="secondary" data-action="close">Cancel</button><button class="primary" type="submit">Use these teams</button></div></form>`);$("[data-form=accept-draw]").pairs=top.map((p,i)=>[p,lower[i]]);break;
      }
      case "accept-draw": {form.pairs.forEach((pair,i)=>{pair.forEach((p,j)=>$(`[name="player-${i}-${j}"]`).value=p);if(!$(`[name="team-${i}"]`).value)$(`[name="team-${i}"]`).value=`Team ${i+1}`;});dirty=true;saveDraft();modal.close();toast("Partnerships saved to your setup draft. Rename the teams as you like.");break;}
    }
  } catch(e){if(error)error.textContent=e.message;else toast(e.message);}
});

refresh();setInterval(refresh,5000);
