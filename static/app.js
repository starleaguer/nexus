document.addEventListener('DOMContentLoaded', () => {
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const candidatesList = document.getElementById('candidates-list');
    const activeSkillsList = document.getElementById('active-skills-list');
    const navItems = document.querySelectorAll('.nav-item');
    const tabs = document.querySelectorAll('.tab-content');
    const notification = document.getElementById('notification');

    // Modal Elements
    const modal = document.getElementById('full-view-modal');
    const closeModalBtn = modal.querySelector('.close-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalInfoBar = document.getElementById('modal-info-bar');
    const modalTextContent = document.getElementById('modal-text-content');
    const modalFooter = document.getElementById('modal-footer-actions');

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
        const deleteLearningsBtn = document.getElementById('delete-learnings-btn');
        list.innerHTML = '<div class="loading-spinner"><i class="fas fa-circle-notch fa-spin"></i><span>Loading learnings...</span></div>';
        deleteLearningsBtn.style.display = 'none';

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
                    card.style = 'background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border); border-radius: 12px; padding: 15px; margin-bottom: 15px; border-left: 4px solid var(--primary-accent); position: relative; cursor: pointer;';
                    card.innerHTML = `
                        <input type="checkbox" class="log-checkbox" data-id="${item.id}" style="position: absolute; right: 15px; top: 15px; width: 18px; height: 18px; cursor: pointer;">
                        <div style="font-size: 0.8rem; color: #888; margin-bottom: 8px;">${new Date(item.timestamp).toLocaleString()}</div>
                        <div style="font-size: 1rem; line-height: 1.5; padding-right: 30px;">${item.content}</div>
                    `;
                    card.onclick = (e) => {
                        if (e.target.tagName !== 'INPUT') {
                            const cb = card.querySelector('.log-checkbox');
                            cb.checked = !cb.checked;
                            updateDeleteButton('learnings');
                        }
                    };
                    card.querySelector('.log-checkbox').onchange = () => updateDeleteButton('learnings');
                    list.appendChild(card);
                });
            }
        } catch (err) {
            list.innerHTML = '<div class="loading-spinner">데이터 로드 실패</div>';
        }
    }

    function updateDeleteButton(type) {
        if (type === 'learnings') {
            const checked = document.querySelectorAll('#learnings-list .log-checkbox:checked').length;
            document.getElementById('delete-learnings-btn').style.display = checked > 0 ? 'block' : 'none';
        }
    }

    document.getElementById('delete-learnings-btn').addEventListener('click', async () => {
        const checked = Array.from(document.querySelectorAll('#learnings-list .log-checkbox:checked')).map(cb => cb.getAttribute('data-id'));
        if (checked.length === 0) return;
        if (!confirm(`${checked.length}건의 학습 로그를 삭제하시겠습니까?`)) return;

        try {
            const res = await fetch('/api/learnings/delete-bulk', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: checked })
            });
            const result = await res.json();
            showNotification(result.message);
            loadLearnings();
        } catch (err) {
            showNotification('삭제 실패');
        }
    });


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
            
            // 데이터 구조 호환성 처리 (배열 직접 반환 vs {candidates: []} 객체 반환)
            const candidatesArray = Array.isArray(data) ? data : (data.candidates || []);
            const pending = candidatesArray.filter(c => c.status === 'pending_approval');
            
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
                        ${tool.url ? `<a href="${tool.url}" target="_blank" style="color: #fff; font-size: 1.2rem; transition: color 0.2s;" onmouseover="this.style.color='#a855f7'" onmouseout="this.style.color='#fff'"><i class="fab fa-github"></i></a>` : '<i class="fab fa-github"></i>'}
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
        const loadingIndicator = document.getElementById('models-loading-indicator');
        const selectArea = document.getElementById('models-select-area');
        
        if (loadingIndicator) loadingIndicator.style.display = 'flex';
        if (selectArea) selectArea.style.opacity = '0.5';

        try {
            const statusRes = await fetch('/api/status');
            const statusData = await statusRes.json();
            
            const managerSelect = document.getElementById('manager-model-select');
            const workerSelect = document.getElementById('worker-model-select');

            // 1. Manager 모델 로드
            try {
                console.log('Fetching manager models...');
                const mgrRes = await fetch('/api/models/manager');
                const mgrModels = await mgrRes.json();
                console.log('Manager models received:', mgrModels);
                
                managerSelect.innerHTML = '';
                if (Array.isArray(mgrModels) && mgrModels.length > 0) {
                    mgrModels.forEach(model => {
                        managerSelect.innerHTML += `<option value="${model}" ${model === statusData.manager_model ? 'selected' : ''}>${model}</option>`;
                    });
                } else {
                    managerSelect.innerHTML = '<option value="">No local models found</option>';
                }
            } catch (err) {
                console.error('Manager models load failed:', err);
                managerSelect.innerHTML = `<option value="">Error loading local models</option>`;
            }

            // 2. Worker 모델 로드
            try {
                console.log('Fetching worker models...');
                const wrkRes = await fetch('/api/models/worker');
                const wrkModels = await wrkRes.json();
                console.log('Worker models received:', wrkModels);
                
                workerSelect.innerHTML = '';
                if (Array.isArray(wrkModels) && wrkModels.length > 0) {
                    wrkModels.forEach(model => {
                        workerSelect.innerHTML += `<option value="${model}" ${model === statusData.worker_model ? 'selected' : ''}>${model}</option>`;
                    });
                } else {
                    workerSelect.innerHTML = '<option value="">No worker models found</option>';
                }
            } catch (err) {
                console.error('Worker models load failed:', err);
                workerSelect.innerHTML = `<option value="">Error loading worker models</option>`;
            }

            if (statusData.timeouts) {
                document.getElementById('worker-timeout-input').value = statusData.timeouts.worker || 120;
                document.getElementById('ollama-timeout-input').value = statusData.timeouts.ollama || 120;
            }

            const toolsRes = await fetch('/api/tools');
            const toolsData = await toolsRes.json();
            
            // Clear lists
            activeSkillsList.innerHTML = '';
            const hunterGrid = document.getElementById('hunter-active-tools-grid');
            if (hunterGrid) hunterGrid.innerHTML = '';
            
            const renderToolCard = (tool, type) => {
                const badgeClass = type === 'skill' ? 'badge-skill' : 'badge-mcp';
                const icon = type === 'skill' ? 'fa-bolt' : 'fa-plug';
                
                let usageHtml = '';
                if (tool.usage) usageHtml = `<div class="meta-item"><span class="meta-label">💡 When to use</span>${tool.usage}</div>`;
                else if (tool.capabilities) usageHtml = `<div class="meta-item"><span class="meta-label">✨ Capabilities</span>${Array.isArray(tool.capabilities) ? tool.capabilities.slice(0, 3).join(', ') : tool.capabilities}</div>`;

                let outputHtml = tool.output ? `<div class="meta-item"><span class="meta-label">📦 Output</span>${tool.output}</div>` : '';

                const cardHtml = `
                    <div class="active-tool-card">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                            <span class="tool-badge ${badgeClass}">${type}</span>
                            <i class="fas ${icon}" style="opacity: 0.3; font-size: 0.8rem;"></i>
                        </div>
                        <h4>${tool.name}</h4>
                        <div class="desc">${tool.description || 'No description available.'}</div>
                        ${usageHtml}
                        ${outputHtml}
                    </div>
                `;
                
                // Sidebar list (simple)
                const li = document.createElement('li');
                li.innerHTML = `${tool.name} <span class="tool-badge ${badgeClass}">${type}</span>`;
                activeSkillsList.appendChild(li);
                
                // Hunter grid (rich)
                if (hunterGrid) {
                    const div = document.createElement('div');
                    div.innerHTML = cardHtml;
                    hunterGrid.appendChild(div.firstElementChild);
                }
            };

            (toolsData.skills || []).forEach(tool => renderToolCard(tool, 'skill'));
            (toolsData.mcp || []).forEach(tool => renderToolCard(tool, 'mcp'));
        } catch (err) {
            console.error('System info load failed:', err);
            showNotification('❌ 시스템 정보를 불러오지 못했습니다.');
        } finally {
            if (loadingIndicator) loadingIndicator.style.display = 'none';
            if (selectArea) {
                selectArea.style.opacity = '1';
                selectArea.style.pointerEvents = 'auto';
            }
        }
    }

    document.getElementById('refresh-models-btn')?.addEventListener('click', loadActiveTools);

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


    function showNotification(text) {
        notification.innerText = text;
        notification.classList.add('show');
        setTimeout(() => notification.classList.remove('show'), 3000);
    }

    // Initial load
    loadActiveTools();
    loadKnowledgeNotes();

    // ==================== YouTube Knowledge Feeder ====================
    let currentSummary = '';
    let currentUrl = '';

    document.getElementById('summarize-btn').addEventListener('click', async () => {
        const url = document.getElementById('youtube-url').value.trim();
        const modelType = document.getElementById('youtube-model-type').value;
        
        if (!url) { showNotification('YouTube URL을 입력하세요.'); return; }

        const btn = document.getElementById('summarize-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> 분석 중...';
        document.getElementById('yt-result-area').style.display = 'none';

        try {
            const res = await fetch('/api/youtube/summarize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, model_type: modelType })
            });
            const data = await res.json();

            if (data.status === 'error') {
                showNotification(`오류: ${data.message}`);
                return;
            }

            currentSummary = data.summary;
            currentUrl = url;

            document.getElementById('yt-video-link').href = url;
            document.getElementById('yt-video-link').textContent = `youtu.be/${data.video_id} (${data.language || 'Video'})`;
            const titleEl = document.getElementById('yt-video-title');
            if (titleEl) titleEl.textContent = data.title || '';

            // 사용된 모델 배지 표시
            const badge = document.getElementById('yt-model-badge');
            if (badge && data.selected_model) badge.textContent = `🤖 ${data.selected_model}`;

            // 요약 내용 렌더링
            document.getElementById('yt-summary-content').innerHTML = formatReport(data.summary);

            // 이면 추론 렌더링
            const insightEl = document.getElementById('yt-insight-content');
            if (insightEl && data.insight) {
                insightEl.innerHTML = formatReport(data.insight);
            }

            // 탭 초기화 (요약 탭 활성)
            document.querySelectorAll('.yt-tab-btn').forEach(b => {
                const isActive = b.dataset.target === 'yt-summary-panel';
                b.style.color = isActive ? 'white' : '#888';
                b.style.borderBottom = isActive ? '2px solid var(--accent-primary)' : '2px solid transparent';
                b.classList.toggle('active', isActive);
            });
            document.getElementById('yt-summary-panel').style.display = 'block';
            const insightPanel = document.getElementById('yt-insight-panel');
            if (insightPanel) insightPanel.style.display = 'none';

            document.getElementById('yt-user-comment').value = '';
            const resultArea = document.getElementById('yt-result-area');
            resultArea.style.display = 'block';
            
            // 결과 카드 클릭 시 모달 연결
            const resultCard = resultArea.querySelector('.yt-summary-card');
            resultCard.style.cursor = 'pointer';
            resultCard.onclick = () => {
                const title = data.title || '영상 요약 결과';
                const info = `
                    <span><i class="fab fa-youtube"></i> <a href="${url}" target="_blank" style="color:inherit; text-decoration:none;">${url}</a></span>
                    <span><i class="fas fa-microchip"></i> ${data.selected_model || 'Unknown Model'}</span>
                `;
                const footer = `
                    <button class="btn btn-approve" onclick="noteToAI('${data.summary.replace(/'/g, "\\'")}', '${url}', document.getElementById('yt-user-comment').value.replace(/'/g, "\\'"))">
                        <i class="fas fa-brain"></i> AI에게 학습시키기
                    </button>
                    <button class="btn btn-reject close-modal-action">닫기</button>
                `;
                openModal(title, data.summary + (data.insight ? "\n\n---\n\n### 이면 추론\n" + data.insight : ""), info, footer);
            };
            
            resultArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (err) {
            showNotification('요약 요청 실패');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '영상 요약 분석 시작';
        }
    });

    document.getElementById('youtube-url').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') document.getElementById('summarize-btn').click();
    });

    // 요약 / 이면 추론 탭 전환
    document.addEventListener('click', (e) => {
        const tabBtn = e.target.closest('.yt-tab-btn');
        if (!tabBtn) return;
        const target = tabBtn.dataset.target;
        document.querySelectorAll('.yt-tab-btn').forEach(b => {
            const isActive = b.dataset.target === target;
            b.style.color = isActive ? 'white' : '#888';
            b.style.borderBottom = isActive ? '2px solid var(--accent-primary)' : '2px solid transparent';
            b.classList.toggle('active', isActive);
        });
        ['yt-summary-panel', 'yt-insight-panel'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = (id === target) ? 'block' : 'none';
        });
    });

    document.getElementById('yt-note-btn').addEventListener('click', async () => {
        // currentSummary가 비었으면 DOM에서 직접 읽기 (새로고침 후에도 동작)
        const summaryEl = document.getElementById('yt-summary-content');
        const summaryText = currentSummary || summaryEl?.innerText?.trim();
        
        if (!summaryText) { showNotification('먼저 영상 요약을 실행해 주세요.'); return; }
        
        const urlEl = document.getElementById('yt-video-link');
        const saveUrl = currentUrl || urlEl?.href || '';
        const userComment = document.getElementById('yt-user-comment').value.trim();

        const btn = document.getElementById('yt-note-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> 학습 중...';

        try {
            const res = await fetch('/api/knowledge/note', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: summaryText,
                    source_url: saveUrl,
                    user_comment: userComment,
                    category: 'youtube'
                })
            });
            const data = await res.json();
            showNotification('✅ AI가 학습했습니다!');
            loadKnowledgeNotes();
        } catch (err) {
            showNotification('❌ 노트 저장 실패');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-brain"></i> AI에게 노트 (학습시키기)';
        }
    });

    async function loadKnowledgeNotes() {
        const list = document.getElementById('yt-notes-list');
        const badge = document.getElementById('notes-count-badge');
        list.innerHTML = '<div class="loading-spinner"><i class="fas fa-circle-notch fa-spin"></i><span>Loading knowledge base...</span></div>';
        
        try {
            const res = await fetch('/api/knowledge/notes');
            const data = await res.json();
            list.innerHTML = '';
            
            const notes = data.notes || [];
            if (badge) badge.textContent = `${notes.length} Notes`;
            
            if (notes.length === 0) {
                list.innerHTML = '<div class="loading-spinner" style="grid-column: 1/-1;">저장된 노트가 없습니다. 영상을 요약하고 AI에게 학습시켜 보세요!</div>';
                return;
            }

            notes.forEach(note => {
                const card = document.createElement('div');
                card.className = 'note-card';
                
                const commentHtml = note.user_comment ? `<div class="note-comment">📌 ${note.user_comment}</div>` : '';
                const linkHtml = note.source_url ? `<a href="${note.source_url}" target="_blank" class="note-link">🔗 Link</a>` : '';
                
                card.innerHTML = `
                    <button class="delete-note-btn" title="삭제" onclick="event.stopPropagation(); deleteKnowledgeNote('${note.id}')">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                    <div class="note-header">
                        <span class="note-time"><i class="far fa-calendar-alt"></i> ${new Date(note.timestamp).toLocaleDateString()}</span>
                        ${linkHtml}
                    </div>
                    ${commentHtml}
                    <div class="note-body">${formatReport(note.content)}</div>
                `;

                // 카드 클릭 시 상세 모달 오픈
                card.onclick = () => {
                    const infoHtml = `
                        <span><i class="far fa-calendar-alt"></i> ${new Date(note.timestamp).toLocaleString()}</span>
                        ${note.source_url ? `<span><i class="fas fa-link"></i> <a href="${note.source_url}" target="_blank" style="color:inherit; text-decoration:none;">${note.source_url}</a></span>` : ''}
                    `;
                    const footerHtml = `
                        <button class="btn btn-approve" onclick="noteToAI('${note.content.replace(/'/g, "\\'")}', '${note.source_url || ''}', '${note.user_comment?.replace(/'/g, "\\'") || ''}')">
                            <i class="fas fa-brain"></i> AI에게 다시 학습시키기
                        </button>
                        <button class="btn btn-reject close-modal-action">닫기</button>
                    `;
                    openModal(note.user_comment || '지식 노트 상세', note.content, infoHtml, footerHtml);
                };

                list.appendChild(card);
            });
        } catch (err) {
            list.innerHTML = '<div class="loading-spinner" style="grid-column: 1/-1;">데이터 로드 실패</div>';
        }
    }

    // Modal Utility Functions
    function openModal(title, content, infoHtml = '', footerHtml = '') {
        modalTitle.innerText = title;
        modalInfoBar.innerHTML = infoHtml;
        modalTextContent.innerHTML = formatReport(content);
        modalFooter.innerHTML = footerHtml;
        
        modal.classList.add('show');
        document.body.style.overflow = 'hidden';

        // 닫기 버튼 이벤트 바인딩 (동적 생성된 버튼 포함)
        const closeBtns = modal.querySelectorAll('.close-modal, .close-modal-action');
        closeBtns.forEach(btn => {
            btn.onclick = closeModal;
        });
    }

    function closeModal() {
        modal.classList.remove('show');
        document.body.style.overflow = 'auto';
    }

    window.onclick = (event) => {
        if (event.target == modal) closeModal();
    };

    // Note to AI (Shared logic)
    window.noteToAI = async (content, sourceUrl, userComment) => {
        const loadingBtn = modal.querySelector('.btn-approve');
        const originalHtml = loadingBtn ? loadingBtn.innerHTML : '';
        if (loadingBtn) {
            loadingBtn.disabled = true;
            loadingBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> 학습 중...';
        }

        try {
            const res = await fetch('/api/knowledge/note', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: content,
                    source_url: sourceUrl,
                    user_comment: userComment,
                    category: 'youtube'
                })
            });
            showNotification('✅ AI가 학습했습니다!');
            if (modal.classList.contains('show')) closeModal();
            loadKnowledgeNotes();
        } catch (err) {
            showNotification('❌ 노트 저장 실패');
        } finally {
            if (loadingBtn) {
                loadingBtn.disabled = false;
                loadingBtn.innerHTML = originalHtml;
            }
        }
    };

    window.deleteKnowledgeNote = async (id) => {
        if (!confirm('이 지식 노트를 삭제하시겠습니까? 에이전트의 기억에서 제거됩니다.')) return;
        
        try {
            const res = await fetch('/api/knowledge/notes/delete-bulk', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: [id] })
            });
            const data = await res.json();
            showNotification(data.message || '삭제되었습니다.');
            loadKnowledgeNotes();
        } catch (err) {
            showNotification('삭제 오류 발생');
        }
    };
});
