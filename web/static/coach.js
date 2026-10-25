// AI coach: floating chat grounded in the app's data, focused on the dashboard page in view.
(() => {
  const $c = (s) => document.querySelector(s);
  const escC = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const CONV_KEY = "fm-coach-conversation";      // id of the open conversation; the messages live on the server
  let msgs = [];
  let busy = false;
  let convId = null;
  let showHistory = false;
  try { convId = localStorage.getItem(CONV_KEY); } catch { convId = null; }
  const setConv = (id) => { convId = id; try { id ? localStorage.setItem(CONV_KEY, id) : localStorage.removeItem(CONV_KEY); } catch { /* private mode */ } };
  async function loadConv(id) {
    try {
      const r = await fetch(`/api/chats/${encodeURIComponent(id)}`);
      if (!r.ok) throw new Error("gone");
      msgs = (await r.json()).messages || [];
      setConv(id);
    } catch { msgs = []; setConv(null); }
  }
  const fmtN = (n) => Number(n || 0).toLocaleString();
  const usageText = (u) => (!u ? "" : `${fmtN(u.input)} in · ${fmtN(u.output)} out tokens`
    + (u.cost != null ? ` · $${u.cost < 0.01 ? u.cost.toFixed(4) : u.cost.toFixed(3)}` : "")
    + (u.plan ? " · ChatGPT plan usage" : u.cost == null ? " · cost not reported by this provider" : ""));

  const page = () => (location.hash.slice(1) || "overview");
  function focusLabel() {
    const [name, ...args] = page().split("?")[0].split("/");
    const h1 = document.querySelector("#view h1")?.textContent?.trim();
    if (name === "player" && args[0]) return { kind: "player", text: h1 || "this player", who: h1 };
    if (name === "match" && args[0]) return { kind: "match", text: h1 || "this match" };
    if (name === "compare" && args.length >= 2) {
      const sel = [...document.querySelectorAll("#view select")].map((s) => s.selectedOptions[0]?.textContent.replace(/ \(.*/, ""));
      return { kind: "compare", text: sel.filter(Boolean).join(" vs ") || "comparison", pair: sel };
    }
    return { kind: name, text: { overview: "Overview (whole squad)", players: "All players", development: "Development",
      per90: "Per 90", fixtures: "Fixtures", settings: "Settings" }[name] || name };
  }

  function suggestions() {
    const f = focusLabel();
    const base = [
      "Who should I rest for the next match?",
      "Who's on form and should stay in the matchday squad?",
      "Who's not performing well and should I consider rotating?",
      "Which young players need development minutes, and in which games?",
      "Who's really tired and needs a rest?",
      "Pick my strongest fit XI for the next match.",
    ];
    if (f.kind === "player" && f.who) {
      const n = f.who.split(" ").slice(-1)[0];
      return [`Should ${n} start the next match?`, `Who should I bring in if I drop ${n}?`,
        `How is ${n} developing, and what should his training focus be?`, `Is ${n}'s form good enough to keep him in the XI?`, ...base.slice(0, 2)];
    }
    if (f.kind === "match") return ["Who underperformed in this match and why?", "Who was the standout player, and was it sustainable?",
      "What does this match say about changes for the next one?", ...base.slice(0, 3)];
    if (f.kind === "compare" && f.pair?.length === 2) return [`Who should start: ${f.pair[0]} or ${f.pair[1]}?`,
      `What are the key differences between ${f.pair[0]} and ${f.pair[1]}?`, ...base.slice(0, 3)];
    if (f.kind === "development") return ["Who has improved most, and why might that be?", "Who's declining and should I worry?",
      "Which youngsters should get more first-team minutes?", ...base.slice(0, 2)];
    return base;
  }

  // small, safe markdown: escape first, then bold/italic/code, bullet + numbered lists, tables, paragraphs
  function md(src) {
    const lines = escC(src).split("\n");
    let html = "", list = null, table = [];
    const inline = (s) => s.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
    const flushList = () => { if (list) { html += `</${list}>`; list = null; } };
    const flushTable = () => {
      if (!table.length) return;
      const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim())));
      html += `<div class="scroll"><table class="mdt"><thead><tr>${rows[0].map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`
        + rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>";
      table = [];
    };
    for (const raw of lines) {
      const l = raw.trimEnd();
      if (/^\s*\|.*\|\s*$/.test(l)) { flushList(); table.push(l.trim()); continue; }
      flushTable();
      let m;
      if ((m = l.match(/^\s*[-*•]\s+(.*)/))) { if (list !== "ul") { flushList(); html += "<ul>"; list = "ul"; } html += `<li>${inline(m[1])}</li>`; continue; }
      if ((m = l.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { flushList(); html += "<ol>"; list = "ol"; } html += `<li>${inline(m[1])}</li>`; continue; }
      flushList();
      if ((m = l.match(/^#{1,4}\s+(.*)/))) html += `<h4>${inline(m[1])}</h4>`;
      else if (l.trim()) html += `<p>${inline(l)}</p>`;
    }
    flushList(); flushTable();
    return html;
  }

  async function renderHistory() {
    const log = $c("#coachLog");
    log.innerHTML = '<div class="muted">Loading…</div>';
    const d = await fetch("/api/chats").then((r) => r.json()).catch(() => ({ conversations: [] }));
    log.innerHTML = `<div class="hist"><div class="histhead"><b>Saved conversations</b>
        <button type="button" class="chip" id="histNew">+ New conversation</button></div>
      ${d.conversations.length ? d.conversations.map((c) => `<div class="histrow ${c.id === convId ? "on" : ""}" data-id="${c.id}">
        <div class="histmain"><div>${escC(c.title || "Conversation")}</div><div class="muted small0">${escC(c.updated || "")} · ${c.messages} messages</div></div>
        <button type="button" class="iconbtn" data-del="${c.id}" title="Delete this conversation">✕</button></div>`).join("")
        : '<div class="muted">No saved conversations yet for this game snapshot.</div>'}</div>`;
    $c("#histNew").addEventListener("click", () => { msgs = []; setConv(null); showHistory = false; render(); });
    log.querySelectorAll(".histrow").forEach((row) => row.addEventListener("click", async (e) => {
      if (e.target.closest("[data-del]")) return;
      await loadConv(row.dataset.id); showHistory = false; render();
    }));
    log.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Delete this conversation?")) return;
      await fetch(`/api/chats/${b.dataset.del}`, { method: "DELETE" });
      if (b.dataset.del === convId) { msgs = []; setConv(null); }
      renderHistory();
    }));
  }

  function render() {
    const log = $c("#coachLog");
    $c("#coachFocus").textContent = "Focused on: " + focusLabel().text;
    if (showHistory) { renderHistory(); return; }
    if (!msgs.length) {
      log.innerHTML = `<div class="coachintro"><p>Ask me about your squad. I use the captured stats, focused on the page you're viewing.</p>
        <div class="chips">${suggestions().map((q) => `<button type="button" class="chip">${escC(q)}</button>`).join("")}</div></div>`;
      log.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => ask(b.textContent)));
      return;
    }
    log.innerHTML = msgs.map((m) => m.role === "user" ? `<div class="msg user">${escC(m.content)}</div>`
      : `<div class="msg assistant${m.error ? " err" : ""}">${m.status && !m.content ? `<span class="typing">🔎 ${escC(m.status)}…</span>` : ""}
          ${md(m.content) || (m.status ? "" : '<span class="typing">…</span>')}
          ${m.tools?.length || m.usage ? `<div class="msgmeta">${m.tools?.length ? `🔎 ${escC(m.tools.join(" · "))}<br>` : ""}${escC(usageText(m.usage))}</div>` : ""}</div>`).join("")
      + (busy ? "" : `<div class="chips after">${suggestions().slice(0, 3).map((q) => `<button type="button" class="chip">${escC(q)}</button>`).join("")}</div>`);
    log.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => ask(b.textContent)));
    log.scrollTop = log.scrollHeight;
  }

  async function ask(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true;
    $c("#coachSend").disabled = true;
    msgs.push({ role: "user", content: text });
    const reply = { role: "assistant", content: "" };
    msgs.push(reply);
    render();
    try {
      const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: page(), conversation_id: convId,
          messages: msgs.filter((m) => !m.error && m !== reply).map(({ role, content, usage, tools }) => ({ role, content, usage, tools })) }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const ev = buf.slice(0, i); buf = buf.slice(i + 2);
          const data = ev.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("");
          if (!data) continue;
          const e = JSON.parse(data);
          if (e.conversation) setConv(e.conversation);
          if (e.delta) { reply.content += e.delta; reply.status = null; render(); }
          if (e.tool) { reply.status = e.tool; (reply.tools = reply.tools || []).push(e.tool); render(); }
          if (e.usage) { reply.usage = e.usage; }
          if (e.error) { reply.content = e.error + "\n\nCheck **Settings › AI coach**."; reply.error = true; }
        }
      }
      if (!reply.content) { reply.content = "No answer came back. Try again."; reply.error = true; }
    } catch (err) {
      reply.content = `Couldn't reach the coach: ${err.message}`; reply.error = true;
    }
    reply.status = null;
    busy = false;
    $c("#coachSend").disabled = false;
    render();
  }

  async function provider() {
    try {
      const s = await fetch("/api/llm/status").then((r) => r.json());
      const el = $c("#coachProvider");
      el.textContent = s.label;
      el.title = s.detail || "";
      el.className = "pill" + (s.ready ? "" : " down");
    } catch { /* backend down: chat shows the error on send */ }
  }

  async function open() {
    $c("#coach").classList.remove("hidden"); $c("#coachBtn").classList.add("hidden"); provider();
    if (!msgs.length && convId) await loadConv(convId);      // reopen the last conversation, even after a restart
    render(); $c("#coachInput").focus();
  }
  function close() { $c("#coach").classList.add("hidden"); $c("#coachBtn").classList.remove("hidden"); }

  $c("#coachBtn").addEventListener("click", open);
  $c("#coachClose").addEventListener("click", close);
  $c("#coachClear").addEventListener("click", () => { if (busy) return; msgs = []; setConv(null); showHistory = false; render(); });
  $c("#coachHist").addEventListener("click", () => { if (busy) return; showHistory = !showHistory; render(); });
  $c("#coachData").addEventListener("click", async () => {
    const d = await fetch(`/api/chat/context?page=${encodeURIComponent(page())}`).then((r) => r.json());
    const w = window.open("", "_blank", "width=900,height=700");
    if (w) { w.document.title = "Data sent to the coach"; w.document.body.innerHTML = `<pre style="white-space:pre-wrap;font:12px Consolas,monospace">${escC(d.context)}</pre>`; }
  });
  $c("#coachForm").addEventListener("submit", (e) => { e.preventDefault(); const t = $c("#coachInput").value; $c("#coachInput").value = ""; ask(t); });
  $c("#coachInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $c("#coachForm").requestSubmit(); } });
  addEventListener("hashchange", () => setTimeout(() => { if (!$c("#coach").classList.contains("hidden")) render(); }, 400));
  addEventListener("keydown", (e) => { if (e.key === "Escape" && !$c("#coach").classList.contains("hidden")) close(); });
})();
