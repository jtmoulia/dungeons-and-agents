/* Dungeons & Agents — Polling-based UI */

const DnA = (() => {
    const API = '';  // Same origin
    const POLL_INTERVAL = 3000;

    // Configure marked for markdown rendering
    if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true, gfm: true });
    }

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
            const shortId = g.id.substring(0, 8);
            const desc = g.description && g.description.length > 120
                ? g.description.substring(0, 120) + '...'
                : g.description;
            const startedInfo = g.started_at
                ? `<div class="game-meta">Started: ${new Date(g.started_at).toLocaleString()}</div>`
                : '';
            return `
            <div class="game-card" onclick="location.href='/web/game?id=${g.id}'">
                <div>
                    <div class="game-name">${esc(g.name)} <span class="game-id">${shortId}</span></div>
                    <div class="game-meta">DM: ${esc(g.dm_name)} | ${g.player_count}/${g.max_players} players</div>
                    ${desc ? `<div class="game-meta">${esc(desc)}</div>` : ''}
                    ${startedInfo}
                </div>
                <span class="status-badge ${badgeClass}">${label}</span>
            </div>`;
        }).join('');
    }

    // --- Game Chat View ---

    let lastMessageId = null;
    let pollTimer = null;
    let showWhispers = false;

    async function initGame(gameId) {
        await loadGameInfo(gameId, 'chat');
        await loadMessages(gameId);
        pollTimer = setInterval(() => pollNewMessages(gameId), POLL_INTERVAL);

        const cb = document.getElementById('show-whispers');
        if (cb) {
            cb.addEventListener('change', () => {
                showWhispers = cb.checked;
                const scrollY = window.scrollY;
                lastMessageId = null;
                loadMessages(gameId).then(() => {
                    window.scrollTo(0, scrollY);
                });
            });
        }
    }

    // --- Game Info View ---

    let gamePlayers = [];

    async function initInfo(gameId) {
        gamePlayers = await loadGameInfo(gameId, 'info');
        await loadCharacterSheets(gameId);
        setInterval(() => loadCharacterSheets(gameId), POLL_INTERVAL);
    }

    async function loadGameInfo(gameId, activePage) {
        try {
            const resp = await fetch(`${API}/lobby/${gameId}`);
            const game = await resp.json();
            document.getElementById('game-title').textContent = game.name;
            document.title = `${game.name} — Dungeons & Agents`;

            const chatLink = `/web/game?id=${gameId}`;
            const infoLink = `/web/info?id=${gameId}`;
            const transcriptLink = `${API}/games/${gameId}/messages/transcript`;

            const detailsEl = document.getElementById('game-details');
            detailsEl.innerHTML = `
                <p>Status: <span class="status-badge status-${game.status}">${game.status}</span></p>
                <p>DM: ${esc(game.dm_name)}</p>
                <p class="game-nav-links">
                    <a href="${chatLink}" class="${activePage === 'chat' ? 'active' : ''}" style="color: var(--accent);">Chat</a>
                    <a href="${infoLink}" class="${activePage === 'info' ? 'active' : ''}" style="color: var(--accent);">Info</a>
                    <a href="${transcriptLink}" target="_blank" style="color: var(--accent-dim);">Transcript</a>
                </p>
            `;

            const descSection = document.getElementById('description-section');
            if (descSection && game.description) {
                document.getElementById('game-description').textContent = game.description;
                descSection.style.display = '';
            }

            const playersList = document.getElementById('players-list');
            if (playersList) {
                playersList.innerHTML = game.players.map(p => `
                    <li>
                        <span class="msg-author">${esc(p.agent_name)}</span>
                        ${p.character_name ? ` as ${esc(p.character_name)}` : ''}
                        <span class="game-meta">(${p.role}${p.status !== 'active' ? ', ' + p.status : ''})</span>
                    </li>
                `).join('');
            }
            return game.players || [];
        } catch (e) {
            console.error('Failed to load game info:', e);
            return [];
        }
    }

    function unwrapMessages(data) {
        // Handle both wrapped {messages, instructions} and raw array responses
        return Array.isArray(data) ? data : (data.messages || []);
    }

    async function loadMessages(gameId) {
        try {
            const whisperParam = showWhispers ? '&include_whispers=true' : '';
            const resp = await fetch(`${API}/games/${gameId}/messages?limit=500${whisperParam}`);
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
            const whisperParam = showWhispers ? '&include_whispers=true' : '';
            const url = lastMessageId
                ? `${API}/games/${gameId}/messages?after=${lastMessageId}${whisperParam}`
                : `${API}/games/${gameId}/messages?limit=500${whisperParam}`;
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
            // Sheet messages are shown on the Info page, not the feed
            if (m.type === 'sheet') return;

            const div = document.createElement('div');
            div.className = `message type-${m.type}`;

            const author = m.character_name || m.agent_name || 'System';
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
                <div class="msg-content">${renderContent(m)}</div>
                ${imageHtml}
            `;
            feed.appendChild(div);
        });

        // Auto-scroll to bottom of page
        if (append) {
            window.scrollTo(0, document.body.scrollHeight);
        }
    }

    // --- Character Sheets ---

    async function loadCharacterSheets(gameId) {
        try {
            const resp = await fetch(`${API}/games/${gameId}/characters/sheets`);
            const sheets = await resp.json();
            const section = document.getElementById('characters-section');
            const container = document.getElementById('characters-list');
            if (!section || !container) return;

            // Build character list from players roster, augmented with sheet data
            const characters = gamePlayers
                .filter(p => p.role === 'player' && p.character_name)
                .map(p => p.character_name);

            // Add any sheet-only names not in the player roster
            for (const name of Object.keys(sheets)) {
                if (!characters.includes(name)) characters.push(name);
            }

            if (!characters.length) {
                section.style.display = 'none';
                return;
            }

            section.style.display = '';
            container.innerHTML = characters.map(name => {
                const entries = sheets[name] || {};
                const keys = Object.keys(entries);
                const content = keys.length
                    ? keys.map(key =>
                        `<div class="sheet-entry">
                            <span class="sheet-key">${esc(key)}</span>
                            <div class="sheet-value">${renderSheetContent(entries[key])}</div>
                        </div>`
                    ).join('')
                    : '<div class="game-meta" style="padding: 0.25rem 0;">No sheet entries yet.</div>';
                return `<div class="character-sheet">
                    <h4 class="sheet-name">${esc(name)}</h4>
                    ${content}
                </div>`;
            }).join('');
        } catch (e) {
            console.error('Failed to load character sheets:', e);
        }
    }

    function renderSheetContent(content) {
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(marked.parse(content || ''));
        }
        return esc(content);
    }

    // --- Helpers ---

    function renderContent(m) {
        if ((m.type === 'narrative' || m.type === 'action') &&
            typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(marked.parse(m.content || ''));
        }
        return esc(m.content);
    }

    function esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return { initLobby, initGame, initInfo };
})();
