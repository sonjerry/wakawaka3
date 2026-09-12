from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
def load_config():
    with (ROOT/"config"/"pi.yaml").open("r",encoding="utf-8") as f: return yaml.safe_load(f)
