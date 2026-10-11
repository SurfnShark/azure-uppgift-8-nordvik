"""Verifiera portalen med Entra tokens från separata labbapplikationer.

Detta ersätter inte ett verkligt inloggningstest i webbläsaren.
Alla tokens hålls i minnet. Resultatet sparas privat utan hemligheter.
"""
import argparse
import base64
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import uuid4
from PIL import Image


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def token(state, client):
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": client["appId"], "client_secret": client["secret"],
        "scope": "api://" + state["portalApp"]["appId"] + "/.default"}).encode()
    req = urllib.request.Request("https://login.microsoftonline.com/" + state["tenantId"] + "/oauth2/v2.0/token",
                                 data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)["access_token"]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--identities", required=True)
    p.add_argument("--parameters", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--wait-integration", action="store_true")
    p.add_argument("--silent", action="store_true", help="Skip emails using explicit test identities.")
    args = p.parse_args()
    state = json.loads(Path(args.identities).read_text(encoding="utf-8-sig"))
    parameters = json.loads(Path(args.parameters).read_text(encoding="utf-8-sig"))["parameters"]
    root = "https://" + parameters["functionName"]["value"] + ".azurewebsites.net"
    tokens = {c["name"]: token(state, c) for c in state["testApps"]}
    opener = urllib.request.build_opener(NoRedirect())
    def call(path, actor=None, method="GET", value=None, headers=None):
        all_headers = {"Accept": "application/json", **(headers or {})}
        if actor:
            all_headers["Authorization"] = "Bearer " + tokens[actor]
        body = None if value is None else json.dumps(value).encode()
        if body is not None:
            all_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(root + path, data=body, method=method, headers=all_headers)
        try:
            response = opener.open(request, timeout=90)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                result = json.loads(raw)
            except ValueError:
                result = raw
            return response.status, result
    results = {"scope": "Azure API tests with application identities; browser sign-in and mailbox delivery tested separately",
               "checks": [], "tickets": {}}
    def check(name, actual, expected):
        success = actual == expected if not isinstance(expected, tuple) else actual in expected
        results["checks"].append({"name": name, "actual": actual, "expected": expected, "passed": success})
        print(name + ": " + ("OK" if success else "MISSLYCKADES"), flush=True)
        Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2),encoding="utf-8")
        if not success:
            raise RuntimeError("Testet misslyckades: " + name)

    status,_ = call("/api/me")
    check("Inloggning krävs", status, (302,401))
    fake = base64.b64encode(json.dumps({"claims": [{"typ":"roles","val":"Finance"}]}).encode()).decode()
    status,_ = call("/api/me", headers={"x-ms-client-principal": fake})
    check("Förfalskad identitetsheader nekas",status,(302,401))
    for actor in tokens:
        status,value = call("/api/me",actor)
        check("Entra approll " + actor, status,200)
    img = io.BytesIO()
    Image.new("RGB",(80,80),"#0078d4").save(img,format="PNG")
    encoded = base64.b64encode(img.getvalue()).decode()
    samples = {}
    for actor, prop, category in [("tenant-a","F001","ovrigt"),("tenant-b","F002","vatten")]:
        payload = {"requestId": str(uuid4()), "title": "Påhittat Nordvikfel",
                   "description": "Test av felanmälan med bild, inte ett verkligt fastighetsfel.",
                   "propertyId": prop, "category": category, "image": encoded, "labSilent": args.silent}
        status,receipt = call("/api/tickets",actor,"POST",payload)
        check("Felanmälan med bild " + actor,status,201)
        results["tickets"][actor] = receipt["id"]
        samples[actor] = payload
        status,replay = call("/api/tickets",actor,"POST",payload)
        check("Samma anrop återanvänds " + actor,status,200)
        check("Samma ärendenummer " + actor,replay["id"],receipt["id"])
        status,image = call("/api/tickets/"+receipt["id"]+"/image",actor)
        check("Privat bild läses genom portalen " + actor,status,200)
        check("Bilden är JPEG " + actor, isinstance(image,bytes) and image[:2] == b"\xff\xd8", True)
    a,b = results["tickets"]["tenant-a"], results["tickets"]["tenant-b"]
    for actor,path,expected in [
            ("tenant-a","/api/tickets/"+b,404),("tenant-b","/api/tickets/"+a,404),
            ("tenant-a","/api/tickets/"+b+"/image",404),
            ("manager","/api/tickets/"+a,200),("manager","/api/tickets/"+b,404),
            ("finance","/api/tickets/"+a,200),("finance","/api/tickets/"+b,200)]:
        status,_ = call(path,actor)
        check(actor + " åtkomst " + path,status,expected)
    for actor,expected in [("tenant-a",403),("finance",403),("manager",200)]:
        status,_ = call("/api/tickets/"+a,actor,"PATCH",{"status":"Pågår"})
        check("Statusändring " + actor,status,expected)
    status,value = call("/api/tickets/"+a,"tenant-a")
    check("Ändrad status återläst",value.get("status"),"Pågår")
    invalid = dict(samples["tenant-a"],requestId=str(uuid4()),propertyId="F002")
    status,_ = call("/api/tickets","tenant-a","POST",invalid)
    check("Anmälan i annans fastighet nekas",status,403)
    for actor in ["manager","finance"]:
        status,_=call("/api/tickets",actor,"POST",dict(samples["tenant-a"],requestId=str(uuid4())))
        check("Skapande nekas för " + actor,status,403)
    invalid = dict(samples["tenant-a"],description="Ändrade uppgifter")
    status,_ = call("/api/tickets","tenant-a","POST",invalid)
    check("Ändrad data med samma anropsnummer nekas",status,409)
    invalid = dict(samples["tenant-a"],requestId=str(uuid4()),image=base64.b64encode(b"not an image").decode())
    status,_ = call("/api/tickets","tenant-a","POST",invalid)
    check("Fel bildformat nekas",status,400)
    if args.wait_integration:
        deadline = time.monotonic() + 900
        for actor,ticket in results["tickets"].items():
            while True:
                status,value=call("/api/tickets/"+ticket,actor)
                if status==200 and value.get("automationComplete"):
                    check("Listpost och notissteg bekräftade "+actor,True,True)
                    break
                if time.monotonic()>deadline:
                    raise RuntimeError("Automationen är inte bekräftad. Kontrollera kö och Power Automate.")
                time.sleep(10)
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2),encoding="utf-8")
    print("API kontroller klara. Verifiera även webbläsarinloggning, SharePoint och mottagna mejl.")
