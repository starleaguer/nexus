document.addEventListener('DOMContentLoaded', () => {
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const candidatesList = document.getElementById('candidates-list');
    const activeSkillsList = document.getElementById('active-skills-list');
    const activeMcpList = document.getElementById('active-mcp-list');
    const navItems = document.querySelectorAll('.nav-item');
    const tabs = document.querySelectorAll('.tab-content');

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
            if (targetTab === 'config') loadActiveTools();
        });
    });

    // Chat Functionality
    async function sendMessage() {
        const query = userInput.value.trim();
        if (!query) return;

        // Add user message to UI
        addMessage(query, 'user');
        userInput.value = '';

        // Add loading message
        const loadingMsg = addMessage('<i class="fas fa-circle-notch fa-spin"></i> 분석 중입니다...', 'assistant');

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: query })
            });

            const result = await response.json();
            chatBox.removeChild(loadingMsg);

            if (result.error) {
                addMessage(`❌ 오류: ${result.error}`, 'assistant');
            } else {
                // Convert Markdown-like text to simple HTML (basic)
                const reportHtml = formatReport(result.final_report);
                addMessage(reportHtml, 'assistant');
            }
        } catch (err) {
            chatBox.removeChild(loadingMsg);
            addMessage('❌ 서버 연결 실패. 다시 시도해 주세요.', 'assistant');
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

    // Custom Research
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
            
            // 5초마다 후보 목록 새로고침 (최대 1분간)
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

    // Tool Hunter Functionality
    async function loadCandidates() {
        candidatesList.innerHTML = '<div class="loading-spinner"><i class="fas fa-circle-notch fa-spin"></i><span>Loading candidate tools...</span></div>';
        
        try {
            const response = await fetch('/api/candidates');
            const data = await response.json();
            
            candidatesList.innerHTML = '';
            
            // Only show pending_approval
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
                        <button class="btn btn-reject" onclick="showNotification('거절 기능은 추후 구현 예정입니다.')">거절</button>
                    </div>
                `;
                candidatesList.appendChild(card);
            });
        } catch (err) {
            candidatesList.innerHTML = '<div class="loading-spinner">데이터 로드 실패</div>';
        }
    }

    window.approveTool = async (name) => {
        showNotification(`${name} 승인 처리 중...`);
        try {
            const response = await fetch('/api/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tool_name: name })
            });
            const result = await response.json();
            showNotification(`${name} 승인 완료!`);
            loadCandidates();
        } catch (err) {
            showNotification('승인 중 오류 발생');
        }
    };

    // Config Tab Functionality
    async function loadActiveTools() {
        activeSkillsList.innerHTML = '<li>Loading...</li>';
        activeMcpList.innerHTML = '<li>Loading...</li>';
        
        try {
            // Load Status & Current Models
            const statusRes = await fetch('/api/status');
            const statusData = await statusRes.json();
            
            // Load Available Models
            const modelsRes = await fetch('/api/models');
            const models = await modelsRes.json();
            
            const managerSelect = document.getElementById('manager-model-select');
            const workerSelect = document.getElementById('worker-model-select');
            
            managerSelect.innerHTML = '';
            workerSelect.innerHTML = '';
            
            models.forEach(model => {
                managerSelect.innerHTML += `<option value="${model}" ${model === statusData.manager_model ? 'selected' : ''}>${model}</option>`;
                // Worker model might be different in manifest, but status only shows manager_model currently. 
                // Let's just default to what we have or just gemma4:e4b for worker.
                workerSelect.innerHTML += `<option value="${model}" ${model === (statusData.worker_model || 'gemma4:e4b') ? 'selected' : ''}>${model}</option>`;
            });

            const response = await fetch('/api/tools');
            const data = await response.json();
            
            activeSkillsList.innerHTML = '';
            (data.skills || []).forEach(tool => {
                activeSkillsList.innerHTML += `<li>${tool.name} <span class="badge-skill">Skill</span></li>`;
            });

            activeMcpList.innerHTML = '';
            (data.mcp || []).forEach(tool => {
                activeMcpList.innerHTML += `<li>${tool.name} <span class="badge-mcp">MCP</span></li>`;
            });
        } catch (err) {
            console.error('Failed to load system info');
        }
    }

    document.getElementById('save-config-btn').addEventListener('click', async () => {
        const managerModel = document.getElementById('manager-model-select').value;
        const workerModel = document.getElementById('worker-model-select').value;
        
        try {
            showNotification('설정 저장 중...');
            
            await fetch('/api/config/model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ component: 'manager', model: managerModel })
            });
            
            await fetch('/api/config/model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ component: 'worker', model: workerModel })
            });
            
            showNotification('시스템 설정이 저장되었습니다.');
        } catch (err) {
            showNotification('저장 중 오류 발생');
        }
    });

    // Notifications
    const notification = document.getElementById('notification');
    function showNotification(text) {
        notification.innerText = text;
        notification.classList.add('show');
        setTimeout(() => notification.classList.remove('show'), 3000);
    }
    window.showNotification = showNotification;

    // Initial load
    loadActiveTools();
});
