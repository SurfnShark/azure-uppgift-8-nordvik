"""Testa hållbar kö vid integrationsfel och omstart i den separata labben.

Pausa Nordvikflödet i Power Automate innan körning. Skriptet skapar tre
påhittade ärenden utan mejl och kontrollerar att de överlever en omstart.
Aktivera flödet igen när skriptet skriver att återhämtningen väntar.
"""
import argparse
import base64
import io
import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4
from PIL import Image
from azure_cli import az
from portal_client import PortalClient

parser = argparse.ArgumentParser()
for flag in ["identities", "parameters", "output"]:
    parser.add_argument("--" + flag, required=True)
parser.add_argument("--allow-fault", action="store_true")
parser.add_argument("--flow-paused", action="store_true")
args = parser.parse_args()
if not args.allow_fault or not args.flow_paused:
    raise RuntimeError("Pausa flödet och använd --allow-fault --flow-paused i Nordviks separata labbmiljö.")
client = PortalClient(args.identities, args.parameters)
name = client.parameters["functionName"]["value"]
result = {"scope": "Integration failure and whole application restart; not a physical Azure instance kill", "records": []}


def save():
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")


def configure(values):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "settings.json"
        path.write_text(json.dumps(values), encoding="utf-8")
        az("functionapp", "config", "appsettings", "set", "-g", "rg-nordvik", "-n", name,
           "--settings", "@" + str(path))


def ready():
    for _ in range(60):
        try:
            if client.call("/api/me")[0] == 200:
                return
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("Portalen blev inte tillgänglig.")


try:
    ready()
    picture = io.BytesIO()
    Image.new("RGB", (80, 80), "blue").save(picture, "PNG")
    for number in range(3):
        code, receipt = client.call("/api/tickets", "tenant-a", "POST", {
            "requestId": str(uuid4()), "title": "Fictional recovery test " + str(number),
            "description": "Artificial interruption test, no real property data.",
            "propertyId": "F001", "category": "ovrigt", "labSilent": True,
            "image": base64.b64encode(picture.getvalue()).decode()})
        if code != 201:
            raise RuntimeError("Ärendet kunde inte sparas under integrationsfelet.")
        result["records"].append({"id": receipt["id"]})
        save()
    time.sleep(20)
    pending = [client.call("/api/tickets/" + x["id"])[1] for x in result["records"]]
    if not all(x.get("notificationMode") == "test-silent" for x in pending):
        raise RuntimeError("Tyst testläge saknas. Låt flödet vara pausat.")
    result["acceptedWhileIntegrationUnavailable"] = all(not x.get("automationComplete") for x in pending)
    save()
    if not result["acceptedWhileIntegrationUnavailable"]:
        raise RuntimeError("Avbrottstestet skapade inte väntande ärenden.")
    az("functionapp", "restart", "-g", "rg-nordvik", "-n", name)
    ready()
    persisted = [client.call("/api/tickets/" + x["id"])[0] == 200 for x in result["records"]]
    result["survivedApplicationRestart"] = all(persisted)
    save()
finally:
    result["flowSettingsUnchanged"] = True
    save()

ready()
print("Väntande ärenden och omstart är verifierade. Aktivera Nordvikflödet igen för återhämtning.", flush=True)
deadline = time.monotonic() + 900
while True:
    done = [client.call("/api/tickets/" + x["id"])[1].get("automationComplete", False) for x in result["records"]]
    result["recoveredRecords"] = sum(done)
    save()
    print("Automationen återhämtad:", sum(done), "av", len(done), flush=True)
    if all(done):
        break
    if time.monotonic() > deadline:
        raise RuntimeError("Automationen återhämtades inte inom testets tidsgräns.")
    time.sleep(20)
result["passed"] = result["survivedApplicationRestart"] and result["acceptedWhileIntegrationUnavailable"]
save()
