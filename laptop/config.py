from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

def load_yaml(rel):
    with (ROOT / rel).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_all():
    return {
        "laptop": load_yaml("config/laptop.yaml"),
        "input": load_yaml("config/input.yaml"),
        "vehicle": load_yaml("config/vehicle.yaml"),
    }
