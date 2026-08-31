"""Themed word banks — the raw lexicon behind the absurd passphrase templates.

These lists are deliberately unhinged. The generator stitches an adjective onto
a creature onto a role onto a meme number and the result reads like a Discord
username that achieved sentience. Kept in one place so the vocabulary is easy to
extend without touching the generation logic.
"""

from __future__ import annotations

ADJECTIVES: tuple[str, ...] = (
    "Moist", "Forbidden", "Quantum", "Feral", "Illegal", "Rogue", "Cursed",
    "Blessed", "Radioactive", "Unhinged", "Gluten", "Nocturnal", "Sentient",
    "Bootleg", "Artisanal", "Discount", "Premium", "Haunted", "Turbo",
    "Ultra", "Mega", "Chaotic", "Suspicious", "Emotional", "Aggressive",
    "Passive", "Feisty", "Crispy", "Soggy", "Velvet", "Chrome", "Plasma",
    "Diesel", "Vintage", "Corporate", "Federal", "Municipal", "Eternal",
    "Temporary", "Reluctant", "Enthusiastic", "Menacing", "Wholesome",
    "Deranged", "Immortal", "Bankrupt", "Caffeinated", "Sleepy",
)

CREATURES: tuple[str, ...] = (
    "Hamster", "Goose", "Wizard", "Goblin", "Raccoon", "Possum", "Gecko",
    "Narwhal", "Platypus", "Walrus", "Llama", "Alpaca", "Ferret", "Otter",
    "Kraken", "Wyvern", "Basilisk", "Gremlin", "Yeti", "Sasquatch",
    "Manatee", "Axolotl", "Capybara", "Chinchilla", "Mongoose", "Meerkat",
    "Pigeon", "Seagull", "Crustacean", "Mollusk", "Tardigrade", "Salamander",
    "Cryptid", "Homunculus", "Golem", "Phoenix", "Chimera", "Hydra",
    "Beetle", "Moth", "Slug", "Newt", "Toad", "Frog", "Lobster", "Shrimp",
)

ROLES: tuple[str, ...] = (
    "Overlord", "Enthusiast", "Connoisseur", "Officer", "Supervisor",
    "Consultant", "Technician", "Specialist", "Ambassador", "Custodian",
    "Warlord", "Baron", "Duke", "Emperor", "President", "Manager",
    "Intern", "Freelancer", "Influencer", "Prophet", "Oracle", "Guru",
    "Sommelier", "Barista", "Bureaucrat", "Landlord", "Whisperer",
    "Wrangler", "Herder", "Collector", "Dealer", "Broker", "Auditor",
    "Inspector", "Curator", "Ringleader", "Mastermind", "Sidekick",
)

OBJECTS: tuple[str, ...] = (
    "Toaster", "Spatula", "Crayon", "Stapler", "Lawnmower", "Blender",
    "Umbrella", "Mattress", "Doorknob", "Thermostat", "Calculator",
    "Harmonica", "Trombone", "Kazoo", "Bagpipe", "Waffle", "Casserole",
    "Guacamole", "Baguette", "Pretzel", "Meatball", "Pickle", "Mustard",
    "Ketchup", "Parliament", "Committee", "Spreadsheet", "Printer",
    "Router", "Modem", "Firewall", "Cabinet", "Ottoman", "Chandelier",
    "Yogurt", "Custard", "Marmalade", "Linoleum", "Tupperware",
)

VERBS: tuple[str, ...] = (
    "Yeets", "Vibes", "Lurks", "Hoards", "Summons", "Devours", "Ascends",
    "Malds", "Copes", "Seethes", "Grinds", "Farms", "Bonks", "Clutches",
    "Griefs", "Spawns", "Respawns", "Despawns", "Gatekeeps", "Gaslights",
    "Manifests", "Negotiates", "Delegates", "Escalates", "Optimizes",
)

INTENSIFIERS: tuple[str, ...] = (
    "Supreme", "Deluxe", "Prime", "Max", "Pro", "Plus", "Extreme", "Classic",
    "OG", "Legacy", "Beta", "Alpha", "v2", "3000", "9000", "XL", "Lite",
)

INTERJECTIONS: tuple[str, ...] = (
    "bro", "fr", "ngl", "istg", "lmao", "sus", "vibes", "nocap", "onGod",
    "sheesh", "yikes", "oof", "bruh", "lowkey", "highkey", "deadass",
)

MEME_NUMBERS: tuple[str, ...] = ("69", "420", "1337", "9000", "42", "80085", "666", "777")

SYMBOL_TAILS: tuple[str, ...] = ("!", "!!", "!!!", "?!", "$$", "#", "*", "._.", "!@#", "™", "®")
