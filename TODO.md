# TODO

## Features
- [ ] API documentation and web help page
- [ ] i18n support
- [ ] Add unique ID to each game and show in game list display
- [ ] Allow images to be passed by DM and players

## Infrastructure
- [ ] Rate limiting at app level (currently relies on nginx)
- [ ] Enforce session token validation (currently optional for backwards compat)

## Test Harness
- [ ] Wire AgentBackedPlayer to an actual LLM (currently a stub)
- [ ] Add scenario that plays a full game with engine-created characters + rolls
