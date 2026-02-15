"""LLM-backed game agents for autonomous play-by-post games.

Provides GameAgent base class and AIPlayer/AIDM subclasses that use
the Anthropic Claude API to generate in-character actions and narration.
Each agent communicates with the server via the HTTP API.

Messages are cached locally — each agent only fetches new messages since
the last poll, using the ?after= parameter for efficient incremental reads.
"""

from __future__ import annotations

import json
import httpx
import anthropic


MODEL = "claude-sonnet-4-5-20250929"
DM_MAX_TOKENS = 1024
ENGINE_DM_MAX_TOKENS = 2048
PLAYER_MAX_TOKENS = 300


# ---------------------------------------------------------------------------
# Tool definitions for engine-backed DM (Anthropic tool use format)
# ---------------------------------------------------------------------------

ENGINE_TOOL_DEFINITIONS = [
    {
        "name": "roll_check",
        "description": (
            "Roll a d100 stat or save check for a character. Use for risky actions, "
            "contested situations, or moments of uncertainty. Roll-under: success if "
            "roll <= target. Critical success on doubles under target, critical failure "
            "on doubles over."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string", "description": "Name of the character making the check"},
                "stat": {
                    "type": "string",
                    "description": "Stat or save to check: strength, speed, intellect, combat, sanity, fear, body",
                },
                "skill": {"type": "string", "description": "Optional skill to apply bonus (e.g. 'mechanical_repair', 'zero_g')"},
                "advantage": {"type": "boolean", "description": "Roll twice, take better result"},
                "disadvantage": {"type": "boolean", "description": "Roll twice, take worse result"},
            },
            "required": ["character_name", "stat"],
        },
    },
    {
        "name": "apply_damage",
        "description": "Apply damage to a character. Armor absorbs first, then HP. At 0 HP: wound + HP reset. Max wounds = death.",
        "input_schema": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string", "description": "Name of the character taking damage"},
                "amount": {"type": "integer", "description": "Amount of damage to apply"},
            },
            "required": ["character_name", "amount"],
        },
    },
    {
        "name": "heal",
        "description": "Heal a character's HP (up to max_hp).",
        "input_schema": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string", "description": "Name of the character to heal"},
                "amount": {"type": "integer", "description": "Amount of HP to restore"},
            },
            "required": ["character_name", "amount"],
        },
    },
    {
        "name": "add_stress",
        "description": "Add (or remove with negative) stress to a character. High stress makes panic checks more likely.",
        "input_schema": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string", "description": "Name of the character"},
                "amount": {"type": "integer", "description": "Stress to add (negative to reduce)"},
            },
            "required": ["character_name", "amount"],
        },
    },
    {
        "name": "panic_check",
        "description": "Roll a panic check for a character (d20 vs stress). If roll <= stress, they panic with an effect from the panic table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string", "description": "Name of the character"},
            },
            "required": ["character_name"],
        },
    },
    {
        "name": "start_combat",
        "description": "Start a combat encounter. Rolls initiative for all combatants and sets turn order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "combatant_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of all characters entering combat",
                },
            },
            "required": ["combatant_names"],
        },
    },
    {
        "name": "combat_action",
        "description": "Execute a combat action: attack, defend, flee, or use_item. Only valid during active combat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string", "description": "Name of the acting character"},
                "action": {
                    "type": "string",
                    "enum": ["attack", "defend", "flee", "use_item"],
                    "description": "The combat action to take",
                },
                "target": {"type": "string", "description": "Target character name (required for attack)"},
                "advantage": {"type": "boolean", "description": "Roll with advantage"},
                "disadvantage": {"type": "boolean", "description": "Roll with disadvantage"},
            },
            "required": ["character_name", "action"],
        },
    },
    {
        "name": "end_combat",
        "description": "End the current combat encounter.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "set_scene",
        "description": "Set the current scene description in the engine state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "The scene description"},
            },
            "required": ["description"],
        },
    },
]


class GameAgent:
    """Base class for LLM-backed game agents."""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        llm: anthropic.Anthropic,
        http: httpx.Client,
        api_key: str,
        session_token: str,
        game_id: str,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm
        self.http = http
        self.api_key = api_key
        self.session_token = session_token
        self.game_id = game_id
        self._message_cache: list[dict] = []
        self._last_msg_id: str | None = None
        self._server_instructions: str = ""

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Session-Token": self.session_token,
        }

    def sync_messages(self) -> list[dict]:
        """Fetch only new messages since last sync, append to cache."""
        params: dict = {"limit": 500}
        if self._last_msg_id:
            params["after"] = self._last_msg_id
        resp = self.http.get(
            f"/games/{self.game_id}/messages",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        # Handle both wrapped response (with instructions) and raw list
        if isinstance(data, dict):
            new_msgs = data.get("messages", [])
            self._server_instructions = data.get("instructions", "")
        else:
            new_msgs = data
        if new_msgs:
            self._message_cache.extend(new_msgs)
            self._last_msg_id = new_msgs[-1]["id"]
        return self._message_cache

    def format_transcript(self, messages: list[dict]) -> str:
        """Convert game messages into a readable transcript for the LLM."""
        lines: list[str] = []
        for msg in messages:
            sender = msg.get("agent_name", "SYSTEM")
            whisper = " [whisper]" if msg.get("to_agents") else ""
            mtype = msg["type"].upper()
            content = msg["content"]

            if msg["type"] == "narrative":
                lines.append(f"[NARRATIVE]{whisper} WARDEN:\n{content}")
            elif msg["type"] == "action":
                lines.append(f"[ACTION] {sender}:\n{content}")
            elif msg["type"] == "ooc":
                lines.append(f"[OOC] {sender}: {content}")
            elif msg["type"] == "system":
                lines.append(f"[SYSTEM] {content}")
            else:
                lines.append(f"[{mtype}] {sender}: {content}")
        return "\n\n".join(lines)

    def generate(self, instruction: str, max_tokens: int = DM_MAX_TOKENS) -> str:
        """Call the LLM with system prompt + cached transcript + instruction."""
        all_messages = self.sync_messages()
        transcript = self.format_transcript(all_messages)

        user_content = ""
        if transcript:
            user_content += f"## Game transcript so far\n\n{transcript}\n\n---\n\n"
        if self._server_instructions:
            user_content += f"## Response instructions\n\n{self._server_instructions}\n\n---\n\n"
        user_content += f"## Your instruction\n\n{instruction}"

        response = self.llm.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        text = response.content[0].text
        if response.stop_reason == "max_tokens":
            print(f"  ⚠ {self.name} response truncated at {max_tokens} tokens, using partial response")
            text += "\n\n[truncated]"
        return text

    def post_message(self, content: str, msg_type: str, to_agents: list[str] | None = None) -> dict:
        """Post a message to the game and add it to the local cache."""
        body: dict = {"content": content, "type": msg_type}
        if to_agents:
            body["to_agents"] = to_agents
        resp = self.http.post(
            f"/games/{self.game_id}/messages",
            json=body,
            headers=self._headers(),
        )
        resp.raise_for_status()
        posted = resp.json()
        # Add to cache so we don't re-fetch our own message
        self._message_cache.append(posted)
        self._last_msg_id = posted["id"]
        return posted


class AIPlayer(GameAgent):
    """Player agent that generates in-character action declarations."""

    def take_turn(self, instruction: str = "It's your turn. Declare your action.") -> dict:
        """Generate and post an action message."""
        content = self.generate(instruction, max_tokens=PLAYER_MAX_TOKENS)
        return self.post_message(content, "action")


class AIDM(GameAgent):
    """DM agent that generates narration and manages game flow."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Character name → agent ID mapping, set by the orchestrator
        self.character_agents: dict[str, str] = {}

    @staticmethod
    def _extract_json(raw: str) -> dict | None:
        """Extract a JSON object from raw LLM text, handling preamble and code fences."""
        text = raw.strip()
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting from code fence
        if "```" in text:
            parts = text.split("```")
            for part in parts[1::2]:  # odd-indexed parts are inside fences
                inner = part.strip()
                if inner.startswith("json"):
                    inner = inner[4:].strip()
                try:
                    return json.loads(inner)
                except json.JSONDecodeError:
                    continue
        # Try finding a JSON object in the text
        start = text.find("{")
        if start >= 0:
            # Find the matching closing brace
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
        return None

    def _parse_dm_response(self, raw: str) -> dict:
        """Parse DM JSON response (narration, respond, whispers) from raw LLM output."""
        data = self._extract_json(raw)
        if data and "narration" in data:
            return {
                "narration": data["narration"],
                "respond": data.get("respond", []),
                "whispers": data.get("whispers", []),
            }
        # Fallback: try to clean up obvious JSON artifacts
        text = raw.strip()
        if text.startswith("```"):
            # Strip code fence wrapper even if JSON parse failed
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()
        return {"narration": text, "respond": [], "whispers": []}

    def _resolve_character_to_agents(self, character_names: list[str]) -> list[str]:
        """Look up agent IDs for character names."""
        # Build lookup from explicit mapping + message cache
        name_to_agent: dict[str, str] = {
            k.lower(): v for k, v in self.character_agents.items()
        }
        for msg in self._message_cache:
            cn = msg.get("character_name")
            aid = msg.get("agent_id")
            if cn and aid:
                name_to_agent[cn.lower()] = aid
        return [
            name_to_agent[n.lower()]
            for n in character_names
            if n.lower() in name_to_agent
        ]

    def _post_whispers(self, whispers) -> None:
        """Post whisper messages from the DM response.

        Handles multiple formats:
        - List of dicts: [{"to": ["Name"], "content": "..."}]
        - Dict mapping: {"Name": "content", ...}
        """
        if not whispers:
            return

        # Normalize to list of (names, content) tuples
        items: list[tuple[list[str], str]] = []
        if isinstance(whispers, dict):
            for name, content in whispers.items():
                if isinstance(content, str):
                    items.append(([name], content))
        elif isinstance(whispers, list):
            for w in whispers:
                if isinstance(w, dict):
                    to_names = w.get("to", [])
                    if isinstance(to_names, str):
                        to_names = [to_names]
                    content = w.get("content", "")
                    if to_names and content:
                        items.append((to_names, content))

        for to_names, content in items:
            agent_ids = self._resolve_character_to_agents(to_names)
            if agent_ids:
                self.post_message(content, "narrative", to_agents=agent_ids)

    def narrate(self, instruction: str) -> dict:
        """Generate narration as JSON with respond list, post whispers, then narration."""
        raw = self.generate(instruction)
        parsed = self._parse_dm_response(raw)

        # Post whispers first (before public narration)
        self._post_whispers(parsed["whispers"])

        result = self.post_message(parsed["narration"], "narrative")
        result["_respond"] = parsed["respond"]
        return result

    def whisper(self, to_agent_ids: list[str], instruction: str) -> dict:
        """Generate and post a whispered narrative message."""
        raw = self.generate(instruction)
        # Strip JSON wrapper if the LLM returned structured output
        try:
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            data = json.loads(text)
            content = data.get("narration", raw)
        except (json.JSONDecodeError, KeyError, AttributeError):
            content = raw
        return self.post_message(content, "narrative", to_agents=to_agent_ids)


class EngineAIDM(AIDM):
    """Engine-backed DM that uses Anthropic tool use to call GameEngine/CombatEngine."""

    def __init__(
        self,
        *,
        engine,  # game.engine.GameEngine
        combat_engine,  # game.combat.CombatEngine
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.engine = engine
        self.combat_engine = combat_engine

    def _execute_tool(self, name: str, params: dict) -> dict:
        """Dispatch a tool call to the appropriate engine method."""
        try:
            if name == "roll_check":
                result = self.engine.roll_check(
                    params["character_name"],
                    params["stat"],
                    skill=params.get("skill"),
                    advantage=params.get("advantage", False),
                    disadvantage=params.get("disadvantage", False),
                )
                return {
                    "character": params["character_name"],
                    "stat": params["stat"],
                    "roll": result.roll,
                    "target": result.target,
                    "result": result.result.value,
                    "succeeded": result.succeeded,
                    "all_rolls": result.all_rolls,
                }
            elif name == "apply_damage":
                return self.engine.apply_damage(params["character_name"], params["amount"])
            elif name == "heal":
                healed = self.engine.heal(params["character_name"], params["amount"])
                return {"character": params["character_name"], "healed": healed}
            elif name == "add_stress":
                stress = self.engine.add_stress(params["character_name"], params["amount"])
                return {"character": params["character_name"], "stress": stress}
            elif name == "panic_check":
                return self.engine.panic_check(params["character_name"])
            elif name == "start_combat":
                combat_state = self.combat_engine.start_combat(params["combatant_names"])
                return {
                    "active": combat_state.active,
                    "round": combat_state.round,
                    "turn_order": [c.name for c in combat_state.combatants],
                }
            elif name == "combat_action":
                return self.combat_engine.combat_action(
                    params["character_name"],
                    params["action"],
                    target=params.get("target"),
                    advantage=params.get("advantage", False),
                    disadvantage=params.get("disadvantage", False),
                )
            elif name == "end_combat":
                self.combat_engine.end_combat()
                return {"status": "combat ended"}
            elif name == "set_scene":
                self.engine.set_scene(params["description"])
                return {"scene": params["description"]}
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            return {"error": str(e)}

    def _format_engine_state(self) -> str:
        """Concise summary of engine state for the LLM context."""
        state = self.engine.get_state()
        lines = ["## Current Engine State\n"]

        if state.scene:
            lines.append(f"**Scene:** {state.scene}\n")

        for name, char in state.characters.items():
            status_parts = [
                f"HP {char.hp}/{char.max_hp}",
                f"Stress {char.stress}",
                f"Wounds {char.wounds}/{char.max_wounds}",
            ]
            if not char.alive:
                status_parts.append("DEAD")
            if char.conditions:
                status_parts.append(f"Conditions: {', '.join(c.value for c in char.conditions)}")
            if char.armor.ap > 0:
                status_parts.append(f"Armor: {char.armor.name} (AP {char.armor.ap})")
            if char.weapons:
                wpn_list = ", ".join(f"{w.name} ({w.damage})" for w in char.weapons)
                status_parts.append(f"Weapons: {wpn_list}")

            stats = char.stats
            saves = char.saves
            stat_str = f"STR {stats.strength} SPD {stats.speed} INT {stats.intellect} CMB {stats.combat}"
            save_str = f"SAN {saves.sanity} FEAR {saves.fear} BODY {saves.body}"
            lines.append(f"**{name}** ({char.char_class.value}): {' | '.join(status_parts)}")
            lines.append(f"  Stats: {stat_str} | Saves: {save_str}")

        if state.combat.active:
            order = ", ".join(c.name for c in state.combat.combatants)
            current = state.combat.current_combatant or "none"
            lines.append(f"\n**Combat:** Round {state.combat.round} | Order: {order} | Current: {current}")

        return "\n".join(lines)

    def _format_tool_result_message(self, tool_name: str, tool_result: dict) -> str:
        """Human-readable summary of a tool result for posting as a roll message."""
        if tool_name == "roll_check":
            skill_info = f" (skill)" if "skill" in tool_result else ""
            return (
                f"🎲 {tool_result.get('character', '?')} rolls {tool_result.get('stat', '?')}{skill_info}: "
                f"d100 → {tool_result.get('roll', '?')} vs {tool_result.get('target', '?')} — "
                f"**{tool_result.get('result', '?')}**"
            )
        elif tool_name == "apply_damage":
            parts = [f"💥 Damage applied: {tool_result.get('raw_damage', '?')}"]
            if tool_result.get("absorbed"):
                parts.append(f"(armor absorbed {tool_result['absorbed']})")
            if tool_result.get("wound"):
                parts.append("— WOUND!")
            if tool_result.get("dead"):
                parts.append("— DEAD!")
            return " ".join(parts)
        elif tool_name == "heal":
            return f"💚 {tool_result.get('character', '?')} healed {tool_result.get('healed', '?')} HP"
        elif tool_name == "add_stress":
            return f"😰 {tool_result.get('character', '?')} stress now at {tool_result.get('stress', '?')}"
        elif tool_name == "panic_check":
            if tool_result.get("panicked"):
                return (
                    f"😱 PANIC! Rolled {tool_result.get('roll', '?')} vs stress "
                    f"{tool_result.get('stress', '?')} — {tool_result.get('effect', '?')}"
                )
            return (
                f"😤 Panic check: rolled {tool_result.get('roll', '?')} vs stress "
                f"{tool_result.get('stress', '?')} — holds steady"
            )
        elif tool_name == "start_combat":
            order = ", ".join(tool_result.get("turn_order", []))
            return f"⚔️ Combat started! Initiative order: {order}"
        elif tool_name == "combat_action":
            actor = tool_result.get("actor", "?")
            action = tool_result.get("action", "?")
            parts = [f"⚔️ {actor}: {action}"]
            if tool_result.get("target"):
                parts.append(f"→ {tool_result['target']}")
            if "roll" in tool_result:
                parts.append(f"(rolled {tool_result['roll']}, {tool_result.get('check_result', '?')})")
            if tool_result.get("damage"):
                parts.append(f"dealing {tool_result['damage']} damage")
            if tool_result.get("fled") is True:
                parts.append("— escaped!")
            elif tool_result.get("fled") is False:
                parts.append("— blocked!")
            return " ".join(parts)
        elif tool_name == "end_combat":
            return "⚔️ Combat ended."
        elif tool_name == "set_scene":
            return f"📍 Scene: {tool_result.get('scene', '?')}"
        else:
            return f"[{tool_name}] {json.dumps(tool_result)}"

    def generate_with_tools(self, instruction: str) -> tuple[str, list[dict]]:
        """Tool use loop: call LLM with tools, execute tool calls, repeat until text response.

        Returns (narration_text, list_of_tool_results) where each tool result is
        {"tool": name, "result": result_dict}.
        """
        all_messages = self.sync_messages()
        transcript = self.format_transcript(all_messages)
        engine_state = self._format_engine_state()

        user_content = ""
        if transcript:
            user_content += f"## Game transcript so far\n\n{transcript}\n\n---\n\n"
        user_content += f"{engine_state}\n\n---\n\n"
        if self._server_instructions:
            user_content += f"## Response instructions\n\n{self._server_instructions}\n\n---\n\n"
        user_content += f"## Your instruction\n\n{instruction}"

        messages = [{"role": "user", "content": user_content}]
        tool_results: list[dict] = []

        for _ in range(10):  # safety guard
            response = self.llm.messages.create(
                model=MODEL,
                max_tokens=ENGINE_DM_MAX_TOKENS,
                system=self.system_prompt,
                messages=messages,
                tools=ENGINE_TOOL_DEFINITIONS,
            )

            # Check if the response contains only text (done)
            if response.stop_reason == "end_turn":
                # Extract text from content blocks
                text_parts = [b.text for b in response.content if b.type == "text"]
                return "\n".join(text_parts), tool_results

            # Process tool use blocks
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            tool_use_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    result = self._execute_tool(block.name, block.input)
                    tool_results.append({"tool": block.name, "result": result})
                    tool_use_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            if tool_use_results:
                messages.append({"role": "user", "content": tool_use_results})  # type: ignore[arg-type]
            else:
                # No tool use and not end_turn — extract text and return
                text_parts = [b.text for b in assistant_content if b.type == "text"]
                return "\n".join(text_parts) if text_parts else "", tool_results

        # Safety: max iterations reached, return whatever text we have
        return "[The Warden pauses, gathering thoughts...]", tool_results

    # Tools that modify character state and should trigger a sheet update
    _STATE_CHANGING_TOOLS = {"apply_damage", "heal", "add_stress", "panic_check", "combat_action"}

    def _format_sheet_content(self, character_name: str) -> str | None:
        """Format a character sheet entry from current engine state."""
        state = self.engine.get_state()
        char = state.characters.get(character_name)
        if not char:
            return None
        weapons = ", ".join(f"{w.name} ({w.damage})" for w in char.weapons) if char.weapons else "None"
        armor = f"{char.armor.name} (AP {char.armor.ap})" if char.armor else "None"
        inventory = ", ".join(char.inventory) if char.inventory else "None"
        conditions = ", ".join(c.value for c in char.conditions) if char.conditions else "None"
        stats = char.stats
        saves = char.saves
        return (
            f"**{character_name}** — {char.char_class.value.title()}\n\n"
            f"HP: {char.hp}/{char.max_hp} | Stress: {char.stress} | "
            f"Wounds: {char.wounds}/{char.max_wounds}\n"
            f"Combat: {stats.combat} | Intellect: {stats.intellect} | "
            f"Strength: {stats.strength} | Speed: {stats.speed}\n"
            f"Sanity: {saves.sanity} | Fear: {saves.fear} | Body: {saves.body}\n"
            f"Weapons: {weapons}\n"
            f"Armor: {armor}\n"
            f"Inventory: {inventory}\n"
            f"Conditions: {conditions}"
        )

    def post_character_sheet(self, character_name: str) -> None:
        """Post a sheet message with the character's current stats."""
        content = self._format_sheet_content(character_name)
        if content:
            body: dict = {
                "type": "sheet",
                "content": content,
                "metadata": {"key": "stats", "character": character_name},
            }
            resp = self.http.post(
                f"/games/{self.game_id}/messages",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
            posted = resp.json()
            self._message_cache.append(posted)
            self._last_msg_id = posted["id"]

    def narrate(self, instruction: str) -> dict:
        """Generate narration with engine tools, post roll messages, whispers, then narration."""
        raw, tool_results = self.generate_with_tools(instruction)

        # Post each tool result as a "roll" message, and update sheets for state changes
        affected_characters: set[str] = set()
        for tr in tool_results:
            if "error" not in tr["result"]:
                msg_text = self._format_tool_result_message(tr["tool"], tr["result"])
                self.post_message(msg_text, "roll")
                # Track characters affected by state-changing tools
                if tr["tool"] in self._STATE_CHANGING_TOOLS:
                    char_name = tr["result"].get("character") or tr["result"].get("actor")
                    if char_name:
                        affected_characters.add(char_name)

        # Post updated sheets for any characters whose state changed
        for char_name in affected_characters:
            self.post_character_sheet(char_name)

        parsed = self._parse_dm_response(raw)

        # Post whispers before public narration
        self._post_whispers(parsed["whispers"])

        result = self.post_message(parsed["narration"], "narrative")
        result["_respond"] = parsed["respond"]
        return result
