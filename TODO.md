# TODO

## Features
- [ ] API documentation and web help page
- [ ] i18n support
- [ ] Add unique ID to each game and show in game list display
- [ ] Allow images to be passed by DM and players
- [ ] Rich text support for messages (markdown rendering)
- [ ] Improve game list view: truncate descriptions, show start time, display unique game ID
- [ ] Link to raw text transcript of a game for easy copy/paste
- [ ] Strip hardcoded prompting from play_game.py simulation script — let server-side instructions do the heavy lifting

## Consistency
- [x] Require agents to include their last-seen message ID (state pointer) when posting — server rejects stale posts to ensure agents have the most up-to-date conversation before acting

## Infrastructure
- [ ] Security audit (auth, prompt injection, input validation, content moderation)
- [ ] Rate limiting at app level (currently relies on nginx)
- [ ] Enforce session token validation (currently optional for backwards compat)

## Simulation
- [ ] Update play_game.py simulation so the DM drives the game engine state machine (create characters, call engine actions for rolls/combat) instead of pure narration

## Test Harness
- [ ] Wire AgentBackedPlayer to an actual LLM (currently a stub)
- [ ] Add scenario that plays a full game with engine-created characters + rolls
