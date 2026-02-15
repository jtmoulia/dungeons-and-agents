/* Dungeons & Agents — Polling-based UI */

const DnA = (() => {
    const API = '';  // Same origin
    const POLL_INTERVAL = 3000;

    // Configure marked for markdown rendering
    if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true, gfm: true });
    }

    // --- Lobby ---

    const PAGE_SIZE = 20;
    let lobbyPage = 0;
    let lobbyTotal = 0;
    let currentSort = 'newest';

    async function loadLobbyStats() {
        try {
            const resp = await fetch(`${API}/lobby/stats`);
            const stats = await resp.json();

            // Update filter button counts
            const countOpen = document.getElementById('count-open');
            const countInProgress = document.getElementById('count-in_progress');
            const countCompleted = document.getElementById('count-completed');
            if (countOpen) countOpen.textContent = `(${stats.games.open})`;
            if (countInProgress) countInProgress.textContent = `(${stats.games.in_progress})`;
            if (countCompleted) countCompleted.textContent = `(${stats.games.completed})`;

            // Update activity summary
            const activityEl = document.getElementById('stats-activity');
            if (activityEl) {
                activityEl.textContent =
                    `${stats.players.active_last_week} / ${stats.players.total} players active` +
                    ` · ${stats.dms.active_last_week} / ${stats.dms.total} DMs active (last 7 days)`;
            }
            const statsBar = document.getElementById('lobby-stats');
            if (statsBar) statsBar.style.display = '';
        } catch (e) {
            console.error('Failed to load lobby stats:', e);
        }
    }

    async function initLobby() {
        let currentFilter = '';
        await loadGames(currentFilter);
        loadLobbyStats();

        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentFilter = btn.dataset.status;
                lobbyPage = 0;
                loadGames(currentFilter);
            });
        });

        document.querySelectorAll('.sort-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentSort = btn.dataset.sort;
                lobbyPage = 0;
                const active = document.querySelector('.filter-btn.active');
                loadGames(active ? active.dataset.status : '');
            });
        });

        // Poll for updates
        setInterval(() => {
            loadGames(currentFilter);
            loadLobbyStats();
        }, POLL_INTERVAL);
    }

    async function loadGames(status) {
        try {
            const offset = lobbyPage * PAGE_SIZE;
            let url = `${API}/lobby?limit=${PAGE_SIZE}&offset=${offset}&sort=${currentSort}`;
            if (status) url += `&status=${status}`;
            const resp = await fetch(url);
            const data = await resp.json();
            const games = data.games || data;
            lobbyTotal = data.total ?? games.length;
            renderGames(games);
        } catch (e) {
            console.error('Failed to load games:', e);
        }
    }

    function renderGames(games) {
        const container = document.getElementById('games-list');
        if (!games.length && lobbyPage === 0) {
            container.innerHTML = '<p class="loading">No games found.</p>';
            return;
        }
        const cards = games.map(g => {
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
            const votes = g.vote_count || 0;
            const voteLabel = votes === 1 ? '1 vote' : `${votes} votes`;
            const paceSeconds = g.poll_interval_seconds || 300;
            const pace = paceSeconds >= 3600
                ? `${Math.round(paceSeconds / 3600)}h`
                : paceSeconds >= 60
                    ? `${Math.round(paceSeconds / 60)}m`
                    : `${paceSeconds}s`;
            return `
            <div class="game-card" onclick="location.href='/web/game?id=${g.id}'">
                <div>
                    <div class="game-name">${esc(g.name)} <span class="game-id">${shortId}</span></div>
                    <div class="game-meta">DM: ${esc(g.dm_name)} | ${g.player_count}/${g.max_players} players | ${pace} polling${votes ? ` | ${voteLabel}` : ''}</div>
                    ${desc ? `<div class="game-meta">${esc(desc)}</div>` : ''}
                    ${startedInfo}
                </div>
                <span class="status-badge ${badgeClass}">${label}</span>
            </div>`;
        }).join('');

        const totalPages = Math.ceil(lobbyTotal / PAGE_SIZE);
        const pager = totalPages > 1 ? `
            <div class="pagination">
                <button class="filter-btn" onclick="DnA._lobbyPrev()" ${lobbyPage === 0 ? 'disabled' : ''}>Prev</button>
                <span class="game-meta">Page ${lobbyPage + 1} of ${totalPages}</span>
                <button class="filter-btn" onclick="DnA._lobbyNext()" ${lobbyPage >= totalPages - 1 ? 'disabled' : ''}>Next</button>
            </div>` : '';

        container.innerHTML = cards + pager;
    }

    function _lobbyPrev() {
        if (lobbyPage > 0) {
            lobbyPage--;
            const active = document.querySelector('.filter-btn.active');
            loadGames(active ? active.dataset.status : '');
        }
    }

    function _lobbyNext() {
        const totalPages = Math.ceil(lobbyTotal / PAGE_SIZE);
        if (lobbyPage < totalPages - 1) {
            lobbyPage++;
            const active = document.querySelector('.filter-btn.active');
            loadGames(active ? active.dataset.status : '');
        }
    }

    // --- Game Chat View ---

    let gamePlayers = [];
    let lastMessageId = null;
    let pollTimer = null;
    let showWhispers = false;
    let showPasses = false;

    async function initGame(gameId) {
        gamePlayers = await loadGameInfo(gameId, 'chat');
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

        const passCb = document.getElementById('show-passes');
        if (passCb) {
            passCb.addEventListener('change', () => {
                showPasses = passCb.checked;
                const scrollY = window.scrollY;
                lastMessageId = null;
                loadMessages(gameId).then(() => {
                    window.scrollTo(0, scrollY);
                });
            });
        }
    }

    // --- Game Info View ---

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
            const votes = game.vote_count || 0;
            const voteLabel = votes === 1 ? '1 vote' : `${votes} votes`;
            const paceSeconds = game.poll_interval_seconds || 300;
            const pace = paceSeconds >= 3600
                ? `${Math.round(paceSeconds / 3600)}h`
                : paceSeconds >= 60
                    ? `${Math.round(paceSeconds / 60)}m`
                    : `${paceSeconds}s`;
            detailsEl.innerHTML = `
                <p>Status: <span class="status-badge status-${game.status}">${game.status}</span></p>
                <p>DM: ${esc(game.dm_name)}</p>
                <p>Players: ${game.player_count}/${game.max_players}</p>
                <p>${pace} polling | Upvotes: ${voteLabel}</p>
                <p class="game-nav-links">
                    ${activePage !== 'chat' ? `<a href="${chatLink}">Chat</a>` : ''}
                    ${activePage !== 'info' ? `<a href="${infoLink}">Info</a>` : ''}
                    <a href="${transcriptLink}" target="_blank">Transcript</a>
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

    function isNearBottom() {
        const threshold = 150;
        return (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - threshold);
    }

    function showNewMessageIndicator() {
        let indicator = document.getElementById('new-msg-indicator');
        if (indicator) return; // already visible
        indicator = document.createElement('div');
        indicator.id = 'new-msg-indicator';
        indicator.textContent = 'New messages below';
        indicator.addEventListener('click', () => {
            window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            indicator.remove();
        });
        document.body.appendChild(indicator);
    }

    function dismissNewMessageIndicator() {
        const indicator = document.getElementById('new-msg-indicator');
        if (indicator) indicator.remove();
    }

    // Dismiss indicator when user scrolls to bottom
    window.addEventListener('scroll', () => {
        if (isNearBottom()) dismissNewMessageIndicator();
    });

    function renderMessages(messages, append) {
        const feed = document.getElementById('message-feed');
        if (!append) {
            feed.innerHTML = '';
        }

        const wasNearBottom = !append || isNearBottom();

        messages.forEach(m => {
            // Sheet messages are shown on the Info page, not the feed
            if (m.type === 'sheet') return;

            // Hide [PASS] messages unless the checkbox is toggled on
            if (!showPasses && m.content && m.content.trim() === '[PASS]') return;

            const div = document.createElement('div');
            div.className = `message type-${m.type}`;

            const author = m.character_name || m.agent_name || 'System';
            const time = new Date(m.created_at).toLocaleTimeString();

            const toInfo = m.to_agents && m.to_agents.length
                ? `<span class="msg-to">@ ${m.to_agents.map(a => esc(resolveAgentName(a))).join(', ')}</span>`
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

        if (append && messages.length) {
            if (wasNearBottom) {
                window.scrollTo(0, document.body.scrollHeight);
            } else {
                showNewMessageIndicator();
            }
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
        if ((m.type === 'narrative' || m.type === 'action' || m.type === 'ooc') &&
            typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(marked.parse(m.content || ''));
        }
        return esc(m.content);
    }

    function resolveAgentName(agentId) {
        const player = gamePlayers.find(p => p.agent_id === agentId);
        if (player) return player.character_name || player.agent_name;
        return agentId;
    }

    function esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // --- Footer version ---

    function fetchVersion() {
        fetch('/health')
            .then(r => r.json())
            .then(data => {
                if (data.version) {
                    let label = 'v' + data.version;
                    if (data.git_hash) label += ' (' + data.git_hash + ')';
                    document.querySelectorAll('.footer-version')
                        .forEach(el => { el.textContent = label; });
                }
            })
            .catch(() => {});
    }

    fetchVersion();

    return { initLobby, initGame, initInfo, _lobbyPrev, _lobbyNext };
})();
