"""Class definitions, panic table, skills, and equipment tables."""

from game.models import Armor, CharacterClass, Saves, SkillLevel, Stats, Weapon


# --- Class Definitions ---

CLASS_STATS: dict[CharacterClass, Stats] = {
    # Base stats are 2d10+25 each; these are the class modifiers added on top
    CharacterClass.TEAMSTER: Stats(strength=5, speed=5, intellect=5, combat=0),
    CharacterClass.SCIENTIST: Stats(strength=0, speed=0, intellect=10, combat=0),
    CharacterClass.ANDROID: Stats(strength=5, speed=5, intellect=5, combat=5),
    CharacterClass.MARINE: Stats(strength=5, speed=0, intellect=0, combat=10),
}

CLASS_SAVES: dict[CharacterClass, Saves] = {
    CharacterClass.TEAMSTER: Saves(sanity=30, fear=35, body=30),
    CharacterClass.SCIENTIST: Saves(sanity=40, fear=25, body=25),
    CharacterClass.ANDROID: Saves(sanity=20, fear=60, body=30),
    CharacterClass.MARINE: Saves(sanity=25, fear=30, body=35),
}

CLASS_HP: dict[CharacterClass, int] = {
    CharacterClass.TEAMSTER: 20,
    CharacterClass.SCIENTIST: 15,
    CharacterClass.ANDROID: 25,
    CharacterClass.MARINE: 25,
}

CLASS_STARTING_SKILLS: dict[CharacterClass, dict[str, SkillLevel]] = {
    CharacterClass.TEAMSTER: {
        "Mechanical Repair": SkillLevel.TRAINED,
        "Zero-G": SkillLevel.TRAINED,
    },
    CharacterClass.SCIENTIST: {
        "Computers": SkillLevel.TRAINED,
        "First Aid": SkillLevel.TRAINED,
    },
    CharacterClass.ANDROID: {
        "Linguistics": SkillLevel.TRAINED,
        "Mathematics": SkillLevel.TRAINED,
    },
    CharacterClass.MARINE: {
        "Military Training": SkillLevel.TRAINED,
        "Athletics": SkillLevel.TRAINED,
    },
}

SKILL_TIER_BONUS: dict[SkillLevel, int] = {
    SkillLevel.TRAINED: 10,
    SkillLevel.EXPERT: 15,
    SkillLevel.MASTER: 20,
}

SKILLS = [
    "Archaeology",
    "Art",
    "Athletics",
    "Botany",
    "Chemistry",
    "Climbing",
    "Computers",
    "Ecology",
    "Engineering",
    "Explosives",
    "First Aid",
    "Geology",
    "Heavy Machinery",
    "Linguistics",
    "Mathematics",
    "Mechanical Repair",
    "Military Training",
    "Mycology",
    "Pathology",
    "Piloting",
    "Rimwise",
    "Theology",
    "Xenobiology",
    "Zero-G",
]


# --- Panic Table (d20 roll, paraphrased effects) ---

PANIC_TABLE: dict[int, str] = {
    1: "Adrenaline surge — gain advantage on next check.",
    2: "Nervous twitch — minor distraction, no mechanical effect.",
    3: "Shaking hands — disadvantage on fine motor tasks for 1 round.",
    4: "Tunnel vision — can only focus on one target this round.",
    5: "Short of breath — lose next action catching breath.",
    6: "Paranoia — refuse to trust allies for 1d10 minutes.",
    7: "Overwhelmed — freeze in place, skip next turn.",
    8: "Cowardice — must flee from danger source for 1 round.",
    9: "Scream — alert all nearby creatures to your position.",
    10: "Nausea — vomit, lose action this round.",
    11: "Frenzy — attack nearest creature (friend or foe) once.",
    12: "Compulsive behavior — fixate on one object, can't act otherwise.",
    13: "Catatonic — unresponsive for 1d10 rounds unless shaken.",
    14: "Hallucinations — perceive threats that aren't there for 1d10 rounds.",
    15: "Violent outburst — smash or throw nearest object.",
    16: "Phobia — develop lasting fear of current threat type.",
    17: "Dissociation — act on autopilot, -20 to all checks for scene.",
    18: "Heart attack — take 1d10 damage, gain wound if at 0 HP.",
    19: "Collapse — fall unconscious, must be revived.",
    20: "Total psychotic break — Warden determines severe consequence.",
}


# --- Equipment ---

BASIC_WEAPONS: list[Weapon] = [
    Weapon(name="Crowbar", damage="1d10", range="close"),
    Weapon(name="Combat Knife", damage="1d10", range="close"),
    Weapon(name="Revolver", damage="2d10", range="nearby", shots=6),
    Weapon(name="Pulse Rifle", damage="3d10", range="far", shots=30),
    Weapon(name="Shotgun", damage="4d10", range="close", shots=2,
           special="Damage halved at nearby range"),
    Weapon(name="Flamethrower", damage="2d10", range="close", shots=4,
           special="Continues burning: 1d10 damage per round"),
    Weapon(name="Stun Baton", damage="1d10", range="close",
           special="Target must Body save or be stunned"),
    Weapon(name="Laser Cutter", damage="1d10", range="close",
           special="Tool, not designed as weapon"),
]

BASIC_ARMOR: list[Armor] = [
    Armor(name="Standard Crew Suit", ap=1),
    Armor(name="Hazard Suit", ap=3),
    Armor(name="Combat Armor", ap=5),
    Armor(name="Power Armor", ap=7),
]

BASIC_EQUIPMENT: list[str] = [
    "Flashlight",
    "Medkit (+10 to First Aid checks)",
    "Duct Tape",
    "Portable Welder",
    "Motion Tracker",
    "Sample Kit",
    "MREs (7 days)",
    "Water Purifier",
    "Oxygen Tank (8 hours)",
    "Emergency Flare",
    "Rope (50m)",
    "Comms Unit",
    "Personal Terminal",
    "Binoculars",
    "Lock Pick Set",
    "Mag-Boots",
]
