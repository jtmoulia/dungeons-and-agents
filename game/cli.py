"""Click CLI for the Mothership-inspired game engine."""

from __future__ import annotations

import json
from pathlib import Path

import click

from game.combat import CombatEngine
from game.engine import EngineError, GameEngine
from game.models import CharacterClass, Controller


def get_engine(ctx: click.Context) -> GameEngine:
    return ctx.obj["engine"]


def get_combat(ctx: click.Context) -> CombatEngine:
    return ctx.obj["combat"]


@click.group()
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("state"),
    help="Directory for game state files.",
)
@click.pass_context
def cli(ctx: click.Context, state_dir: Path) -> None:
    """Mothership-inspired RPG game engine."""
    ctx.ensure_object(dict)
    engine = GameEngine(state_dir / "game.json")
    ctx.obj["engine"] = engine
    ctx.obj["combat"] = CombatEngine(engine)


@cli.command()
@click.option("--name", default="Untitled Game", help="Name for the game session.")
@click.pass_context
def init(ctx: click.Context, name: str) -> None:
    """Initialize a new game session."""
    engine = get_engine(ctx)
    state = engine.init_game(name)
    click.echo(f"Game '{state.name}' initialized.")


@cli.command()
@click.pass_context
def state(ctx: click.Context) -> None:
    """Show full game state as JSON."""
    engine = get_engine(ctx)
    try:
        gs = engine.get_state()
        click.echo(gs.model_dump_json(indent=2))
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Character commands ---


@cli.group()
def character() -> None:
    """Character management commands."""


@character.command("create")
@click.argument("name")
@click.argument("char_class", type=click.Choice([c.value for c in CharacterClass]))
@click.option(
    "--controller",
    type=click.Choice([c.value for c in Controller]),
    default="ai",
    help="Who controls this character.",
)
@click.pass_context
def character_create(
    ctx: click.Context, name: str, char_class: str, controller: str
) -> None:
    """Create a new character."""
    engine = get_engine(ctx)
    try:
        char = engine.create_character(
            name, CharacterClass(char_class), Controller(controller)
        )
        click.echo(f"Created {char.name} ({char.char_class.value})")
        click.echo(f"  Stats: STR {char.stats.strength} SPD {char.stats.speed} "
                    f"INT {char.stats.intellect} CMB {char.stats.combat}")
        click.echo(f"  Saves: SAN {char.saves.sanity} FEAR {char.saves.fear} "
                    f"BODY {char.saves.body}")
        skills_display = ", ".join(
            f"{s} ({lvl.value})" for s, lvl in char.skills.items()
        )
        click.echo(f"  HP: {char.hp}/{char.max_hp}  Stress: {char.stress}  "
                    f"Skills: {skills_display}")
    except EngineError as e:
        raise click.ClickException(str(e))


@character.command("show")
@click.argument("name")
@click.pass_context
def character_show(ctx: click.Context, name: str) -> None:
    """Show a character sheet."""
    engine = get_engine(ctx)
    try:
        char = engine.get_character(name)
        click.echo(f"=== {char.name} ({char.char_class.value}) ===")
        click.echo(f"Controller: {char.controller.value}  Alive: {char.alive}")
        click.echo(f"HP: {char.hp}/{char.max_hp}  Wounds: {char.wounds}/{char.max_wounds}  "
                    f"Stress: {char.stress}")
        click.echo(f"Stats: STR {char.stats.strength}  SPD {char.stats.speed}  "
                    f"INT {char.stats.intellect}  CMB {char.stats.combat}")
        click.echo(f"Saves: SAN {char.saves.sanity}  FEAR {char.saves.fear}  "
                    f"BODY {char.saves.body}")
        click.echo(f"Armor: {char.armor.name} (AP {char.armor.ap})")
        if char.weapons:
            for w in char.weapons:
                click.echo(f"Weapon: {w.name} ({w.damage}, {w.range})")
        if char.skills:
            skills_display = ", ".join(
                f"{s} ({lvl.value})" for s, lvl in char.skills.items()
            )
            click.echo(f"Skills: {skills_display}")
        else:
            click.echo("Skills: none")
        click.echo(f"Inventory: {', '.join(char.inventory) or 'empty'}")
        if char.conditions:
            click.echo(f"Conditions: {', '.join(c.value for c in char.conditions)}")
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Roll ---


@cli.command()
@click.argument("name")
@click.argument("stat")
@click.option("--skill", default=None, help="Skill to apply bonus for.")
@click.option("--advantage", "-a", is_flag=True, help="Roll with advantage (roll twice, take lower).")
@click.option("--disadvantage", "-d", is_flag=True, help="Roll with disadvantage (roll twice, take higher).")
@click.pass_context
def roll(
    ctx: click.Context,
    name: str,
    stat: str,
    skill: str | None,
    advantage: bool,
    disadvantage: bool,
) -> None:
    """Roll a d100 stat check for a character."""
    engine = get_engine(ctx)
    try:
        result = engine.roll_check(
            name, stat, skill,
            advantage=advantage, disadvantage=disadvantage,
        )
        rolls_info = ""
        if len(result.all_rolls) > 1:
            rolls_info = f" (rolls: {result.all_rolls[0]}, {result.all_rolls[1]})"
        click.echo(
            f"{name} rolls {stat}: {result.roll} vs {result.target} "
            f"-> {result.result.value}"
            + (" (doubles!)" if result.doubles else "")
            + rolls_info
        )
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Damage / Heal ---


@cli.command()
@click.argument("name")
@click.argument("amount", type=int)
@click.pass_context
def damage(ctx: click.Context, name: str, amount: int) -> None:
    """Apply damage to a character."""
    engine = get_engine(ctx)
    try:
        result = engine.apply_damage(name, amount)
        click.echo(f"{name}: {result['raw_damage']} raw damage")
        if result["absorbed"]:
            click.echo(f"  Armor absorbed: {result['absorbed']}")
        click.echo(f"  Damage taken: {result['damage_taken']}")
        if result["wound"]:
            click.echo("  Wound gained!")
        if result["dead"]:
            click.echo("  CHARACTER DEAD!")
    except EngineError as e:
        raise click.ClickException(str(e))


@cli.command()
@click.argument("name")
@click.argument("amount", type=int)
@click.pass_context
def heal(ctx: click.Context, name: str, amount: int) -> None:
    """Heal a character."""
    engine = get_engine(ctx)
    try:
        healed = engine.heal(name, amount)
        click.echo(f"{name} healed {healed} HP.")
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Stress / Panic ---


@cli.command()
@click.argument("name")
@click.argument("amount", type=int)
@click.pass_context
def stress(ctx: click.Context, name: str, amount: int) -> None:
    """Add or remove stress from a character."""
    engine = get_engine(ctx)
    try:
        new_stress = engine.add_stress(name, amount)
        click.echo(f"{name} stress is now {new_stress}.")
    except EngineError as e:
        raise click.ClickException(str(e))


@cli.command()
@click.argument("name")
@click.pass_context
def panic(ctx: click.Context, name: str) -> None:
    """Make a panic check for a character."""
    engine = get_engine(ctx)
    try:
        result = engine.panic_check(name)
        if result["panicked"]:
            click.echo(
                f"{name} PANICS! (rolled {result['roll']} vs stress {result['stress']})"
            )
            click.echo(f"  Effect: {result['effect']}")
        else:
            click.echo(
                f"{name} keeps it together (rolled {result['roll']} vs stress {result['stress']})."
            )
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Inventory ---


@cli.group()
def inventory() -> None:
    """Inventory management commands."""


@inventory.command("add")
@click.argument("name")
@click.argument("item")
@click.pass_context
def inventory_add(ctx: click.Context, name: str, item: str) -> None:
    """Add an item to a character's inventory."""
    engine = get_engine(ctx)
    try:
        inv = engine.add_inventory(name, item)
        click.echo(f"{name} now has: {', '.join(inv)}")
    except EngineError as e:
        raise click.ClickException(str(e))


@inventory.command("remove")
@click.argument("name")
@click.argument("item")
@click.pass_context
def inventory_remove(ctx: click.Context, name: str, item: str) -> None:
    """Remove an item from a character's inventory."""
    engine = get_engine(ctx)
    try:
        inv = engine.remove_inventory(name, item)
        click.echo(f"{name} now has: {', '.join(inv) or 'nothing'}")
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Combat ---


@cli.group()
def combat() -> None:
    """Combat encounter commands."""


@combat.command("start")
@click.argument("combatants", nargs=-1, required=True)
@click.pass_context
def combat_start(ctx: click.Context, combatants: tuple[str, ...]) -> None:
    """Start a combat encounter with the named combatants."""
    combat_engine = get_combat(ctx)
    try:
        cs = combat_engine.start_combat(list(combatants))
        click.echo(f"Combat started! Round {cs.round}")
        click.echo("Initiative order:")
        for i, c in enumerate(cs.combatants):
            marker = " <--" if i == cs.current_index else ""
            click.echo(f"  {c.name} (initiative {c.initiative}){marker}")
    except EngineError as e:
        raise click.ClickException(str(e))


@combat.command("action")
@click.argument("name")
@click.argument("action")
@click.option("--target", "-t", default=None, help="Target of the action.")
@click.option("--advantage", "-a", is_flag=True, help="Roll with advantage.")
@click.option("--disadvantage", "-d", is_flag=True, help="Roll with disadvantage.")
@click.pass_context
def combat_action(
    ctx: click.Context,
    name: str,
    action: str,
    target: str | None,
    advantage: bool,
    disadvantage: bool,
) -> None:
    """Perform a combat action."""
    combat_engine = get_combat(ctx)
    try:
        result = combat_engine.combat_action(
            name, action, target,
            advantage=advantage, disadvantage=disadvantage,
        )
        click.echo(f"{result['actor']} -> {result['action']}")
        if "check_result" in result:
            click.echo(f"  Roll: {result['roll']} ({result['check_result']})")
        if result.get("damage"):
            click.echo(f"  Damage: {result['damage']} ({result.get('weapon', 'unknown')})")
        if result.get("effect"):
            click.echo(f"  Effect: {result['effect']}")
        if "fled" in result:
            click.echo(f"  Fled: {'yes' if result['fled'] else 'no'}")
    except EngineError as e:
        raise click.ClickException(str(e))


@combat.command("end")
@click.pass_context
def combat_end(ctx: click.Context) -> None:
    """End the current combat encounter."""
    combat_engine = get_combat(ctx)
    try:
        combat_engine.end_combat()
        click.echo("Combat ended.")
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Scene ---


@cli.command()
@click.argument("description")
@click.pass_context
def scene(ctx: click.Context, description: str) -> None:
    """Set the current scene description."""
    engine = get_engine(ctx)
    try:
        engine.set_scene(description)
        click.echo(f"Scene set: {description}")
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Log ---


@cli.command()
@click.option("--count", "-n", default=20, help="Number of log entries to show.")
@click.pass_context
def log(ctx: click.Context, count: int) -> None:
    """Show recent game log entries."""
    engine = get_engine(ctx)
    try:
        entries = engine.get_log(count)
        if not entries:
            click.echo("No log entries.")
            return
        for entry in entries:
            click.echo(f"[{entry.category}] {entry.message}")
    except EngineError as e:
        raise click.ClickException(str(e))


# --- Campaign ---


@cli.group()
def campaign() -> None:
    """Campaign module management commands."""


@campaign.command("discover")
@click.option(
    "--dir", "search_dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path("campaigns"),
    help="Directory to search for campaign JSON files.",
)
@click.pass_context
def campaign_discover(ctx: click.Context, search_dir: Path) -> None:
    """Discover available campaign modules in a directory."""
    from game.campaign_engine import CampaignManager

    manager = CampaignManager()
    modules = manager.discover(search_dir)
    if not modules:
        click.echo(f"No campaign modules found in {search_dir}/")
        return
    click.echo(f"Found {len(modules)} campaign module(s):")
    for path, module in modules.items():
        click.echo(f"  {module.name} (v{module.version}) - {path}")


@campaign.command("load")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def campaign_load(ctx: click.Context, path: Path) -> None:
    """Load a campaign module from a JSON file."""
    from game.campaign_engine import CampaignManager, CampaignError

    manager = CampaignManager()
    try:
        module = manager.load(path)
        click.echo(f"Loaded: {module.name} (v{module.version})")
        click.echo(f"  Locations: {len(module.locations)}")
        click.echo(f"  Entities: {len(module.entities)}")
        click.echo(f"  Missions: {len(module.missions)}")
        click.echo(f"  Factions: {len(module.factions)}")
        click.echo(f"  Random Tables: {len(module.random_tables)}")
    except CampaignError as e:
        raise click.ClickException(str(e))


@campaign.command("activate")
@click.argument("name")
@click.pass_context
def campaign_activate(ctx: click.Context, name: str) -> None:
    """Set the active campaign for the current game."""
    engine = get_engine(ctx)
    try:
        engine.set_campaign(name)
        click.echo(f"Active campaign set to '{name}'.")
    except EngineError as e:
        raise click.ClickException(str(e))


@campaign.command("locations")
@click.argument("name")
@click.option("--tag", default=None, help="Filter locations by tag.")
@click.pass_context
def campaign_locations(ctx: click.Context, name: str, tag: str | None) -> None:
    """List locations in a loaded campaign module."""
    from game.campaign_engine import CampaignManager, CampaignError

    manager = CampaignManager()
    try:
        # Find and load the campaign by name from campaigns dir
        modules = manager.discover(Path("campaigns"))
        module = None
        for path, mod in modules.items():
            if mod.name == name:
                module = mod
                break
        if not module:
            raise click.ClickException(f"Campaign '{name}' not found. Run 'campaign discover' to see available modules.")

        locations = manager.query_locations(module, tag=tag)
        if not locations:
            click.echo("No locations found" + (f" with tag '{tag}'" if tag else "") + ".")
            return
        for loc_id, loc in locations.items():
            tags = f" [{', '.join(loc.tags)}]" if loc.tags else ""
            click.echo(f"  {loc_id}: {loc.name}{tags}")
            if loc.description:
                click.echo(f"    {loc.description[:80]}...")
    except CampaignError as e:
        raise click.ClickException(str(e))


@campaign.command("entity")
@click.argument("campaign_name")
@click.argument("entity_id")
@click.pass_context
def campaign_entity(ctx: click.Context, campaign_name: str, entity_id: str) -> None:
    """Show details of an entity in a campaign module."""
    from game.campaign_engine import CampaignManager, CampaignError

    manager = CampaignManager()
    try:
        modules = manager.discover(Path("campaigns"))
        module = None
        for path, mod in modules.items():
            if mod.name == campaign_name:
                module = mod
                break
        if not module:
            raise click.ClickException(f"Campaign '{campaign_name}' not found.")

        entity = manager.get_entity(module, entity_id)
        click.echo(f"=== {entity.name} ===")
        click.echo(f"Type: {entity.entity_type}")
        if entity.description:
            click.echo(f"Description: {entity.description}")
        if entity.stats:
            click.echo(f"Stats: STR {entity.stats.strength} SPD {entity.stats.speed} "
                        f"INT {entity.stats.intellect} CMB {entity.stats.combat}")
            click.echo(f"HP: {entity.stats.hp}  Armor: {entity.stats.armor}")
        if entity.tags:
            click.echo(f"Tags: {', '.join(entity.tags)}")
    except CampaignError as e:
        raise click.ClickException(str(e))


@campaign.command("mission")
@click.argument("campaign_name")
@click.argument("mission_id")
@click.pass_context
def campaign_mission(ctx: click.Context, campaign_name: str, mission_id: str) -> None:
    """Show details of a mission in a campaign module."""
    from game.campaign_engine import CampaignManager, CampaignError

    manager = CampaignManager()
    try:
        modules = manager.discover(Path("campaigns"))
        module = None
        for path, mod in modules.items():
            if mod.name == campaign_name:
                module = mod
                break
        if not module:
            raise click.ClickException(f"Campaign '{campaign_name}' not found.")

        mission = manager.get_mission(module, mission_id)
        click.echo(f"=== {mission.name} ===")
        if mission.description:
            click.echo(f"Description: {mission.description}")
        if mission.objectives:
            click.echo("Objectives:")
            for obj in mission.objectives:
                click.echo(f"  - {obj}")
        if mission.rewards:
            click.echo("Rewards:")
            for reward in mission.rewards:
                click.echo(f"  - {reward}")
        if mission.tags:
            click.echo(f"Tags: {', '.join(mission.tags)}")
    except CampaignError as e:
        raise click.ClickException(str(e))


@campaign.command("roll-table")
@click.argument("campaign_name")
@click.argument("table_id")
@click.pass_context
def campaign_roll_table(ctx: click.Context, campaign_name: str, table_id: str) -> None:
    """Roll on a random table in a campaign module."""
    from game.campaign_engine import CampaignManager, CampaignError

    manager = CampaignManager()
    try:
        modules = manager.discover(Path("campaigns"))
        module = None
        for path, mod in modules.items():
            if mod.name == campaign_name:
                module = mod
                break
        if not module:
            raise click.ClickException(f"Campaign '{campaign_name}' not found.")

        roll, entry = manager.roll_on_table(module, table_id)
        click.echo(f"Rolled {roll} on '{module.random_tables[table_id].name}':")
        click.echo(f"  {entry.description}")
        if entry.effect:
            click.echo(f"  Effect: {entry.effect}")
    except CampaignError as e:
        raise click.ClickException(str(e))
