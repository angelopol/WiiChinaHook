"""Atomic local metadata. Bumble manages link keys in a separate file."""
from __future__ import annotations

import json
from pathlib import Path
from .config import normalize_address


class Registry:
    def __init__(self, directory: Path, adapter: str):
        self.path = directory / f"devices-{adapter.replace(':', '')}.json"
        self.devices = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not isinstance(self.devices, dict) or len(self.devices) > 4:
            raise ValueError(f"Invalid registry: {self.path}")
        slots = set()
        for address, entry in self.devices.items():
            normalize_address(address)
            if entry["slot"] not in range(4) or entry["slot"] in slots:
                raise ValueError(f"Invalid/duplicate registry slot: {self.path}")
            slots.add(entry["slot"])

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.devices, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def add(self, address, slot=None, pin_mode="sync"):
        address = normalize_address(address)
        if address in self.devices:
            if slot is not None and self.devices[address]["slot"] != slot:
                raise ValueError("Configured slot conflicts with saved slot; forget the device first")
            return self.devices[address]
        used = {entry["slot"] for entry in self.devices.values()}
        if slot is None:
            slot = next((s for s in range(4) if s not in used), None)
        if slot is None or slot in used or slot not in range(4):
            raise ValueError("No free slot (0..3)")
        self.devices[address] = {"slot": slot, "pin_mode": pin_mode}
        self.save()
        return self.devices[address]

    def forget(self, address):
        self.devices.pop(address, None)
        self.save()
