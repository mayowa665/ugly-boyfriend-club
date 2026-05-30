const CONF_COLORS = {
  UEFA: "#1d4ed8",
  CMB: "#eab308",
  CAF: "#16a34a",
  AFC: "#dc2626",
  CCF: "#9333ea",
  OFC: "#0891b2",
};

let state = null;
let activeTab = "cards";

function fmtPct(value) {
  const percent = value * 100;
  if (percent <= 0) return "0%";
  if (percent < 0.01) return "<0.01%";
  if (percent < 0.1) return percent.toFixed(2) + "%";
  return percent.toFixed(1) + "%";
}

function titlePhase(phase) {
  return String(phase || "").replaceAll("_", " ").replace(/\b\w/g, char => char.toUpperCase());
}

function relativeTime(iso) {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "Updated recently";
  const seconds = Math.round((Date.now() - then.getTime()) / 1000);
  const abs = Math.abs(seconds);
  const units = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (abs >= size) {
      const value = Math.round(seconds / size);
      return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(-value, unit);
    }
  }
  return "just now";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function flag(t, className = "") {
  const code = encodeURIComponent(t.code);
  const fallback = t.code.replace("gb-", "").slice(0, 2).toUpperCase();
  return `
    <span class="flag ${className}">
      <img src="https://flagcdn.com/${code}.svg" alt="" loading="lazy"
        onerror="this.remove(); this.parentElement.dataset.fallback='${fallback}'">
    </span>
  `;
}

function teamRow(team) {
  const out = team.eliminated ? `<span class="out-tag">OUT</span>` : "";
  return `
    <div class="team ${team.eliminated ? "eliminated" : ""}" style="--conf:${CONF_COLORS[team.conf] || "#777"}">
      <span class="team-flag">${flag(team)}</span>
      <span class="team-name">${escapeHtml(team.name)}</span>
      ${out}
      <span class="team-prob">${fmtPct(team.p)}</span>
    </div>
  `;
}

function cardsView() {
  return `
    <section class="section">
      <div class="section-head">
        <div>
          <div class="section-kicker">Entrants</div>
          <h2>Sweepstake Cards</h2>
        </div>
        <p>Current outright chances by entrant.</p>
      </div>
      <div class="grid">${entrantCards()}</div>
    </section>
  `;
}

function entrantCards() {
  return state.entrants.map((entrant, index) => `
    <article class="card">
      <div class="card-num">${String(index + 1).padStart(2, "0")}</div>
      <h2 class="card-name">${escapeHtml(entrant.name)}</h2>
      <div class="card-divider"></div>
      ${entrant.teams.map(teamRow).join("")}
      <div class="slip">
        <div>
          <div class="slip-label">To Lift The Trophy</div>
          <div class="slip-prob">${fmtPct(entrant.prob)} - ${entrant.alive_teams} alive</div>
        </div>
        <div class="slip-odds">${escapeHtml(entrant.odds)}</div>
      </div>
    </article>
  `).join("");
}

function boardView() {
  return `
    <section class="section">
      <div class="board-head">
        <div class="board-title">Outright Winner - Entrants</div>
        <div class="board-sub">Probability of holding the World Cup winner</div>
      </div>
      <div class="board">${leaderboardRows()}</div>
    </section>
  `;
}

function leaderboardRows() {
  return state.entrants.map((entrant, index) => `
    <div class="board-row">
      <div class="rank">${String(index + 1).padStart(2, "0")}</div>
      <div>
        <div class="board-name">${escapeHtml(entrant.name)}</div>
        <div class="board-teams">${entrant.teams.map(t => escapeHtml(t.name)).join(" / ")}</div>
      </div>
      <div class="board-prob">${fmtPct(entrant.prob)}</div>
      <div class="board-odds">${escapeHtml(entrant.odds)}</div>
    </div>
  `).join("");
}

function renderRecent() {
  const recent = document.getElementById("recent");
  if (!state.recent_results || state.recent_results.length === 0) {
    recent.innerHTML = "";
    return;
  }
  recent.innerHTML = state.recent_results.map(result => `
    <div class="result">
      <span>${escapeHtml(result.stage)}</span>
      <strong>${escapeHtml(result.home)} ${escapeHtml(result.score)} ${escapeHtml(result.away)}</strong>
    </div>
  `).join("");
}

function eliminatedView() {
  return `
    <section class="section">
      <div class="section-head">
        <div>
          <div class="section-kicker">The Fallen</div>
          <h2>Eliminated Teams</h2>
        </div>
      </div>
      <div class="eliminated-rail">${eliminatedRail()}</div>
    </section>
  `;
}

function eliminatedRail() {
  const eliminatedTeams = state.teams
    .filter(team => team.eliminated)
    .sort((left, right) => left.name.localeCompare(right.name));

  if (eliminatedTeams.length === 0) {
    return `<div class="empty-state">No teams eliminated yet.</div>`;
  }

  const chips = eliminatedTeams.map((team, index) => `
    <div class="eliminated-chip" style="--i:${index}; --conf:${CONF_COLORS[team.conf] || "#777"}">
      ${flag(team)}
      <span>${escapeHtml(team.name)}</span>
      <strong>OUT</strong>
    </div>
  `).join("");

  return `
    <div class="elimination-track ${eliminatedTeams.length > 4 ? "scrolling" : ""}">
      ${chips}
      ${eliminatedTeams.length > 4 ? chips : ""}
    </div>
  `;
}

function bracketView() {
  return `
    <section class="section">
      <div class="section-head">
        <div>
          <div class="section-kicker">Knockout</div>
          <h2>Bracket</h2>
        </div>
        <p>Elimination-round fixtures only.</p>
      </div>
      <div class="bracket">${bracketRounds()}</div>
    </section>
  `;
}

function bracketRounds() {
  const rounds = state.knockout_bracket || [];

  if (rounds.length === 0) {
    return `<div class="empty-state">Knockout fixtures not released yet.</div>`;
  }

  return rounds.map(round => `
    <section class="bracket-round">
      <h3>${escapeHtml(round.stage)}</h3>
      <div class="bracket-matches">
        ${round.matches.map(renderBracketMatch).join("")}
      </div>
    </section>
  `).join("");
}

function renderBracketMatch(match) {
  return `
    <article class="bracket-match ${match.status === "FINISHED" ? "finished" : ""}">
      <div class="match-meta">${escapeHtml(matchLabel(match))}</div>
      ${bracketTeam(match, "home")}
      ${bracketTeam(match, "away")}
    </article>
  `;
}

function bracketTeam(match, side) {
  const code = match[`${side}_code`];
  const name = match[`${side}_name`] || "TBD";
  const score = match[`${side}_score`];
  const winner = code && match.winner_code === code;
  const team = code ? { code, name } : null;

  return `
    <div class="bracket-team ${winner ? "winner" : ""}">
      ${team ? flag(team) : `<span class="flag placeholder"></span>`}
      <span>${escapeHtml(name)}</span>
      <strong>${score === null || score === undefined ? "" : escapeHtml(score)}</strong>
    </div>
  `;
}

function matchLabel(match) {
  if (match.status === "FINISHED") return "FT";
  if (match.date) return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(new Date(match.date));
  return titlePhase(match.status || "scheduled");
}

function renderMeta() {
  document.getElementById("meta").innerHTML = `<span>USA</span><span>MEX</span><span>CAN</span><span>Live Odds</span>`;
  document.getElementById("updated").textContent = "Updated " + relativeTime(state.updated_at);
  document.getElementById("phase").textContent = titlePhase(state.phase);
}

function renderAll() {
  renderMeta();
  renderRecent();
  setTab(activeTab);
}

const VIEW_RENDERERS = {
  cards: cardsView,
  eliminated: eliminatedView,
  bracket: bracketView,
  board: boardView,
};

function setTab(tab) {
  if (!VIEW_RENDERERS[tab]) return;
  activeTab = tab;

  document.querySelectorAll(".tab").forEach(button => {
    const active = button.dataset.tab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });

  const view = document.getElementById("view");
  view.setAttribute("aria-labelledby", `tab-${tab}`);
  if (state) view.innerHTML = VIEW_RENDERERS[tab]();
}

async function init() {
  try {
    const response = await fetch("./state.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`state.json returned ${response.status}`);
    state = await response.json();
    renderAll();
  } catch (error) {
    document.getElementById("view").innerHTML = `<div class="error">Could not load state.json. Run python sim/build_state.py --out state.json first.</div>`;
    document.getElementById("updated").textContent = error.message;
  }
}

document.querySelectorAll(".tab").forEach(button => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
});

init();
