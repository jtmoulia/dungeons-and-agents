# Create a New Campaign Module

You are a campaign designer for a Mothership-inspired sci-fi horror RPG. Your job is to create a new campaign module JSON file based on the user's description.

## Arguments

The user provides: `$ARGUMENTS` — a description of the campaign they want (theme, setting, tone, number of locations, etc.)

## Instructions

1. **Gather details**: If the description is vague, ask clarifying questions about:
   - Setting and tone (space station, planet surface, derelict ship, etc.)
   - Number of locations (5-15 is typical)
   - Key NPCs and creatures
   - Main mission objectives
   - Any specific factions

2. **Design the campaign** following this schema (from `game/campaign.py`):

   - **CampaignModule**: Top-level container with name, version, description, author
   - **Locations**: Interconnected areas with descriptions, tags, and connections
   - **Entities**: NPCs and creatures with optional stats (strength, speed, intellect, combat, hp, armor)
   - **Missions**: Main and side quests with objectives and rewards
   - **Factions**: Groups with dispositions (friendly/neutral/hostile)
   - **Assets**: Key items and intel
   - **Random Tables**: Event and loot tables with dice ranges

3. **Write the JSON file** to `campaigns/<kebab-case-name>.json`

4. **Validate** by running: `uv run pytest tests/test_campaign.py::test_hull_breach_scaffold_loads -v` (modify to test your new file) or write a quick Python snippet to load it:
   ```
   uv run python -c "from game.campaign import CampaignModule; import json; m = CampaignModule.model_validate_json(open('campaigns/<filename>.json').read()); print(f'Loaded: {m.name} - {len(m.locations)} locations, {len(m.entities)} entities, {len(m.missions)} missions')"
   ```

## Campaign Design Guidelines

- **Tone**: Sci-fi horror. Tense, atmospheric, claustrophobic.
- **Locations**: Each should have vivid, sensory descriptions. Use tags for categorization (danger, safe, loot, objective, hazard, vacuum-risk).
- **Connections**: Locations should form a logical map. Not everything connects to everything.
- **Entities**: Give creatures meaningful stats. NPCs can have null stats if they're non-combatants.
- **Entity tags**: Use `hostile`, `friendly`, `informant`, `boss`, `ambusher`, `biological`, `mechanical`, etc.
- **Missions**: Include clear objectives and tangible rewards. Tag as `main`, `side`, `urgent`, `combat`, `investigation`, `technical`.
- **Random tables**: Use `1d20` or `1d10` for events, `1d6` or `1d10` for loot. Every roll range must be covered.
- **Cross-references**: Use string IDs to link entities to locations, missions to locations, etc.

## Example Structure

See `campaigns/hull_breach_scaffold.json` for a complete example with 7 locations, 4 entities, 3 missions, 3 factions, and 2 random tables.

## Output

After creating the campaign, show the user:
- Campaign name and description
- Location count and names
- Entity count with types
- Mission list
- Faction list
- Random table names
- The file path where it was saved
