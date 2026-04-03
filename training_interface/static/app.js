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
            if (target === "projects") { loadProjects(); loadModelsForSelects(); loadBlueprintsForSelect(); }
            if (target === "knowledge") loadKB();
            if (target === "chat") loadModelsForSelects();
            if (target === "hub") loadModelsForSelects();
            if (target === "dashboard") loadDashboard();
            if (target === "admin") loadAdmin();
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
            // Load all models: local Ollama + external providers
            const data = await api("/api/models/all");
            const options = data.models.map((m) => `<option value="${m.ref}">${m.name} (${m.provider_name}${m.size_gb ? ', ' + m.size_gb + ' GB' : ''})</option>`).join("");
            const empty = '<option value="">Select model...</option>';
            ["#session-model-kb", "#session-model-custom", "#chat-model", "#project-model", "#hub-model", "#asm-model"].forEach((sel) => {
                const el = $(sel);
                if (el) el.innerHTML = empty + options;
            });
        } catch (_) {
            // Fallback to Ollama-only
            try {
                const data = await api("/api/models");
                const options = data.models.map((m) => `<option value="${m.name}">${m.name} (${formatBytes(m.size)})</option>`).join("");
                const empty = '<option value="">Select model...</option>';
                ["#session-model-kb", "#session-model-custom", "#chat-model", "#project-model", "#hub-model", "#asm-model"].forEach((sel) => {
                    const el = $(sel);
                    if (el) el.innerHTML = empty + options;
                });
            } catch (_2) { /* ignore */ }
        }
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

    // ── Projects ────────────────────────────────────────────────────────
    let _currentProjectId = null;

    async function loadBlueprintsForSelect() {
        try {
            const data = await api("/api/blueprints");
            const sel = $("#project-blueprint");
            if (sel) {
                sel.innerHTML = '<option value="">Select blueprint...</option>' +
                    data.blueprints.map((b) => `<option value="${b.id}">${b.name} (${b.language}/${b.framework})</option>`).join("");
            }
        } catch (_) { /* ignore */ }
    }

    async function loadProjects() {
        const container = $("#projects-list");
        try {
            const data = await api("/api/projects?limit=50");
            if (!data.projects.length) {
                container.innerHTML = '<p class="muted">No projects yet. Generate one from a blueprint!</p>';
                return;
            }
            container.innerHTML = data.projects.map((p) => `
                <div class="list-item" onclick="window._viewProject('${p.id}')">
                    <div class="list-item-main">
                        <div class="list-item-title">${p.name || "Untitled"}</div>
                        <div class="list-item-sub">${p.blueprint_name || ""} · ${p.model_name || ""} · ${formatTime(p.created_at)}${p.git_remote ? ' · Git: ' + p.git_remote : ''}</div>
                    </div>
                    <div class="list-item-actions">
                        <span class="badge ${badgeClass(p.status)}">${p.status}</span>
                        <button class="btn btn-small btn-danger" onclick="event.stopPropagation(); window._deleteProject('${p.id}')">Delete</button>
                    </div>
                </div>
            `).join("");
        } catch (e) {
            container.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
        }
    }

    $("#btn-new-project").addEventListener("click", () => {
        const form = $("#new-project-form");
        form.classList.toggle("hidden");
        if (!form.classList.contains("hidden")) {
            loadModelsForSelects();
            loadBlueprintsForSelect();
        }
    });

    $("#btn-cancel-project").addEventListener("click", () => {
        $("#new-project-form").classList.add("hidden");
    });

    // Blueprint preview
    $("#project-blueprint").addEventListener("change", async () => {
        const bpId = $("#project-blueprint").value;
        const preview = $("#blueprint-preview");
        if (!bpId) { preview.textContent = ""; return; }
        try {
            const bp = await api(`/api/blueprints/${bpId}`);
            preview.textContent = `${bp.description} — ${bp.files.length} files, ${bp.language}/${bp.framework}`;
        } catch (_) { preview.textContent = ""; }
    });

    $("#btn-generate-project").addEventListener("click", async () => {
        const bpId = $("#project-blueprint").value;
        const name = $("#project-name").value.trim();
        const model = $("#project-model").value;
        if (!bpId || !name || !model) return alert("Select blueprint, enter name, and select model");

        try {
            await api("/api/projects/generate", {
                method: "POST",
                body: JSON.stringify({
                    blueprint_id: bpId,
                    name: name,
                    model: model,
                    user_prompt: $("#project-prompt").value.trim(),
                }),
            });
            $("#new-project-form").classList.add("hidden");
            alert("Project generation started! Refresh in a few moments.");
            setTimeout(loadProjects, 2000);
            setTimeout(loadProjects, 10000);
            setTimeout(loadProjects, 30000);
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    window._viewProject = async function (id) {
        try {
            const p = await api(`/api/projects/${id}`);
            _currentProjectId = id;
            const panel = $("#project-detail");
            panel.classList.remove("hidden");
            $("#project-detail-title").textContent = p.name;

            let html = `
                <div style="margin-bottom:12px">
                    <span class="badge ${badgeClass(p.status)}">${p.status}</span>
                    <span style="margin-left:12px">${p.blueprint_name} · ${p.language}/${p.framework} · ${p.model_name}</span>
                    ${p.git_remote ? `<span style="margin-left:12px">Git: ${p.git_remote}</span>` : ''}
                </div>
            `;

            for (const f of p.files) {
                html += `
                    <div class="attempt-card">
                        <div class="attempt-header">
                            <span><strong>${f.path}</strong> ${f.generated ? '<span class="badge badge-pass">generated</span>' : '<span class="badge badge-pending">static</span>'}</span>
                            <span>${f.description}</span>
                        </div>
                        <div class="attempt-response">${escapeHtml(f.content || "(empty)")}</div>
                    </div>
                `;
            }

            $("#project-detail-body").innerHTML = html;
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    $("#btn-close-project").addEventListener("click", () => {
        $("#project-detail").classList.add("hidden");
        _currentProjectId = null;
    });

    $("#btn-export-project").addEventListener("click", async () => {
        if (!_currentProjectId) return;
        try {
            const data = await api(`/api/projects/${_currentProjectId}/export`, { method: "POST" });
            alert(`Exported ${data.file_count} files to: ${data.path}`);
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    $("#btn-sync-project").addEventListener("click", async () => {
        if (!_currentProjectId) return;
        try {
            const remotes = await api("/api/git/remotes");
            if (!remotes.remotes.length) {
                alert("No Git remotes configured. Add one in the Admin panel first.");
                return;
            }
            const remoteId = remotes.remotes[0].id;
            const repoName = prompt("Repository name:", "my-project");
            if (!repoName) return;

            const result = await api("/api/git/sync", {
                method: "POST",
                body: JSON.stringify({
                    project_id: _currentProjectId,
                    remote_id: remoteId,
                    repo_name: repoName,
                }),
            });
            if (result.success) {
                alert("Pushed to Git successfully!");
            } else {
                alert("Git sync failed: " + result.message);
            }
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    window._deleteProject = async function (id) {
        if (!confirm("Delete this project?")) return;
        try {
            await api(`/api/projects/${id}`, { method: "DELETE" });
            loadProjects();
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    // ── Admin Panel ────────────────────────────────────────────────────
    async function loadAdmin() {
        // Stats
        try {
            const data = await api("/api/admin/overview");
            $("#admin-sessions").textContent = data.sessions;
            $("#admin-projects").textContent = data.projects;
            $("#admin-blueprints").textContent = data.blueprints;
            $("#admin-kb").textContent = data.kb_items;
            $("#admin-remotes").textContent = data.git_remotes;
        } catch (_) { /* ignore */ }

        loadAdminRemotes();
        loadAdminProviders();
        loadAdminBlueprints();
        loadAdminKB();
    }

    // Git remotes
    async function loadAdminRemotes() {
        const container = $("#remotes-list");
        try {
            const data = await api("/api/git/remotes");
            if (!data.remotes.length) {
                container.innerHTML = '<p class="muted">No Git remotes configured.</p>';
                return;
            }
            container.innerHTML = data.remotes.map((r) => `
                <div class="list-item">
                    <div class="list-item-main">
                        <div class="list-item-title">${r.name} <span class="tag">${r.provider}</span></div>
                        <div class="list-item-sub">${r.owner} · Token: ${r.token}</div>
                    </div>
                    <div class="list-item-actions">
                        <button class="btn btn-small btn-danger" onclick="window._deleteRemote('${r.id}')">Delete</button>
                    </div>
                </div>
            `).join("");
        } catch (e) {
            container.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
        }
    }

    $("#btn-add-remote").addEventListener("click", () => {
        $("#add-remote-form").classList.toggle("hidden");
    });

    $("#btn-cancel-remote").addEventListener("click", () => {
        $("#add-remote-form").classList.add("hidden");
    });

    $("#btn-save-remote").addEventListener("click", async () => {
        const name = $("#remote-name").value.trim();
        const owner = $("#remote-owner").value.trim();
        if (!name || !owner) return alert("Name and owner are required");

        try {
            await api("/api/git/remotes", {
                method: "POST",
                body: JSON.stringify({
                    name: name,
                    provider: $("#remote-provider").value,
                    owner: owner,
                    token: $("#remote-token").value.trim(),
                    url_template: $("#remote-url-template").value.trim(),
                }),
            });
            $("#add-remote-form").classList.add("hidden");
            loadAdminRemotes();
            loadAdmin();
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    window._deleteRemote = async function (id) {
        if (!confirm("Delete this remote?")) return;
        try {
            await api(`/api/git/remotes/${id}`, { method: "DELETE" });
            loadAdminRemotes();
            loadAdmin();
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    // API Providers
    const _providerPresets = {
        xai: { name: "Z.ai / Grok (xAI)", base_url: "https://api.x.ai/v1", default_model: "grok-3-latest" },
        openai: { name: "OpenAI", base_url: "https://api.openai.com/v1", default_model: "gpt-4o" },
        anthropic: { name: "Anthropic (Claude)", base_url: "https://api.anthropic.com/v1", default_model: "claude-sonnet-4-20250514" },
        google: { name: "Google (Gemini)", base_url: "https://generativelanguage.googleapis.com/v1beta/openai", default_model: "gemini-2.0-flash" },
        deepseek: { name: "DeepSeek", base_url: "https://api.deepseek.com", default_model: "deepseek-chat" },
        custom: { name: "", base_url: "", default_model: "" },
    };

    async function loadAdminProviders() {
        const container = $("#providers-list");
        try {
            const data = await api("/api/providers");
            if (!data.providers.length) {
                container.innerHTML = '<p class="muted">No API providers configured. Add one to use online models.</p>';
                return;
            }
            container.innerHTML = data.providers.map((p) => `
                <div class="list-item">
                    <div class="list-item-main">
                        <div class="list-item-title">${p.name} <span class="tag">${p.provider_type}</span> ${p.enabled ? '<span class="badge badge-pass">active</span>' : '<span class="badge badge-fail">disabled</span>'}</div>
                        <div class="list-item-sub">Model: ${p.default_model} · Key: ${p.api_key}</div>
                    </div>
                    <div class="list-item-actions">
                        <button class="btn btn-small" onclick="window._testProvider('${p.id}')">Test</button>
                        <button class="btn btn-small btn-danger" onclick="window._deleteProvider('${p.id}')">Delete</button>
                    </div>
                </div>
            `).join("");
        } catch (e) {
            container.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
        }
    }

    $("#btn-add-provider").addEventListener("click", () => {
        $("#add-provider-form").classList.toggle("hidden");
        // Auto-fill from preset
        const type = $("#provider-type").value;
        const preset = _providerPresets[type] || {};
        $("#provider-base-url").value = preset.base_url || "";
        $("#provider-default-model").value = preset.default_model || "";
    });

    $("#btn-cancel-provider").addEventListener("click", () => {
        $("#add-provider-form").classList.add("hidden");
    });

    // Auto-fill when provider type changes
    $("#provider-type").addEventListener("change", () => {
        const type = $("#provider-type").value;
        const preset = _providerPresets[type] || {};
        $("#provider-base-url").value = preset.base_url || "";
        $("#provider-default-model").value = preset.default_model || "";
        if (!$("#provider-name").value.trim()) {
            $("#provider-name").value = preset.name || "";
        }
    });

    $("#btn-save-provider").addEventListener("click", async () => {
        const apiKey = $("#provider-api-key").value.trim();
        if (!apiKey) return alert("API key is required");

        const models = $("#provider-models").value.trim().split(",").map((s) => s.trim()).filter(Boolean);

        try {
            await api("/api/providers", {
                method: "POST",
                body: JSON.stringify({
                    provider_type: $("#provider-type").value,
                    name: $("#provider-name").value.trim(),
                    base_url: $("#provider-base-url").value.trim(),
                    api_key: apiKey,
                    default_model: $("#provider-default-model").value.trim(),
                    models: models,
                }),
            });
            $("#add-provider-form").classList.add("hidden");
            loadAdminProviders();
            loadAdmin();
            alert("Provider saved! Its models will now appear in all model selectors.");
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    window._testProvider = async function (id) {
        try {
            const result = await api(`/api/providers/${id}/test`, { method: "POST" });
            alert(result.success ? "Connection OK: " + result.message : "Failed: " + result.message);
        } catch (e) {
            alert("Test failed: " + e.message);
        }
    };

    window._deleteProvider = async function (id) {
        if (!confirm("Delete this provider?")) return;
        try {
            await api(`/api/providers/${id}`, { method: "DELETE" });
            loadAdminProviders();
            loadAdmin();
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    // Admin blueprints
    async function loadAdminBlueprints() {
        const container = $("#admin-blueprints-list");
        try {
            const data = await api("/api/blueprints");
            if (!data.blueprints.length) {
                container.innerHTML = '<p class="muted">No blueprints.</p>';
                return;
            }
            container.innerHTML = data.blueprints.map((b) => `
                <div class="list-item" onclick="window._editBlueprint('${b.id}')">
                    <div class="list-item-main">
                        <div class="list-item-title">${b.name} <span class="tag">${b.category}</span></div>
                        <div class="list-item-sub">${b.language}/${b.framework} · ${b.file_count} files · ${b.tags.map((t) => '<span class="tag">' + t + '</span>').join(" ")}</div>
                    </div>
                    <div class="list-item-actions">
                        <button class="btn btn-small">Edit</button>
                        <button class="btn btn-small btn-danger" onclick="event.stopPropagation(); window._deleteBlueprint('${b.id}')">Delete</button>
                    </div>
                </div>
            `).join("");
        } catch (e) {
            container.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
        }
    }

    window._editBlueprint = async function (id) {
        try {
            const bp = await api(`/api/blueprints/${id}`);
            const modal = $("#edit-modal");
            modal.classList.remove("hidden");
            $("#edit-modal-title").textContent = `Edit Blueprint: ${bp.name}`;
            modal.dataset.editType = "blueprint";
            modal.dataset.editId = id;

            $("#edit-modal-body").innerHTML = `
                <label>Name:</label><input type="text" id="edit-bp-name" class="input-wide" value="${escapeHtml(bp.name)}">
                <label>Category:</label><input type="text" id="edit-bp-category" class="input-wide" value="${escapeHtml(bp.category)}">
                <label>Description:</label><textarea id="edit-bp-desc" rows="2" class="input-wide">${escapeHtml(bp.description)}</textarea>
                <label>Language:</label><input type="text" id="edit-bp-lang" class="input-wide" value="${escapeHtml(bp.language)}">
                <label>Framework:</label><input type="text" id="edit-bp-fw" class="input-wide" value="${escapeHtml(bp.framework)}">
                <label>System Prompt:</label><textarea id="edit-bp-prompt" rows="4" class="input-wide">${escapeHtml(bp.system_prompt)}</textarea>
                <label>Tags (comma-separated):</label><input type="text" id="edit-bp-tags" class="input-wide" value="${bp.tags.join(", ")}">
                <label>Dependencies (comma-separated):</label><input type="text" id="edit-bp-deps" class="input-wide" value="${bp.dependencies.join(", ")}">
                <label>Run Command:</label><input type="text" id="edit-bp-run" class="input-wide" value="${escapeHtml(bp.run_command)}">
            `;
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    window._deleteBlueprint = async function (id) {
        if (!confirm("Delete this blueprint?")) return;
        try {
            await api(`/api/blueprints/${id}`, { method: "DELETE" });
            loadAdminBlueprints();
            loadAdmin();
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    // Admin KB items
    async function loadAdminKB() {
        const container = $("#admin-kb-list");
        try {
            const data = await api("/api/kb");
            if (!data.items.length) {
                container.innerHTML = '<p class="muted">No KB items.</p>';
                return;
            }
            container.innerHTML = data.items.map((item) => `
                <div class="list-item" onclick="window._editKBItem('${item.id}')">
                    <div class="list-item-main">
                        <div class="list-item-title">${item.name} <span class="tag">${item.kind}</span></div>
                        <div class="list-item-sub">${item.tags.map((t) => '<span class="tag">' + t + '</span>').join(" ")}</div>
                    </div>
                    <div class="list-item-actions">
                        <button class="btn btn-small">Edit</button>
                        <button class="btn btn-small btn-danger" onclick="event.stopPropagation(); window._deleteKBItem('${item.id}')">Delete</button>
                    </div>
                </div>
            `).join("");
        } catch (e) {
            container.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
        }
    }

    window._editKBItem = async function (id) {
        try {
            const item = await api(`/api/kb/${id}`);
            const modal = $("#edit-modal");
            modal.classList.remove("hidden");
            $("#edit-modal-title").textContent = `Edit: ${item.title || item.name || id}`;
            modal.dataset.editType = "kb";
            modal.dataset.editId = id;

            // Build editable fields from the item's keys
            let fields = "";
            for (const [key, val] of Object.entries(item)) {
                if (key === "id") continue;
                if (Array.isArray(val)) {
                    fields += `<label>${key}:</label><input type="text" class="input-wide edit-field" data-key="${key}" value="${val.join(", ")}">`;
                } else if (typeof val === "string" && val.length > 100) {
                    fields += `<label>${key}:</label><textarea rows="4" class="input-wide edit-field" data-key="${key}">${escapeHtml(val)}</textarea>`;
                } else {
                    fields += `<label>${key}:</label><input type="text" class="input-wide edit-field" data-key="${key}" value="${escapeHtml(String(val))}">`;
                }
            }
            $("#edit-modal-body").innerHTML = fields;
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    // Save edit modal
    $("#btn-save-edit").addEventListener("click", async () => {
        const modal = $("#edit-modal");
        const editType = modal.dataset.editType;
        const editId = modal.dataset.editId;

        try {
            if (editType === "blueprint") {
                const tags = $("#edit-bp-tags").value.split(",").map((t) => t.trim()).filter(Boolean);
                const deps = $("#edit-bp-deps").value.split(",").map((t) => t.trim()).filter(Boolean);
                await api(`/api/admin/blueprints/${editId}`, {
                    method: "PUT",
                    body: JSON.stringify({
                        name: $("#edit-bp-name").value.trim(),
                        category: $("#edit-bp-category").value.trim(),
                        description: $("#edit-bp-desc").value.trim(),
                        language: $("#edit-bp-lang").value.trim(),
                        framework: $("#edit-bp-fw").value.trim(),
                        system_prompt: $("#edit-bp-prompt").value.trim(),
                        tags: tags,
                        dependencies: deps,
                        run_command: $("#edit-bp-run").value.trim(),
                    }),
                });
                loadAdminBlueprints();
            } else if (editType === "kb") {
                const data = {};
                $$("#edit-modal-body .edit-field").forEach((el) => {
                    const key = el.dataset.key;
                    let val = el.value;
                    // Try to parse arrays
                    if (val.includes(",") && !val.includes("\n")) {
                        const arr = val.split(",").map((s) => s.trim()).filter(Boolean);
                        if (arr.length > 1 || (arr.length === 1 && val.includes(","))) {
                            data[key] = arr;
                            return;
                        }
                    }
                    data[key] = val;
                });
                await api(`/api/admin/kb/${editId}`, {
                    method: "PUT",
                    body: JSON.stringify({ data }),
                });
                loadAdminKB();
            }
            modal.classList.add("hidden");
            alert("Saved!");
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    $("#btn-close-edit").addEventListener("click", () => {
        $("#edit-modal").classList.add("hidden");
    });

    // ── AI Hub — Response Checker ──────────────────────────────────────
    $("#btn-hub-check").addEventListener("click", async () => {
        const responseText = $("#hub-response").value.trim();
        const model = $("#hub-model").value;
        if (!responseText) return alert("Paste an AI response to check");
        if (!model) return alert("Select a model for checking");

        $("#btn-hub-check").textContent = "Checking...";
        $("#btn-hub-check").disabled = true;
        $("#hub-results").classList.add("hidden");

        try {
            const data = await api("/api/hub/check", {
                method: "POST",
                body: JSON.stringify({
                    response_text: responseText,
                    context: $("#hub-context").value.trim(),
                    check_type: $("#hub-check-type").value,
                    model: model,
                }),
            });

            // Show results
            $("#hub-results").classList.remove("hidden");

            // Score badge
            const scoreBadge = $("#hub-score-badge");
            if (data.score >= 8) {
                scoreBadge.className = "badge badge-pass";
                scoreBadge.textContent = `Score: ${data.score}/10`;
            } else if (data.score >= 5) {
                scoreBadge.className = "badge badge-partial";
                scoreBadge.textContent = `Score: ${data.score}/10`;
            } else {
                scoreBadge.className = "badge badge-fail";
                scoreBadge.textContent = data.score >= 0 ? `Score: ${data.score}/10` : "Could not score";
            }

            // Summary
            $("#hub-summary").textContent = data.summary || "";

            // Errors
            if (data.errors && data.errors.length) {
                $("#hub-errors-section").classList.remove("hidden");
                $("#hub-errors-list").innerHTML = data.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("");
            } else {
                $("#hub-errors-section").classList.add("hidden");
            }

            // Warnings
            if (data.warnings && data.warnings.length) {
                $("#hub-warnings-section").classList.remove("hidden");
                $("#hub-warnings-list").innerHTML = data.warnings.map((w) => `<li style="color:var(--warning)">${escapeHtml(w)}</li>`).join("");
            } else {
                $("#hub-warnings-section").classList.add("hidden");
            }

            // Corrected version
            $("#hub-corrected").textContent = data.corrected || "(no corrections needed)";

        } catch (e) {
            alert("Error: " + e.message);
        } finally {
            $("#btn-hub-check").textContent = "Check & Fix";
            $("#btn-hub-check").disabled = false;
        }
    });

    // Copy corrected text
    $("#btn-hub-copy").addEventListener("click", () => {
        const text = $("#hub-corrected").textContent;
        if (text && navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                $("#btn-hub-copy").textContent = "Copied!";
                setTimeout(() => { $("#btn-hub-copy").textContent = "Copy Corrected"; }, 2000);
            });
        }
    });

    // ── AI Hub — Code Assembler ────────────────────────────────────────
    let _lastAssembledProjectId = null;

    $("#btn-asm-assemble").addEventListener("click", async () => {
        const code = $("#asm-code").value.trim();
        const name = $("#asm-name").value.trim();
        const model = $("#asm-model").value;
        if (!code) return alert("Paste the AI code output");
        if (!name) return alert("Enter a project name");
        if (!model) return alert("Select a model");

        $("#btn-asm-assemble").textContent = "Assembling...";
        $("#btn-asm-assemble").disabled = true;
        $("#asm-result").classList.add("hidden");

        try {
            const data = await api("/api/hub/assemble", {
                method: "POST",
                body: JSON.stringify({
                    raw_code: code,
                    project_name: name,
                    model: model,
                    instructions: $("#asm-instructions").value.trim(),
                }),
            });

            _lastAssembledProjectId = data.project_id;
            $("#asm-result").classList.remove("hidden");
            $("#asm-result-title").textContent = `${data.name} (${data.file_count} files)`;
            $("#asm-result-info").textContent = `${data.language} · ${data.description}`;
            $("#asm-result-files").innerHTML = data.files.map((f) =>
                `<div class="list-item"><div class="list-item-main"><div class="list-item-title">${f}</div></div></div>`
            ).join("");

        } catch (e) {
            alert("Error: " + e.message);
        } finally {
            $("#btn-asm-assemble").textContent = "Assemble Project";
            $("#btn-asm-assemble").disabled = false;
        }
    });

    $("#btn-asm-view").addEventListener("click", () => {
        if (!_lastAssembledProjectId) return;
        // Switch to Projects tab and open this project
        $$(".tab").forEach((b) => b.classList.remove("active"));
        $$(".tab-content").forEach((s) => s.classList.remove("active"));
        document.querySelector('[data-tab="projects"]').classList.add("active");
        $("#tab-projects").classList.add("active");
        loadProjects();
        window._viewProject(_lastAssembledProjectId);
    });

    $("#btn-asm-push").addEventListener("click", async () => {
        if (!_lastAssembledProjectId) return;
        try {
            const remotes = await api("/api/git/remotes");
            if (!remotes.remotes.length) {
                alert("No Git remotes configured. Add one in Admin panel first.");
                return;
            }
            const remoteId = remotes.remotes[0].id;
            const repoName = prompt("Repository name for GitHub:", $("#asm-name").value.trim().replace(/\s+/g, "-").toLowerCase() || "my-project");
            if (!repoName) return;

            const result = await api(`/api/hub/assemble/${_lastAssembledProjectId}/push?remote_id=${remoteId}&repo_name=${encodeURIComponent(repoName)}`, {
                method: "POST",
            });

            if (result.git_sync && result.git_sync.success) {
                alert("Pushed to GitHub successfully!");
            } else if (result.git_sync) {
                alert("Git push failed: " + result.git_sync.message);
            } else {
                alert("Exported to disk: " + result.exported + "\nAdd a Git remote in Admin to push.");
            }
        } catch (e) {
            alert("Error: " + e.message);
        }
    });

    // ── Init ────────────────────────────────────────────────────────────
    loadDashboard();
})();
