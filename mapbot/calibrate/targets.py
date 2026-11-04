"""Calibration target names and instructions (no heavy imports, used by the CLI)."""

ROI_TARGETS = {
    "minimap": "Drag around the MINIMAP map area (not its title bar or buttons)",
    "hp_bar": "Drag tightly around the whole HP bar (where the red fill can be)",
    "mp_bar": "Drag tightly around the whole MP bar (where the blue fill can be)",
    "play_area": "Drag around the area monsters can appear in (leave out minimap, status bar, chat)",
}

COLOR_TARGETS = {
    # target: (ROI it is sampled in, instructions)
    "player_dot": ("minimap", "Click your YELLOW player dot on the minimap a few times"),
    "hp_fill": ("hp_bar", "Click across the HP fill (calibrate at FULL HP)"),
    "mp_fill": ("mp_bar", "Click across the MP fill (calibrate at FULL MP)"),
}

TEMPLATE_KINDS = ("monsters", "loot", "player", "alerts")

# Which detection threshold each template kind uses.
TEMPLATE_THRESHOLD_FIELD = {
    "monsters": "monster_threshold",
    "loot": "loot_threshold",
    "player": "nametag_threshold",
    "alerts": "alert_threshold",
}
