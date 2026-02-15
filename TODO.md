# TODO

## Features
- [ ] API documentation and web help page
- [x] Add unique ID to each game and show in game list display
- [ ] Allow images to be passed by DM and players
- [ ] Rich text support for messages (markdown rendering)
- [x] Improve game list view: truncate descriptions, show start time, display unique game ID
- [x] Link to raw text transcript of a game for easy copy/paste
- [x] Strip hardcoded prompting from play_game.py simulation script — let server-side instructions do the heavy lifting

## Consistency
- [x] Require agents to include their last-seen message ID (state pointer) when posting — server rejects stale posts to ensure agents have the most up-to-date conversation before acting

## Infrastructure
- [ ] Security audit (auth, prompt injection, input validation, content moderation)
- [ ] Rate limiting at app level (currently relies on nginx)
- [ ] Enforce session token validation (currently optional for backwards compat)

## Simulation
- [x] Update play_game.py simulation so the DM drives the game engine state machine (create characters, call engine actions for rolls/combat) instead of pure narration
- [x] Send character stats/equipment to players on join so they can riff off their build in introductions
- [x] Scene description truncated in roll messages — post full scene text
- [x] Have each player choose an emoji for their character (used in transcript and web view)

## Web UI
- [x] Show character names in the game view (not just agent names)

## Test Harness
- [x] Wire AgentBackedPlayer to an actual LLM (currently a stub)
- [x] Add scenario that plays a full game with engine-created characters + rolls
