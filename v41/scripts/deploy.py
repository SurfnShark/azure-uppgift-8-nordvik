"""Driftsätt Nordviks separata labbmiljö. Privata parametrar ska hållas utanför Git."""
import argparse
import json
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from azure_cli import az

ROOT = Path(__file__).resolve().parents[1]
GROUP = "rg-nordvik"

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--parameters", required=True)
    p.add_argument("--validate-only", action="store_true")
    args = p.parse_args()
    parameters = json.loads(Path(args.parameters).read_text(encoding="utf-8-sig"))
    if az("group", "exists", "-n", GROUP):
        if az("group", "show", "-n", GROUP).get("tags", {}).get("lab") != "nordvik-v41":
            raise RuntimeError("Gruppen finns redan utan rätt labbtagg. Den får inte ändras.")
    az("group", "create", "-n", GROUP, "-l", parameters["parameters"]["location"]["value"],
       "--tags", "lab=nordvik-v41", "company=nordvik", "department=forvaltning", "property=shared", "environment=lab")
    az("deployment", "group", "validate", "-g", GROUP, "--template-file", str(ROOT / "infra/main.json"),
       "--parameters", "@" + str(Path(args.parameters).resolve()))
    print("ARM validerad.", flush=True)
    if args.validate_only:
        raise SystemExit(0)
    az("deployment", "group", "create", "-g", GROUP, "-n", "nordvik-v41",
       "--template-file", str(ROOT / "infra/main.json"), "--parameters", "@" + str(Path(args.parameters).resolve()))
    # Privata anslutningar skapar nätverkskort automatiskt. Märk även dem.
    for resource in az("resource", "list", "-g", GROUP):
        if resource["type"].lower() == "microsoft.network/networkinterfaces":
            az("tag", "update", "--resource-id", resource["id"], "--operation", "Merge",
               "--tags", "lab=nordvik-v41", "company=nordvik", "department=forvaltning",
               "property=shared", "environment=lab")
    print("Infrastruktur skapad. Publicerar portalen.", flush=True)
    name = parameters["parameters"]["functionName"]["value"]
    with tempfile.TemporaryDirectory() as folder:
        package = Path(folder) / "portal.zip"
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            for f in (ROOT / "app").iterdir():
                if f.is_file():
                    archive.write(f, f.name)
        az("functionapp", "deployment", "source", "config-zip", "-g", GROUP, "-n", name,
           "--src", str(package), "--build-remote", "true", "--timeout", "600")
    url = "https://" + name + ".azurewebsites.net"
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=20) as response:
                if response.status == 200:
                    print("Hälsokontroll OK. Portal: " + url + "/api/portal", flush=True)
                    break
        except Exception:
            time.sleep(10)
    else:
        raise RuntimeError("Portalen svarade inte inom tidsgränsen.")
    print("Verifiera inloggning, roller, lagring och Microsoft 365 innan uppgiften bedöms som klar.")
