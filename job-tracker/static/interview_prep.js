(function () {
    const page = document.body.dataset.page;
    const state = {
        userId: document.body.dataset.userId || "",
        jobPostingId: document.body.dataset.jobPostingId || "",
        sessionId: null,
        lastInterviewerText: "",
        recognition: null,
        recognizing: false,
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function escapeHtml(value) {
        return String(value || "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    async function api(path, options) {
        const response = await fetch(path, {
            headers: { "Content-Type": "application/json" },
            ...options,
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || "Request failed");
        }
        return payload;
    }

    function setStatus(message, isError) {
        const target = byId("prepStatus");
        if (!target) return;
        target.textContent = message || "";
        target.classList.toggle("error", Boolean(isError));
    }

    function readTarget() {
        const userInput = byId("prepUserId");
        const jobInput = byId("prepJobId");
        state.userId = userInput ? userInput.value.trim() : state.userId;
        state.jobPostingId = jobInput ? jobInput.value.trim() : state.jobPostingId;
        return Boolean(state.userId && state.jobPostingId);
    }

    function renderList(items) {
        if (!items || !items.length) return "<p class=\"muted\">Nothing listed yet.</p>";
        return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
    }

    function renderBrief(payload) {
        const briefRecord = payload.brief || {};
        const brief = briefRecord.brief_json || {};
        const output = byId("briefOutput");
        const mode = byId("researchMode");
        const sourcesOutput = byId("sourcesOutput");

        if (mode) {
            mode.textContent = brief.research ? brief.research.mode : briefRecord.research_mode || "";
        }

        if (output) {
            const process = brief.likely_process || [];
            const questions = brief.likely_questions || [];
            const positioning = brief.candidate_positioning || {};
            output.innerHTML = `
                <div>
                    <h3>Summary</h3>
                    <p>${escapeHtml(brief.summary || "No summary yet.")}</p>
                </div>
                <div>
                    <h3>Core Skills</h3>
                    ${renderList((brief.role_context || {}).core_skills || [])}
                </div>
                <div>
                    <h3>Likely Process</h3>
                    ${process.map((item) => `
                        <div class="question-item">
                            <strong>${escapeHtml(item.stage)}</strong>
                            <p>${escapeHtml(item.what_to_expect)}</p>
                            <p class="muted">${escapeHtml(item.prep_notes)}</p>
                        </div>
                    `).join("") || "<p class=\"muted\">No process notes yet.</p>"}
                </div>
                <div>
                    <h3>Likely Questions</h3>
                    ${questions.map((item) => `
                        <div class="question-item">
                            <strong>${escapeHtml(item.category)}</strong>
                            <p>${escapeHtml(item.question)}</p>
                            <p class="muted">${escapeHtml(item.why_it_matters)}</p>
                        </div>
                    `).join("") || "<p class=\"muted\">No questions yet.</p>"}
                </div>
                <div>
                    <h3>Positioning</h3>
                    <p><strong>Strengths</strong></p>
                    ${renderList(positioning.strengths_to_emphasize || [])}
                    <p><strong>Gaps</strong></p>
                    ${renderList(positioning.gaps_to_prepare || [])}
                    <p><strong>Stories</strong></p>
                    ${renderList(positioning.stories_to_prepare || [])}
                </div>
            `;
        }

        if (sourcesOutput) {
            const sources = payload.sources || [];
            sourcesOutput.innerHTML = `
                <h3>Sources</h3>
                ${sources.length ? `<ul>${sources.map((source) => `
                    <li class="source-item">
                        <a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.title || source.url)}</a>
                        <p class="muted">${escapeHtml(source.snippet || "")}</p>
                    </li>
                `).join("")}</ul>` : "<p class=\"muted\">No web sources stored for this brief.</p>"}
            `;
        }
    }

    function renderQuestions(payload) {
        const output = byId("questionsOutput");
        if (!output) return;
        const questions = payload.questions || [];
        output.innerHTML = questions.map((item) => `
            <div class="question-item">
                <strong>${escapeHtml(item.category)}</strong>
                <p>${escapeHtml(item.question)}</p>
                <p class="muted">Follow-up: ${escapeHtml(item.follow_up)}</p>
                ${renderList(item.answer_signals || [])}
            </div>
        `).join("") || "<p class=\"muted\">No questions generated.</p>";
    }

    function renderTurns(turns, append) {
        const output = byId("conversationOutput");
        if (!output) return;
        const html = (turns || []).map((turn) => `
            <div class="turn ${escapeHtml(turn.role)}">
                <strong>${escapeHtml(turn.role)}</strong>
                <span>${escapeHtml(turn.content)}</span>
            </div>
        `).join("");
        if (append) {
            output.insertAdjacentHTML("beforeend", html);
        } else {
            output.innerHTML = html;
        }
        output.scrollTop = output.scrollHeight;
    }

    function renderSessions(payload) {
        const output = byId("sessionsOutput");
        if (!output) return;
        const sessions = payload.sessions || [];
        output.innerHTML = sessions.length ? sessions.map((session) => `
            <div class="session-item">
                <button type="button" class="secondary js-load-session" data-session-id="${escapeHtml(session.id)}">
                    ${escapeHtml(session.status)} - ${escapeHtml(session.turn_count)} turns - ${escapeHtml(session.created_at)}
                </button>
            </div>
        `).join("") : "<p class=\"muted\">No sessions yet.</p>";

        output.querySelectorAll(".js-load-session").forEach((button) => {
            button.addEventListener("click", () => loadSession(button.dataset.sessionId));
        });
    }

    function renderFeedback(payload) {
        const output = byId("feedbackOutput");
        if (!output) return;
        const feedback = payload.feedback || {};
        output.innerHTML = `
            <h3>Feedback</h3>
            <p class="muted">${escapeHtml(payload.feedback_type || "interim")} feedback${payload.session_ended ? " - session ended" : ""}</p>
            <p>${escapeHtml(feedback.overall || "")}</p>
            <p><strong>Strengths</strong></p>
            ${renderList(feedback.strengths || [])}
            <p><strong>Improvements</strong></p>
            ${renderList(feedback.improvements || [])}
            <p><strong>Next drills</strong></p>
            ${renderList(feedback.next_drills || [])}
        `;
    }

    function speak(text) {
        if (!text || !("speechSynthesis" in window)) return;
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.98;
        window.speechSynthesis.speak(utterance);
    }

    async function loadBrief(refresh) {
        if (!readTarget()) {
            setStatus("Add a user ID and job posting ID.", true);
            return;
        }

        setStatus(refresh ? "Refreshing brief..." : "Loading brief...");
        try {
            let payload;
            if (refresh) {
                payload = await api("/interview-prep/briefs", {
                    method: "POST",
                    body: JSON.stringify({
                        user_id: state.userId,
                        job_posting_id: state.jobPostingId,
                        refresh: true,
                    }),
                });
            } else {
                try {
                    payload = await api(`/interview-prep/briefs?user_id=${encodeURIComponent(state.userId)}&job_posting_id=${encodeURIComponent(state.jobPostingId)}`);
                } catch (_error) {
                    payload = await api("/interview-prep/briefs", {
                        method: "POST",
                        body: JSON.stringify({
                            user_id: state.userId,
                            job_posting_id: state.jobPostingId,
                        }),
                    });
                }
            }
            renderBrief(payload);
            await loadSessions();
            setStatus(payload.generated ? "Brief generated." : "Brief loaded.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    async function generateQuestions() {
        if (!readTarget()) {
            setStatus("Add a user ID and job posting ID.", true);
            return;
        }

        setStatus("Generating questions...");
        try {
            const payload = await api("/interview-prep/questions", {
                method: "POST",
                body: JSON.stringify({
                    user_id: state.userId,
                    job_posting_id: state.jobPostingId,
                    focus: byId("questionFocus") ? byId("questionFocus").value.trim() : "",
                    count: 5,
                }),
            });
            renderQuestions(payload);
            setStatus("Questions ready.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    async function startSession() {
        if (!readTarget()) {
            setStatus("Add a user ID and job posting ID.", true);
            return;
        }

        setStatus("Starting session...");
        try {
            const payload = await api("/interview-prep/sessions", {
                method: "POST",
                body: JSON.stringify({
                    user_id: state.userId,
                    job_posting_id: state.jobPostingId,
                    mode: "browser_voice_text",
                }),
            });
            state.sessionId = payload.session.id;
            renderTurns(payload.turns || []);
            const firstTurn = (payload.turns || []).find((turn) => turn.role === "interviewer");
            state.lastInterviewerText = firstTurn ? firstTurn.content : "";
            if (byId("speakReplies") && byId("speakReplies").checked) speak(state.lastInterviewerText);
            await loadSessions();
            setStatus("Session started.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    async function sendAnswer() {
        const input = byId("answerInput");
        const message = input ? input.value.trim() : "";
        if (!message) {
            setStatus("Add an answer first.", true);
            return;
        }
        if (!state.sessionId) {
            await startSession();
        }
        if (!state.sessionId) return;

        setStatus("Sending answer...");
        try {
            const payload = await api(`/interview-prep/sessions/${state.sessionId}/turns`, {
                method: "POST",
                body: JSON.stringify({
                    message,
                    transcript_chunk: byId("liveTranscript") ? byId("liveTranscript").textContent : message,
                }),
            });
            renderTurns(payload.turns || [], true);
            state.lastInterviewerText = payload.reply ? payload.reply.interviewer_message : "";
            if (input) input.value = "";
            if (byId("liveTranscript")) byId("liveTranscript").textContent = "";
            if (byId("speakReplies") && byId("speakReplies").checked) speak(state.lastInterviewerText);
            await loadSessions();
            setStatus("Answer saved.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    async function loadSessions() {
        if (!readTarget()) return;
        try {
            const payload = await api(`/interview-prep/sessions?user_id=${encodeURIComponent(state.userId)}&job_posting_id=${encodeURIComponent(state.jobPostingId)}`);
            renderSessions(payload);
        } catch (_error) {
            renderSessions({ sessions: [] });
        }
    }

    async function loadSession(sessionId) {
        try {
            const payload = await api(`/interview-prep/sessions/${sessionId}`);
            state.sessionId = sessionId;
            renderTurns(payload.turns || []);
            const interviewerTurns = (payload.turns || []).filter((turn) => turn.role === "interviewer");
            state.lastInterviewerText = interviewerTurns.length ? interviewerTurns[interviewerTurns.length - 1].content : "";
            setStatus("Session loaded.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    async function getFeedback(feedbackType) {
        if (!state.sessionId) {
            setStatus("Start or load a session first.", true);
            return;
        }

        const isFinal = feedbackType === "final";
        setStatus(isFinal ? "Ending session..." : "Generating feedback...");
        try {
            const payload = await api(`/interview-prep/sessions/${state.sessionId}/feedback`, {
                method: "POST",
                body: JSON.stringify({
                    feedback_type: isFinal ? "final" : "interim",
                    end_session: isFinal,
                }),
            });
            renderFeedback(payload);
            renderTurns([payload.turn], true);
            if (isFinal) {
                state.sessionId = null;
            }
            await loadSessions();
            setStatus(isFinal ? "Session ended." : "Feedback ready.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    function startVoice() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const status = byId("voiceStatus");
        if (!SpeechRecognition) {
            if (status) status.textContent = "Speech recognition is not available in this browser.";
            return;
        }

        if (state.recognizing) return;
        const input = byId("answerInput");
        const transcript = byId("liveTranscript");
        state.recognition = new SpeechRecognition();
        state.recognition.continuous = true;
        state.recognition.interimResults = true;

        state.recognition.onstart = () => {
            state.recognizing = true;
            if (status) status.textContent = "Listening...";
        };
        state.recognition.onerror = (event) => {
            if (status) status.textContent = event.error || "Voice error";
        };
        state.recognition.onend = () => {
            state.recognizing = false;
            if (status) status.textContent = "Voice stopped.";
        };
        state.recognition.onresult = (event) => {
            let finalText = input ? input.value : "";
            let interimText = "";
            for (let index = event.resultIndex; index < event.results.length; index += 1) {
                const chunk = event.results[index][0].transcript;
                if (event.results[index].isFinal) {
                    finalText = `${finalText} ${chunk}`.trim();
                } else {
                    interimText += chunk;
                }
            }
            if (input) input.value = `${finalText} ${interimText}`.trim();
            if (transcript) transcript.textContent = `${finalText} ${interimText}`.trim();
        };
        state.recognition.start();
    }

    function stopVoice() {
        if (state.recognition && state.recognizing) {
            state.recognition.stop();
        }
    }

    function setupApplicationsPage() {
        document.querySelectorAll(".js-got-interview").forEach((button) => {
            button.addEventListener("click", async () => {
                const row = button.closest(".application-row");
                const status = row.querySelector(".row-status");
                status.textContent = "Preparing...";
                button.disabled = true;

                try {
                    const payload = await api("/applications/got-interview", {
                        method: "POST",
                        body: JSON.stringify({
                            user_id: row.dataset.userId,
                            job_posting_id: row.dataset.jobPostingId,
                            application_id: row.dataset.applicationId,
                        }),
                    });
                    status.textContent = "Interview prep ready.";
                    window.location.href = payload.prep_url;
                } catch (error) {
                    status.textContent = error.message;
                    button.disabled = false;
                }
            });
        });
    }

    function setupPrepPage() {
        byId("loadBrief").addEventListener("click", () => loadBrief(false));
        byId("refreshBrief").addEventListener("click", () => loadBrief(true));
        byId("generateQuestions").addEventListener("click", generateQuestions);
        byId("startSession").addEventListener("click", startSession);
        byId("sendAnswer").addEventListener("click", sendAnswer);
        byId("getFeedback").addEventListener("click", () => getFeedback("interim"));
        byId("endSession").addEventListener("click", () => getFeedback("final"));
        byId("loadSessions").addEventListener("click", loadSessions);
        byId("startVoice").addEventListener("click", startVoice);
        byId("stopVoice").addEventListener("click", stopVoice);

        if (state.userId && state.jobPostingId) {
            loadBrief(false);
        }
    }

    if (page === "applications") {
        setupApplicationsPage();
    }

    if (page === "interview-prep") {
        setupPrepPage();
    }
}());
