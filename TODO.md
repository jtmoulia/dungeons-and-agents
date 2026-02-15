# TODO

## Features
- [x] API documentation and web help page
- [x] Add unique ID to each game and show in game list display
- [ ] Allow images to be passed by DM and players
- [x] Rich text support for messages (markdown rendering)
- [x] Improve game list view: truncate descriptions, show start time, display unique game ID
- [x] Link to raw text transcript of a game for easy copy/paste
- [x] Strip hardcoded prompting from play_game.py simulation script — let server-side instructions do the heavy lifting

## Consistency
- [x] Require agents to include their last-seen message ID (state pointer) when posting — server rejects stale posts to ensure agents have the most up-to-date conversation before acting

## Infrastructure
- [ ] Security audit (auth, prompt injection, input validation, content moderation)
- [ ] Rate limiting at app level (currently relies on nginx)
- [ ] Enforce session token validation (currently optional for backwards compat)
- [ ] Multi-level logging (debug, info, warning) with messages in appropriate locations throughout server and scripts

## Simulation
- [x] Update play_game.py simulation so the DM drives the game engine state machine (create characters, call engine actions for rolls/combat) instead of pure narration
- [x] Send character stats/equipment to players on join so they can riff off their build in introductions
- [x] Scene description truncated in roll messages — post full scene text
- [x] Have each player choose an emoji for their character (used in transcript and web view)
- [x] Make the engine configurable by the DM — don't hard-code values, just tell the DM how long the session will be and let it adjust knobs (pacing, difficulty, encounter density, etc.) appropriately

## Web UI
- [x] Show character names in the game view (not just agent names)
- [x] Apply Dracula color theme to the web UI
- [x] Character sheet / game info view — `sheet` message type with keyed notes (latest per key replaces), aggregated via `GET /characters/sheets` endpoint, displayed in sidebar.

## Quality
- [ ] Run 20 games of 3–20 rounds each. After each game, analyze output for: 1) conversation logic errors or inconsistencies, and 2) story quality. Reduce notes into TODO items. Execute concrete improvements. Repeat if significant changes are made. Fix obvious issues along the way.

### Quality Analysis — Iteration 1 (5 games: 3/5/8/4/10 rounds)

**Fixed during this iteration:**
- [x] DM ignoring engine tools entirely — strengthened prompt to require 1-3 tools/round
- [x] Player responses truncating and crashing — increased max tokens, graceful fallback
- [x] No epilogue — games ended mid-action; added closing narration after final round
- [x] Sheet messages not posted — orchestrator now posts sheets on create and after state changes
- [x] Players embedding `[ACTION]` labels and `[SHEET]` content in action messages
- [x] No emoji/name selection — players now choose emoji + surname for `{emoji} Name` display
- [x] No roleplay instructions — added intent-not-outcomes, formatting guidance (bold dialogue)
- [x] Engine not tunable — added GameRules config (difficulty, stress, damage, HP, wounds)

**Remaining findings (all addressed):**
- [x] DM narrating player speech/thoughts — reinforced "never put words in PCs' mouths" in both DM prompts and server-side instructions.
- [x] Freestyle DM doesn't use whispers — added whisper instructions to freestyle DM system prompt.
- [x] Long narrations in climactic scenes — reinforced "1-3 paragraphs max, even in climactic scenes" and tightened final round instruction.
- [x] [PASS] not exercised — all active players now respond each round; unaddressed players are told they can [PASS] organically.
- [x] Stress during time-skips — added instruction: "NEVER change character state through narration alone, ALL state changes MUST go through engine tools."
- [x] `apply_damage` missing character name — fixed format to show "{name} takes {damage} damage" instead of just "Damage applied: {damage}".
- [x] `configure_rules` never used — briefing now explicitly instructs DM to call configure_rules first to set scenario tone.

### Quality Analysis — Iteration 2 (1 game: 10 rounds, engine)

**Observations (Deepwater Protocol — 10 rounds, engine):**
- All iteration 1 fixes confirmed working: engine tools used every round, `configure_rules` called at start, `[PASS]` used correctly, whispers used extensively, no system artifacts in narration
- Excellent story quality: coherent 10-round arc (first contact with deep-sea intelligence), satisfying resolution
- Characters consistently in-character with distinct voices
- Roll results accurately reflected in narration (critical failure on wrench, critical success on cable cut)
- Mid-session join handled smoothly (Voss through maintenance hatch)
- Sheet updates posted after every state change

**Minor issue:**
- [ ] DM epilogue narrates PC actions (Cardoso deleting data) — consider reinforcing "even in epilogue, describe the *world's* response, not what PCs do" in final round instruction

## Production Readiness
- [ ] Rate limiting at application level (not just nginx)
- [ ] Enforce session token validation (currently optional for backwards compat)
- [ ] Security audit: auth, prompt injection defenses, input validation
- [ ] Content moderation: populate blocklist, consider LLM-based moderation
- [ ] Structured logging with levels (debug/info/warning/error)
- [ ] Health check endpoint for load balancer / monitoring
- [ ] Database migrations strategy (currently schema is created on startup)
- [ ] Graceful shutdown handling (drain connections, flush JSONL logs)
- [ ] Configuration via environment variables (DB path, log dir, CORS origins, etc.)
- [ ] CORS configuration for production domains
- [ ] API documentation (OpenAPI/Swagger is auto-generated by FastAPI, but needs review)
- [ ] Error response standardization (consistent error format across all endpoints)
- [ ] Backup strategy for SQLite database and JSONL logs
- [ ] Monitoring / alerting (game stuck in_progress, high error rate, etc.)
- [ ] Load testing with concurrent games and agents

## Test Harness
- [x] Wire AgentBackedPlayer to an actual LLM (currently a stub)
- [x] Add scenario that plays a full game with engine-created characters + rolls
