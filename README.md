# dnd-party

A Mothership-inspired RPG game engine designed for Claude Code Agent Teams. AI agents play characters, roll dice, manage combat encounters, and explore campaign modules — all through a CLI.

## Quick Start

```bash
# Install dependencies
uv sync

# Initialize a game
uv run game init --name "Deep Space Horror"

# Create characters
uv run game character create Alice marine --controller user
uv run game character create ARIA android --controller ai

# Roll a stat check
uv run game roll Alice combat --skill "Military Training"

# Roll with advantage
uv run game roll Alice combat --advantage --skill "Military Training"
```

## Features

### Core Mechanics

- **d100 roll-under system** — Roll under your stat to succeed. 90+ always fails. Doubles on success = critical success, doubles on failure = critical failure.
- **Advantage/Disadvantage** — Roll twice; advantage takes the lower (better), disadvantage takes the higher. Both cancel out.
- **Stress & Panic** — Failed checks add stress. Panic checks (d20 vs stress) trigger effects from the panic table.
- **Wounds & Death** — HP drops to 0 = wound + HP reset. Max wounds = death.
- **Armor** — Absorbs damage up to AP, then is destroyed.

### Skill Tiers

Characters have skills at three proficiency levels:

| Tier | Bonus | Description |
|------|-------|-------------|
| Trained | +10 | Starting level for class skills |
| Expert | +15 | Improved through experience |
| Master | +20 | Peak proficiency |

### Character Classes

| Class | Strengths | Starting Skills |
|-------|-----------|-----------------|
| Marine | Combat, Body | Military Training, Athletics |
| Scientist | Intellect, Sanity | Computers, First Aid |
| Teamster | Balanced, Fear | Mechanical Repair, Zero-G |
| Android | All-around, Fear-immune | Linguistics, Mathematics |

### Campaign Modules

Campaign modules are JSON files defining locations, entities, missions, factions, and random tables. Load them to structure adventures:

```bash
uv run game campaign load campaigns/hull_breach_scaffold.json
uv run game campaign locations "Hull Breach Scaffold"
uv run game campaign entity "Hull Breach Scaffold" creature_alpha
uv run game campaign roll-table "Hull Breach Scaffold" station_events
```

### Combat

```bash
# Start combat (rolls initiative automatically)
uv run game combat start Alice ARIA

# Take actions
uv run game combat action Alice attack -t ARIA
uv run game combat action ARIA defend
uv run game combat action Alice attack -t ARIA --advantage

# End combat
uv run game combat end
```

## CLI Reference

| Command | Description |
|---|---|
| `game init --name NAME` | Start new game session |
| `game state` | View full game state (JSON) |
| `game character create NAME CLASS [--controller ai\|user\|npc]` | Create character |
| `game character show NAME` | View character sheet |
| `game roll NAME STAT [--skill SKILL] [-a] [-d]` | d100 stat check |
| `game damage NAME AMOUNT` | Apply damage |
| `game heal NAME AMOUNT` | Restore HP |
| `game stress NAME AMOUNT` | Modify stress |
| `game panic NAME` | Panic check |
| `game inventory add NAME ITEM` | Give item |
| `game inventory remove NAME ITEM` | Remove item |
| `game combat start NAME1 NAME2 ...` | Begin encounter |
| `game combat action NAME ACTION [-t TARGET] [-a] [-d]` | Combat action |
| `game combat end` | End combat |
| `game scene DESCRIPTION` | Set scene |
| `game log -n COUNT` | View game log |
| `game campaign discover [--dir DIR]` | Find campaign modules |
| `game campaign load PATH` | Load campaign from JSON |
| `game campaign activate NAME` | Set active campaign |
| `game campaign locations NAME [--tag TAG]` | List locations |
| `game campaign entity CAMPAIGN ENTITY_ID` | Show entity details |
| `game campaign mission CAMPAIGN MISSION_ID` | Show mission details |
| `game campaign roll-table CAMPAIGN TABLE_ID` | Roll on random table |

## Agent Team Play

The engine is designed for multi-agent RPG sessions where Claude Code agents play as characters:

1. A **Warden** (DM) agent narrates the story and resolves all mechanics via CLI
2. **Character agents** respond in-character with their declared actions
3. **User-controlled** characters get prompted for input
4. See `prompts/dm.md` for the full Warden prompt

## Development

```bash
# Run tests
uv run pytest

# Run tests with verbose output
uv run pytest -v
```

## Project Structure

```
game/
  cli.py              # Click CLI interface
  engine.py            # Core game engine with JSON persistence
  combat.py            # Combat encounter system
  dice.py              # Dice rolling with advantage/disadvantage
  models.py            # Pydantic v2 data models
  tables.py            # Class stats, skills, panic table, equipment
  campaign.py          # Campaign module data models
  campaign_engine.py   # Campaign loader and query manager
campaigns/
  hull_breach_scaffold.json  # Example campaign module
prompts/
  dm.md                # Warden (DM) system prompt
tests/
  test_dice.py         # Dice and check resolution tests
  test_models.py       # Model serialization/validation tests
  test_engine.py       # Game engine tests
  test_campaign.py     # Campaign system tests
```
