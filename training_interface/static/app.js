/* Meta-Harness Training Interface — Frontend Application */

(function () {
    "use strict";

    // ── Helpers ──────────────────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    async function api(url, opts = {}) {
        const resp = await fetch(url, {
            headers: { "Content-Type": "application/json", ...opts.headers },
            ...opts,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || resp.statusText);
        }
        return resp.json();
    }

    function formatBytes(bytes) {
        if (!bytes) return "—";
        const gb = bytes / (1024 ** 3);
        if (gb >= 1) return gb.toFixed(1) + " GB";
        const mb = bytes / (1024 ** 2);
        return mb.toFixed(0) + " MB";
    }

    function formatTime(ts) {
        if (!ts) return "—";
        return new Date(ts * 1000).toLocaleString();
    }

    function badgeClass(status) {
        const map = { pass: "badge-pass", partial: "badge-partial", fail: "badge-fail", running: "badge-running", completed: "badge-pass", pending: "badge-pending", failed: "badge-fail" };
        return map[status] || "badge-pending";
    }

    function scoreColor(score) {
        if (score >= 0.8) return "var(--success)";
        if (score >= 0.5) return "var(--warning)";
        return "var(--danger)";
    }

    // ── Tab navigation ──────────────────────────────────────────────────
    $$(".tab").forEach((btn) => {
        btn.addEventListener("click", () => {
            $$(".tab").forEach((b) => b.classList.remove("active"));
            $$(".tab-content").forEach((s) => s.classList.remove("active"));
            btn.classList.add("active");
            const target = btn.dataset.tab;
            $(`#tab-${target}`).classList.add("active");
            // Refresh data when switching tabs
            if (target === "models") loadModels();
            if (target === "training") { loadSessions(); loadModelsForSelects(); loadTasksForSelect(); }
            if (target === "knowledge") loadKB();
            if (target === "chat") loadModelsForSelects();
            if (target === "dashboard") loadDashboard();
        });
    });

    // ── Dashboard ───────────────────────────────────────────────────────
    async function loadDashboard() {
        try {
            const status = await api("/api/status");
            $("#stat-models").textContent = "—";
            $("#stat-sessions").textContent = status.sessions_total;
            $("#stat-completed").textContent = status.sessions_completed;
            $("#stat-kb").textContent = status.knowledge_base.total_items;

            const dot = $("#status-indicator");
            if (status.ollama_available) {
                dot.classList.remove("offline");
                dot.classList.add("online");
                dot.title = "Ollama: connected";
                // Also load model count
                try {
                    const m = await api("/api/models");
                    $("#stat-models").textContent = m.models.length;
                } catch (_) { /* ignore */ }
            } else {
                dot.classList.remove("online");
                dot.classList.add("offline");
                dot.title = "Ollama: disconnected";
            }

            // Recent sessions
            const sessData = await api("/api/sessions?limit=5");
            const container = $("#recent-sessions");
            if (!sessData.sessions.length) {
                container.innerHTML = '<p class="muted">No sessions yet. Start training!</p>';
                return;
            }
            container.innerHTML = sessData.sessions.map((s) => `
                <div class="list-item" onclick="window._viewSession('${s.id}')">
                    <div class="list-item-main">
                        <div class="list-item-title">${s.model_name || "Unknown model"}</div>
                        <div class="list-item-sub">${formatTime(s.created_at)} · Score: ${(s.best_score * 100).toFixed(0)}%</div>
                    </div>
                    <span class="badge ${badgeClass(s.status)}">${s.status}</span>
                </div>
            `).join("");
        } catch (e) {
            console.error("Dashboard error:", e);
        }
    }

    // ── Models ──────────────────────────────────────────────────────────
    async function loadModels() {
        const container = $("#models-list");
        try {
            const data = await api("/api/models");
            if (!data.models.length) {
                container.innerHTML = '<p class="muted">No models installed. Pull one to get started.</p>';
                return;
            }
            container.innerHTML = data.models.map((m) => `
                <div class="list-item">
                    <div class="list-item-main">
                        <div class="list-item-title">${m.name}</div>
                        <div class="list-item-sub">${formatBytes(m.size)} · ${m.parameter_size || "?"} params · ${m.quantization || "?"} · ${m.family || ""}</div>
                    </div>
                    <div class="list-item-actions">
                        <button class="btn btn-small btn-danger" onclick="window._deleteModel('${m.name}')">Delete</button>
                    </div>
                </div>
            `).join("");
        } catch (e) {
            container.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
        }
    }

    async function loadModelsForSelects() {
        try {
            const data = await api("/api/models");
            const options = data.models.map((m) => `<option value="${m.name}">${m.name} (${formatBytes(m.size)})</option>`).join("");
            const empty = '<option value="">Select model...</option>';
            ["#session-model-kb", "#session-model-custom", "#chat-model"].forEach((sel) => {
                const el = $(sel);
                if (el) el.innerHTML = empty + options;
            });
        } catch (_) { /* ignore */ }
    }

    window._deleteModel = async function (name) {
        if (!confirm(`Delete model "${name}"?`)) return;
        try {
            await api(`/api/models/${encodeURIComponent(name)}`, { method: "DELETE" });
            loadModels();
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    $("#btn-refresh-models").addEventListener("click", loadModels);

    $("#btn-pull-model").addEventListener("click", async () => {
        const name = $("#pull-model-name").value.trim();
        if (!name) return alert("Enter a model name");

        const progressEl = $("#pull-progress");
        const fillEl = $("#pull-fill");
        const statusEl = $("#pull-status-text");
        progressEl.classList.remove("hidden");
        fillEl.style.width = "0%";
        statusEl.textContent = "Starting pull...";

        try {
            const resp = await fetch("/api/models/pull", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
            });

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });

                const lines = buffer.split("\n");
                buffer = lines.pop() || "";

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.done) {
                            statusEl.textContent = "Done!";
                            fillEl.style.width = "100%";
                            setTimeout(() => progressEl.classList.add("hidden"), 2000);
                            loadModels();
                            loadModelsForSelects();
                            return;
                        }
                        if (data.error) {
                            statusEl.textContent = "Error: " + data.error;
                            return;
                        }
                        statusEl.textContent = data.status + (data.percent ? ` (${data.percent}%)` : "");
                        if (data.percent) fillEl.style.width = data.percent + "%";
                    } catch (_) { /* skip bad lines */ }
                }
            }
        } catch (e) {
            statusEl.textContent = "Error: " + e.message;
        }
    });

    // ── Training Sessions ───────────────────────────────────────────────
    async function loadSessions() {
        const container = $("#sessions-list");
        try {
            const data = await api("/api/sessions?limit=50");
            if (!data.sessions.length) {
                container.innerHTML = '<p class="muted">No training sessions yet.</p>';
                return;
            }
            container.innerHTML = data.sessions.map((s) => `
                <div class="list-item" onclick="window._viewSession('${s.id}')">
                    <div class="list-item-main">
                        <div class="list-item-title">${s.model_name || "Unknown"}</div>
                        <div class="list-item-sub">${formatTime(s.created_at)} · Best: ${(s.best_score * 100).toFixed(0)}%</div>
                    </div>
                    <div class="list-item-actions">
                        <span class="badge ${badgeClass(s.status)}">${s.status}</span>
                        <button class="btn btn-small btn-danger" onclick="event.stopPropagation(); window._deleteSession('${s.id}')">Delete</button>
                    </div>
                </div>
            `).join("");
        } catch (e) {
            container.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
        }
    }

    async function loadTasksForSelect() {
        try {
            const data = await api("/api/kb?kind=task");
            const select = $("#kb-task-select");
            select.innerHTML = '<option value="">Select a task...</option>' +
                data.items.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
        } catch (_) { /* ignore */ }
    }

    // Toggle new session form
    $("#btn-new-session").addEventListener("click", () => {
        const form = $("#new-session-form");
        form.classList.toggle("hidden");
        if (!form.classList.contains("hidden")) {
            loadModelsForSelects();
            loadTasksForSelect();
        }
    });

    // Form tabs (KB vs Custom)
    $$(".form-tab").forEach((btn) => {
        btn.addEventListener("click", () => {
            $$(".form-tab").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            const target = btn.dataset.form;
            $$("#new-session-form .form-section").forEach((s) => s.classList.add("hidden"));
            $(`#form-${target}`).classList.remove("hidden");
        });
    });

    // Start KB session
    $("#btn-start-kb-session").addEventListener("click", async () => {
        const taskId = $("#kb-task-select").value;
        const model = $("#session-model-kb").value;
        if (!taskId || !model) return alert("Select a task and model");

        try {
            await api("/api/sessions/start", {
                method: "POST",
                body: JSON.stringify({
                    task_id: taskId,
                    model: model,
                    max_iterations: parseInt($("#session-max-iter-kb").value) || 5,
                    temperature: parseFloat($("#session-temp-kb").value) || 0.7,
                }),
            });
            $("#new-session-form").classList.add("hidden");
            // Poll for updates
            setTimeout(loadSessions, 1000);
            setTimeout(loadSessions, 5000);
            setTimeout(loadSessions, 15000);
            alert("Training session started! It will appear in the list shortly.");
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    // Start custom session
    $("#btn-start-custom-session").addEventListener("click", async () => {
        const model = $("#session-model-custom").value;
        const instruction = $("#custom-instruction").value.trim();
        if (!model || !instruction) return alert("Select a model and enter an instruction");

        const criteria = $("#custom-criteria").value.trim().split("\n").filter(Boolean);

        try {
            await api("/api/sessions/start-custom", {
                method: "POST",
                body: JSON.stringify({
                    title: $("#custom-title").value.trim() || "Custom Task",
                    instruction: instruction,
                    expected_behavior: $("#custom-expected").value.trim(),
                    evaluation_criteria: criteria,
                    model: model,
                    max_iterations: parseInt($("#session-max-iter-custom").value) || 5,
                    temperature: parseFloat($("#session-temp-custom").value) || 0.7,
                }),
            });
            $("#new-session-form").classList.add("hidden");
            setTimeout(loadSessions, 1000);
            setTimeout(loadSessions, 5000);
            setTimeout(loadSessions, 15000);
            alert("Training session started!");
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    // View session detail
    window._viewSession = async function (id) {
        try {
            const s = await api(`/api/sessions/${id}`);
            const panel = $("#session-detail");
            panel.classList.remove("hidden");
            $("#session-detail-title").textContent = `Session: ${s.model_name} — ${s.task.title || "Custom"}`;

            let html = `
                <div style="margin-bottom:12px">
                    <span class="badge ${badgeClass(s.status)}">${s.status}</span>
                    <span style="margin-left:12px">Best score: <strong>${(s.best_score * 100).toFixed(0)}%</strong></span>
                    <span style="margin-left:12px">Improvement: <strong>${(s.improvement * 100).toFixed(0)}%</strong></span>
                </div>
                <div style="margin-bottom:12px;color:var(--text-muted);font-size:0.85rem">
                    <strong>Task:</strong> ${s.task.instruction.substring(0, 200)}${s.task.instruction.length > 200 ? "..." : ""}
                </div>
            `;

            for (const a of s.attempts) {
                html += `
                    <div class="attempt-card">
                        <div class="attempt-header">
                            <span><strong>Attempt #${a.attempt_number}</strong></span>
                            <span>
                                <span class="badge ${badgeClass(a.verdict)}">${a.verdict}</span>
                                Score: ${(a.score * 100).toFixed(0)}%
                                <span class="score-bar"><span class="score-fill" style="width:${a.score * 100}%;background:${scoreColor(a.score)}"></span></span>
                                · ${a.duration_sec.toFixed(1)}s
                            </span>
                        </div>
                        <div class="attempt-response">${escapeHtml(a.model_response)}</div>
                        ${a.errors.length ? `<div class="attempt-errors"><strong>Errors:</strong><ul>${a.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul></div>` : ""}
                    </div>
                `;
            }

            $("#session-detail-body").innerHTML = html;
        } catch (e) {
            alert("Error loading session: " + e.message);
        }
    };

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    $("#btn-close-detail").addEventListener("click", () => {
        $("#session-detail").classList.add("hidden");
    });

    window._deleteSession = async function (id) {
        if (!confirm("Delete this session?")) return;
        try {
            await api(`/api/sessions/${id}`, { method: "DELETE" });
            loadSessions();
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    // ── Knowledge Base ──────────────────────────────────────────────────
    async function loadKB() {
        const kind = $("#kb-filter-kind").value || undefined;
        const container = $("#kb-list");
        try {
            let url = "/api/kb";
            if (kind) url += `?kind=${kind}`;
            const data = await api(url);
            if (!data.items.length) {
                container.innerHTML = '<p class="muted">No items in knowledge base.</p>';
                return;
            }
            container.innerHTML = data.items.map((item) => `
                <div class="list-item">
                    <div class="list-item-main">
                        <div class="list-item-title">${item.name} <span class="tag">${item.kind}</span></div>
                        <div class="list-item-sub">${item.tags.map((t) => `<span class="tag">${t}</span>`).join(" ")}</div>
                    </div>
                    <div class="list-item-actions">
                        <button class="btn btn-small btn-danger" onclick="window._deleteKBItem('${item.id}')">Delete</button>
                    </div>
                </div>
            `).join("");
        } catch (e) {
            container.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
        }
    }

    $("#kb-filter-kind").addEventListener("change", loadKB);

    // Add task form
    $("#btn-add-task").addEventListener("click", () => {
        $("#add-task-form").classList.toggle("hidden");
    });

    $("#btn-cancel-task").addEventListener("click", () => {
        $("#add-task-form").classList.add("hidden");
    });

    $("#btn-save-task").addEventListener("click", async () => {
        const title = $("#new-task-title").value.trim();
        const instruction = $("#new-task-instruction").value.trim();
        if (!title || !instruction) return alert("Title and instruction are required");

        const criteria = $("#new-task-criteria").value.trim().split("\n").filter(Boolean);
        const tags = $("#new-task-tags").value.trim().split(",").map((t) => t.trim()).filter(Boolean);

        try {
            await api("/api/kb/tasks", {
                method: "POST",
                body: JSON.stringify({
                    title,
                    instruction,
                    expected_behavior: $("#new-task-expected").value.trim(),
                    evaluation_criteria: criteria,
                    difficulty: $("#new-task-difficulty").value,
                    tags,
                }),
            });
            $("#add-task-form").classList.add("hidden");
            loadKB();
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    window._deleteKBItem = async function (id) {
        if (!confirm("Delete this item?")) return;
        try {
            await api(`/api/kb/${id}`, { method: "DELETE" });
            loadKB();
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    // Export KB
    $("#btn-export-kb").addEventListener("click", () => {
        window.location.href = "/api/kb/export/archive";
    });

    // Import KB
    $("#import-kb-file").addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);

        try {
            const resp = await fetch("/api/kb/import/archive", {
                method: "POST",
                body: formData,
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || "Import failed");
            alert(`Imported ${data.imported} new items`);
            loadKB();
        } catch (err) {
            alert("Import error: " + err.message);
        }
        e.target.value = "";
    });

    // ── Chat ────────────────────────────────────────────────────────────
    const chatMessages = [];

    async function sendChat() {
        const model = $("#chat-model").value;
        const message = $("#chat-input").value.trim();
        if (!model || !message) return;

        chatMessages.push({ role: "user", content: message });
        renderChat();
        $("#chat-input").value = "";

        try {
            const data = await api("/api/chat", {
                method: "POST",
                body: JSON.stringify({ model, message }),
            });
            chatMessages.push({ role: "assistant", content: data.response });
            renderChat();
        } catch (e) {
            chatMessages.push({ role: "assistant", content: `Error: ${e.message}` });
            renderChat();
        }
    }

    function renderChat() {
        const container = $("#chat-messages");
        container.innerHTML = chatMessages.map((m) =>
            `<div class="chat-msg ${m.role}">${escapeHtml(m.content)}</div>`
        ).join("");
        container.scrollTop = container.scrollHeight;
    }

    $("#btn-send-chat").addEventListener("click", sendChat);
    $("#chat-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendChat();
        }
    });

    // ── Init ────────────────────────────────────────────────────────────
    loadDashboard();
})();
