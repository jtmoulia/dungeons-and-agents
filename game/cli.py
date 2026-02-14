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
        click.echo(f"  HP: {char.hp}/{char.max_hp}  Stress: {char.stress}  "
                    f"Skills: {', '.join(char.skills)}")
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
        click.echo(f"Skills: {', '.join(char.skills) or 'none'}")
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
@click.pass_context
def roll(ctx: click.Context, name: str, stat: str, skill: str | None) -> None:
    """Roll a d100 stat check for a character."""
    engine = get_engine(ctx)
    try:
        result = engine.roll_check(name, stat, skill)
        click.echo(
            f"{name} rolls {stat}: {result.roll} vs {result.target} "
            f"-> {result.result.value}"
            + (" (doubles!)" if result.doubles else "")
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
@click.pass_context
def combat_action(
    ctx: click.Context, name: str, action: str, target: str | None
) -> None:
    """Perform a combat action."""
    combat_engine = get_combat(ctx)
    try:
        result = combat_engine.combat_action(name, action, target)
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
