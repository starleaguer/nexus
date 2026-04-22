document.addEventListener('DOMContentLoaded', () => {
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const candidatesList = document.getElementById('candidates-list');
    const activeSkillsList = document.getElementById('active-skills-list');
    const navItems = document.querySelectorAll('.nav-item');
    const tabs = document.querySelectorAll('.tab-content');
    const notification = document.getElementById('notification');

    // Tab Switching
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetTab = item.getAttribute('data-tab');

            navItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            tabs.forEach(tab => {
                tab.classList.remove('active');
                if (tab.id === `${targetTab}-tab`) {
                    tab.classList.add('active');
                }
            });

            if (targetTab === 'hunter') loadCandidates();
            if (targetTab === 'intelligence') loadLearnings();
            if (targetTab === 'system') loadActiveTools();
            if (targetTab === 'youtube') loadKnowledgeNotes();
        });
    });

    // Chat Functionality
    async function sendMessage() {
        const query = userInput.value.trim();
        if (!query) return;

        addMessage(query, 'user');
        userInput.value = '';

        const loadingMsg = addMessage('<i class="fas fa-circle-notch fa-spin"></i> 분석 중입니다...', 'assistant');

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: query })
            });

            const result = await response.json();
            chatBox.removeChild(loadingMsg);

            if (result.final_report) {
                addMessage(formatReport(result.final_report), 'assistant');
                if (result.error) {
                    const warnDiv = document.createElement('div');
                    warnDiv.style = "font-size: 0.8rem; color: #ff6b6b; margin-top: 5px; opacity: 0.8;";
                    warnDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> 알림: ${result.error} (일부 데이터가 누락되었을 수 있습니다)`;
                    chatBox.lastElementChild.querySelector('.msg-content').appendChild(warnDiv);
                }
            } else if (result.error) {
                addMessage(`❌ 오류: ${result.error}`, 'assistant');
            }
        } catch (err) {
            chatBox.removeChild(loadingMsg);
            addMessage('❌ 서버 연결 실패.', 'assistant');
        }
    }

    function addMessage(text, role) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role}`;
        msgDiv.innerHTML = `<div class="msg-content">${text}</div>`;
        chatBox.appendChild(msgDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
        return msgDiv;
    }

    function formatReport(text) {
        if (!text) return '결과가 없습니다.';
        return text
            .replace(/### (.*)/g, '<h3>$1</h3>')
            .replace(/## (.*)/g, '<h2>$1</h2>')
            .replace(/# (.*)/g, '<h1>$1</h1>')
            .replace(/\*\*(.*)\*\*/g, '<strong>$1</strong>')
            .replace(/- (.*)/g, '<li>$1</li>')
            .replace(/\n/g, '<br>');
    }

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    // Intelligence: Learning Log & Autonomous Logs
    async function loadLearnings() {
        const list = document.getElementById('learnings-list');
        list.innerHTML = '<div class="loading-spinner"><i class="fas fa-circle-notch fa-spin"></i><span>Loading learnings...</span></div>';

        try {
            const response = await fetch('/api/learnings');
            const data = await response.json();

            list.innerHTML = '';
            if (!data.learnings || data.learnings.length === 0) {
                list.innerHTML = '<div class="loading-spinner">아직 학습된 내용이 없습니다. 대화를 시작해 보세요!</div>';
            } else {
                data.learnings.forEach(item => {
                    const card = document.createElement('div');
                    card.className = 'learning-card';
                    card.style = 'background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border); border-radius: 12px; padding: 15px; margin-bottom: 15px; border-left: 4px solid var(--primary-accent);';
                    card.innerHTML = `
                        <div style="font-size: 0.8rem; color: #888; margin-bottom: 8px;">${new Date(item.timestamp).toLocaleString()}</div>
                        <div style="font-size: 1rem; line-height: 1.5;">${item.content}</div>
                    `;
                    list.appendChild(card);
                });
            }
        } catch (err) {
            list.innerHTML = '<div class="loading-spinner">데이터 로드 실패</div>';
        }

        // Load Autonomous Logs
        const autoList = document.getElementById('autonomous-logs-list');
        autoList.innerHTML = '<div class="loading-spinner"><i class="fas fa-circle-notch fa-spin"></i><span>Loading market insights...</span></div>';

        try {
            const response = await fetch('/api/autonomous/logs');
            const data = await response.json();

            autoList.innerHTML = '';
            if (!data.logs || data.logs.length === 0) {
                autoList.innerHTML = '<div class="loading-spinner">아직 수집된 시장 동향 로그가 없습니다.</div>';
            } else {
                data.logs.forEach(item => {
                    const card = document.createElement('div');
                    card.className = 'learning-card';
                    card.style = 'background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border); border-radius: 12px; padding: 15px; margin-bottom: 15px; border-left: 4px solid #a855f7;';
                    // The report format can contain markdown, so format it
                    card.innerHTML = `
                        <div style="font-size: 0.8rem; color: #888; margin-bottom: 8px;">${new Date(item.timestamp).toLocaleString()}</div>
                        <div style="font-size: 0.95rem; line-height: 1.6; color: #e2e8f0; max-height: 300px; overflow-y: auto; padding-right: 10px;">${formatReport(item.content)}</div>
                    `;
                    autoList.appendChild(card);
                });
            }
        } catch (err) {
            autoList.innerHTML = '<div class="loading-spinner">시장 동향 로드 실패</div>';
        }
    }

    // Tool Hunter
    const researchBtn = document.getElementById('research-btn');
    const researchInput = document.getElementById('research-query');

    researchBtn.addEventListener('click', async () => {
        const query = researchInput.value.trim();
        if (!query) return;

        try {
            researchBtn.disabled = true;
            researchBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> 탐색 중...';

            const response = await fetch('/api/research', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: query })
            });

            const result = await response.json();
            showNotification(result.message);

            let attempts = 0;
            const interval = setInterval(async () => {
                await loadCandidates();
                attempts++;
                if (attempts >= 12) {
                    clearInterval(interval);
                    researchBtn.disabled = false;
                    researchBtn.innerText = '탐색 시작';
                }
            }, 5000);

        } catch (err) {
            showNotification('탐색 요청 실패');
            researchBtn.disabled = false;
            researchBtn.innerText = '탐색 시작';
        }
    });

    async function loadCandidates() {
        candidatesList.innerHTML = '<div class="loading-spinner"><i class="fas fa-circle-notch fa-spin"></i><span>Searching tools...</span></div>';
        try {
            const response = await fetch('/api/candidates');
            const data = await response.json();
            candidatesList.innerHTML = '';
            const pending = data.filter(c => c.status === 'pending_approval');
            if (pending.length === 0) {
                candidatesList.innerHTML = '<div class="loading-spinner">새로운 후보 도구가 없습니다.</div>';
                return;
            }
            pending.forEach(tool => {
                const card = document.createElement('div');
                card.className = 'candidate-card';
                card.innerHTML = `
                    <div class="card-header">
                        <span class="tool-badge badge-${tool.type}">${tool.type}</span>
                        <i class="fab fa-github"></i>
                    </div>
                    <h3 class="card-title">${tool.tool_name}</h3>
                    <p class="card-desc">${tool.description}</p>
                    <div class="card-actions">
                        <button class="btn btn-approve" onclick="approveTool('${tool.tool_name}')">승인</button>
                        <button class="btn btn-reject" onclick="rejectTool('${tool.tool_name}')">거절</button>
                    </div>
                `;
                candidatesList.appendChild(card);
            });
        } catch (err) {
            candidatesList.innerHTML = '로드 실패';
        }
    }

    window.approveTool = async (name) => {
        showNotification(`${name} 승인 중...`);
        try {
            const response = await fetch('/api/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tool_name: name })
            });
            const result = await response.json();
            showNotification(result.message);
            loadCandidates();
        } catch (err) {
            showNotification('승인 오류');
        }
    };

    window.rejectTool = async (name) => {
        if (!confirm(`'${name}' 도구를 후보 목록에서 삭제하시겠습니까?`)) return;

        try {
            const response = await fetch('/api/reject', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tool_name: name })
            });
            const result = await response.json();
            showNotification(result.message);
            loadCandidates();
        } catch (err) {
            showNotification('거절 처리 중 오류 발생');
        }
    };

    // System: Config & Timeouts
    async function loadActiveTools() {
        activeSkillsList.innerHTML = '<li>Loading...</li>';
        try {
            const statusRes = await fetch('/api/status');
            const statusData = await statusRes.json();
            const modelsRes = await fetch('/models');
            const models = await modelsRes.json();

            const managerSelect = document.getElementById('manager-model-select');
            const workerSelect = document.getElementById('worker-model-select');
            managerSelect.innerHTML = ''; workerSelect.innerHTML = '';

            models.forEach(model => {
                managerSelect.innerHTML += `<option value="${model}" ${model === statusData.manager_model ? 'selected' : ''}>${model}</option>`;
                workerSelect.innerHTML += `<option value="${model}" ${model === (statusData.worker_model || 'gemma4:e4b') ? 'selected' : ''}>${model}</option>`;
            });

            if (statusData.timeouts) {
                document.getElementById('worker-timeout-input').value = statusData.timeouts.worker || 120;
                document.getElementById('ollama-timeout-input').value = statusData.timeouts.ollama || 120;
            }
            if (statusData.autonomous) {
                document.getElementById('autonomous-interval-input').value = statusData.autonomous.interval || 3600;
            }

            const toolsRes = await fetch('/api/tools');
            const toolsData = await toolsRes.json();
            activeSkillsList.innerHTML = '';
            (toolsData.skills || []).forEach(tool => {
                activeSkillsList.innerHTML += `<li>${tool.name} <span class="badge-skill">Skill</span></li>`;
            });
        } catch (err) {
            console.error('System info load failed');
        }
    }

    document.getElementById('save-models-btn').addEventListener('click', async () => {
        const managerModel = document.getElementById('manager-model-select').value;
        const workerModel = document.getElementById('worker-model-select').value;

        console.log(`Saving models: manager=${managerModel}, worker=${workerModel}`);

        try {
            showNotification('모델 설정 저장 중...');
            // Manager 모델 업데이트
            const res1 = await fetch('/api/config/model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ component: 'manager', model: managerModel })
            });
            const data1 = await res1.json();
            console.log('Manager update response:', data1);

            // Worker 모델 업데이트
            const res2 = await fetch('/api/config/model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ component: 'worker', model: workerModel })
            });
            const data2 = await res2.json();
            console.log('Worker update response:', data2);

            showNotification('모델 설정이 성공적으로 저장되었습니다!');

            // 저장 후 정보 다시 로드 (상태 동기화)
            setTimeout(loadActiveTools, 500);
        } catch (err) {
            console.error('Save failed:', err);
            showNotification('모델 저장 실패: ' + err.message);
        }
    });

    document.getElementById('save-timeout-btn').addEventListener('click', async () => {
        const workerT = parseInt(document.getElementById('worker-timeout-input').value);
        const ollamaT = parseInt(document.getElementById('ollama-timeout-input').value);

        try {
            showNotification('타임아웃 설정 저장 중...');
            await fetch('/api/config/timeout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ worker: workerT, ollama: ollamaT })
            });
            showNotification('타임아웃 설정이 반영되었습니다.');
        } catch (err) {
            showNotification('저장 실패');
        }
    });

    document.getElementById('save-interval-btn').addEventListener('click', async () => {
        const interval = parseInt(document.getElementById('autonomous-interval-input').value);
        if (interval < 60) {
            showNotification('주기는 최소 60초 이상이어야 합니다.');
            return;
        }

        try {
            showNotification('모니터링 주기 저장 중...');
            await fetch('/api/config/interval', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ interval: interval })
            });
            showNotification('모니터링 주기가 반영되었으며 자율 루프가 재시작되었습니다.');
        } catch (err) {
            showNotification('저장 실패');
        }
    });

    function showNotification(text) {
        notification.innerText = text;
        notification.classList.add('show');
        setTimeout(() => notification.classList.remove('show'), 3000);
    }

    // Initial load
    loadActiveTools();

    // ==================== YouTube Knowledge Feeder ====================
    let currentSummary = '';
    let currentUrl = '';

    document.getElementById('yt-summarize-btn').addEventListener('click', async () => {
        const url = document.getElementById('yt-url-input').value.trim();
        if (!url) { showNotification('YouTube URL을 입력하세요.'); return; }

        const btn = document.getElementById('yt-summarize-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> 분석 중...';
        document.getElementById('yt-result-area').style.display = 'none';

        try {
            const res = await fetch('/api/youtube/summarize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });
            const data = await res.json();

            if (data.status === 'error') {
                showNotification(`오류: ${data.message}`);
                return;
            }

            currentSummary = data.summary;
            currentUrl = url;

            document.getElementById('yt-video-link').href = url;
            document.getElementById('yt-video-link').textContent = `youtu.be/${data.video_id} (${data.language})`;
            document.getElementById('yt-summary-content').innerHTML = formatReport(data.summary);
            document.getElementById('yt-user-comment').value = '';
            document.getElementById('yt-result-area').style.display = 'block';
        } catch (err) {
            showNotification('요약 요청 실패');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '요약하기';
        }
    });

    document.getElementById('yt-url-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') document.getElementById('yt-summarize-btn').click();
    });

    document.getElementById('yt-note-btn').addEventListener('click', async () => {
        if (!currentSummary) { showNotification('먼저 요약을 생성하세요.'); return; }
        const userComment = document.getElementById('yt-user-comment').value.trim();

        const btn = document.getElementById('yt-note-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> 학습 중...';

        try {
            const res = await fetch('/api/knowledge/note', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: currentSummary,
                    source_url: currentUrl,
                    user_comment: userComment,
                    category: 'youtube'
                })
            });
            const data = await res.json();
            showNotification(data.message || 'AI가 학습했습니다!');
            loadKnowledgeNotes();
        } catch (err) {
            showNotification('노트 저장 실패');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-brain"></i> AI에게 노트 (학습시키기)';
        }
    });

    async function loadKnowledgeNotes() {
        const list = document.getElementById('yt-notes-list');
        list.innerHTML = '<div class="loading-spinner"><i class="fas fa-circle-notch fa-spin"></i><span>Loading notes...</span></div>';
        try {
            const res = await fetch('/api/knowledge/notes');
            const data = await res.json();
            list.innerHTML = '';
            if (!data.notes || data.notes.length === 0) {
                list.innerHTML = '<div class="loading-spinner">저장된 노트가 없습니다. 영상을 요약하고 AI에게 노트해 보세요!</div>';
                return;
            }
            data.notes.forEach(note => {
                const card = document.createElement('div');
                card.style = 'background: rgba(255,68,68,0.05); border: 1px solid rgba(255,68,68,0.2); border-radius: 12px; padding: 18px; margin-bottom: 15px; border-left: 4px solid #ff4444;';
                const comment = note.user_comment ? `<div style="font-weight:600; color: #c084fc; margin-bottom:8px;">📌 ${note.user_comment}</div>` : '';
                const srcLink = note.source_url ? `<a href="${note.source_url}" target="_blank" style="font-size:0.75rem; color:#888; text-decoration:none;">🔗 ${note.source_url.substring(0, 60)}...</a>` : '';
                card.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <span style="font-size:0.75rem; color:#888;">🎥 ${new Date(note.timestamp).toLocaleString()}</span>
                        ${srcLink}
                    </div>
                    ${comment}
                    <div style="font-size:0.9rem; line-height:1.6; color:#ccc; max-height:200px; overflow-y:auto;">${formatReport(note.content)}</div>
                `;
                list.appendChild(card);
            });
        } catch (err) {
            list.innerHTML = '<div class="loading-spinner">노트 로드 실패</div>';
        }
    }
});
