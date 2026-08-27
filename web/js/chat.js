/* SensorSpine chat app — the entire UI is this conversation.
   Sends a message to /api/chat and renders the returned {text, blocks}. */
import { api } from "./api.js";
import { renderBlocks } from "./blocks.js";

const messagesEl = document.getElementById("messages");
const composer = document.getElementById("composer");
const input = document.getElementById("chat-input");
const suggestedEl = document.getElementById("suggested");
const badge = document.getElementById("llm-badge");

let history = [];

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function addMessage(role, contentNode) {
  const wrap = el(`<div class="msg ${role}"></div>`);
  const avatar = el(`<div class="avatar">${role === "user" ? "🧑" : "🤖"}</div>`);
  const bubble = el(`<div class="bubble"></div>`);
  bubble.appendChild(contentNode);
  wrap.append(avatar, bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

async function send(text) {
  text = (text || "").trim();
  if (!text) return;
  addMessage("user", el(`<div class="msg-text"></div>`)).textContent = text;
  history.push({ role: "user", content: text });
  const bubble = addMessage("assistant", el(`<div class="dots"><span>.</span><span>.</span><span>.</span></div>`));
  input.value = "";
  try {
    const r = await api.post("/chat", { message: text, history: history.slice(0, -1) });
    bubble.innerHTML = "";
    const txt = el(`<div class="msg-text"></div>`);
    txt.textContent = r.text || "";
    bubble.appendChild(txt);
    if (r.blocks && r.blocks.length) bubble.appendChild(renderBlocks(r.blocks));
    history.push({ role: "assistant", content: r.text || "" });
    updateBadge(r.engine);
  } catch (e) {
    bubble.textContent = "⚠️ " + (e && e.message ? e.message : String(e));
  }
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  send(input.value);
});

function updateBadge(engine) {
  if (!badge) return;
  const live = engine && engine !== "fallback";
  badge.textContent = live ? "AI · live LLM" : "AI · heuristic";
  badge.className = "sim-chip " + (live ? "ok" : "warn");
}

document.getElementById("theme-btn")?.addEventListener("click", () => {
  document.body.classList.toggle("light");
});

async function init() {
  try {
    const sec = await api.get("/chat/sections");
    (sec.sections || []).forEach((s) => {
      const chip = el(`<button class="chip" type="button">${s.title}</button>`);
      chip.addEventListener("click", () => send(s.q));
      suggestedEl.appendChild(chip);
    });
    updateBadge(sec.llm_enabled ? "llm" : "fallback");
  } catch (e) {
    console.warn("sections load failed", e);
  }
}

init();
