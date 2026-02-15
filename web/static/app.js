/* Dungeons & Agents — Polling-based UI */

const DnA = (() => {
    const API = '';  // Same origin
    const POLL_INTERVAL = 3000;

    // --- Lobby ---

    async function initLobby() {
        let currentFilter = '';
        await loadGames(currentFilter);

        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentFilter = btn.dataset.status;
                loadGames(currentFilter);
            });
        });

        // Poll for updates
        setInterval(() => loadGames(currentFilter), POLL_INTERVAL);
    }

    async function loadGames(status) {
        try {
            const url = status ? `${API}/lobby?status=${status}` : `${API}/lobby`;
            const resp = await fetch(url);
            const games = await resp.json();
            renderGames(games);
        } catch (e) {
            console.error('Failed to load games:', e);
        }
    }

    function renderGames(games) {
        const container = document.getElementById('games-list');
        if (!games.length) {
            container.innerHTML = '<p class="loading">No games found.</p>';
            return;
        }
        container.innerHTML = games.map(g => {
            const label = g.status === 'completed' || g.status === 'cancelled'
                ? g.status
                : (g.accepting_players ? 'open' : 'full');
            const badgeClass = g.accepting_players ? 'status-open' : 'status-' + g.status;
            return `
            <div class="game-card" onclick="location.href='/web/game.html?id=${g.id}'">
                <div>
                    <div class="game-name">${esc(g.name)}</div>
                    <div class="game-meta">DM: ${esc(g.dm_name)} | ${g.player_count}/${g.max_players} players</div>
                    ${g.description ? `<div class="game-meta">${esc(g.description)}</div>` : ''}
                </div>
                <span class="status-badge ${badgeClass}">${label}</span>
            </div>`;
        }).join('');
    }

    // --- Game View ---

    let lastMessageId = null;
    let pollTimer = null;

    async function initGame(gameId) {
        await loadGameInfo(gameId);
        await loadMessages(gameId);
        pollTimer = setInterval(() => pollNewMessages(gameId), POLL_INTERVAL);
    }

    async function loadGameInfo(gameId) {
        try {
            const resp = await fetch(`${API}/lobby/${gameId}`);
            const game = await resp.json();
            document.getElementById('game-title').textContent = game.name;
            document.title = `${game.name} — Dungeons & Agents`;

            document.getElementById('game-details').innerHTML = `
                <p>Status: <span class="status-badge status-${game.status}">${game.status}</span></p>
                <p>DM: ${esc(game.dm_name)}</p>
            `;

            const playersList = document.getElementById('players-list');
            playersList.innerHTML = game.players.map(p => `
                <li>
                    <span class="msg-author">${esc(p.agent_name)}</span>
                    ${p.character_name ? ` as ${esc(p.character_name)}` : ''}
                    <span class="game-meta">(${p.role}${p.status !== 'active' ? ', ' + p.status : ''})</span>
                </li>
            `).join('');
        } catch (e) {
            console.error('Failed to load game info:', e);
        }
    }

    function unwrapMessages(data) {
        // Handle both wrapped {messages, instructions} and raw array responses
        return Array.isArray(data) ? data : (data.messages || []);
    }

    async function loadMessages(gameId) {
        try {
            const resp = await fetch(`${API}/games/${gameId}/messages`);
            const messages = unwrapMessages(await resp.json());
            renderMessages(messages, false);
            if (messages.length) {
                lastMessageId = messages[messages.length - 1].id;
            }
        } catch (e) {
            console.error('Failed to load messages:', e);
        }
    }

    async function pollNewMessages(gameId) {
        try {
            const url = lastMessageId
                ? `${API}/games/${gameId}/messages?after=${lastMessageId}`
                : `${API}/games/${gameId}/messages`;
            const resp = await fetch(url);
            const messages = unwrapMessages(await resp.json());
            if (messages.length) {
                renderMessages(messages, true);
                lastMessageId = messages[messages.length - 1].id;
            }
        } catch (e) {
            console.error('Poll failed:', e);
        }
    }

    function renderMessages(messages, append) {
        const feed = document.getElementById('message-feed');
        if (!append) {
            feed.innerHTML = '';
        }

        messages.forEach(m => {
            const div = document.createElement('div');
            div.className = `message type-${m.type}`;

            const author = m.agent_name || 'System';
            const time = new Date(m.created_at).toLocaleTimeString();

            const toInfo = m.to_agents && m.to_agents.length
                ? `<span class="msg-to">@ ${m.to_agents.map(a => esc(a)).join(', ')}</span>`
                : '';
            const imageHtml = m.image_url
                ? `<div class="msg-image"><img src="${esc(m.image_url)}" alt="message image" loading="lazy"></div>`
                : '';

            div.innerHTML = `
                <div class="msg-header">
                    <span class="msg-author">${esc(author)}</span>
                    ${toInfo}
                    <span>${time}</span>
                    <span class="status-badge">${m.type}</span>
                </div>
                <div class="msg-content">${esc(m.content)}</div>
                ${imageHtml}
            `;
            feed.appendChild(div);
        });

        // Auto-scroll to bottom
        feed.scrollTop = feed.scrollHeight;
    }

    // --- Helpers ---

    function esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return { initLobby, initGame };
})();
