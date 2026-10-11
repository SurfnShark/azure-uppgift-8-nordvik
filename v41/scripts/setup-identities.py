"""Skapa portalens Entra approller och isolerade identiteter för API tester.

En befintlig användare får rollen Tenant för ett verkligt webbläsartest.
API testerna använder separata labbapplikationer, inte personers lösenord.
Resultatet och tillfälliga hemligheter sparas endast i en privat fil.
"""
import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from azure_cli import az


def graph(method, path, value=None):
    args = ["rest", "--method", method, "--url", "https://graph.microsoft.com/v1.0/" + path]
    if value is None:
        return az(*args)
    with tempfile.TemporaryDirectory() as folder:
        body = Path(folder) / "body.json"
        body.write_text(json.dumps(value), encoding="utf-8")
        return az(*args, "--headers", "Content-Type=application/json", "--body", "@" + str(body))


def secret(app):
    until = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    return graph("POST", "applications/" + app["id"] + "/addPassword", {
        "passwordCredential": {"displayName": "Nordvik tillfällig labbnyckel", "endDateTime": until}})["secretText"]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--function-name", required=True)
    args = p.parse_args()
    output = Path(args.output)
    if output.exists():
        raise RuntimeError("Identitetsfilen finns redan. Återanvänd den och skapa inte dubbletter.")
    account = az("account", "show")
    user = az("ad", "signed-in-user", "show")
    roles = {name: str(uuid4()) for name in ["Tenant", "PropertyManager", "Finance"]}
    app = graph("POST", "applications", {
        "displayName": "app-nordvik-portal", "signInAudience": "AzureADMyOrg",
        "api": {"requestedAccessTokenVersion": 2},
        "web": {"redirectUris": ["https://" + args.function_name + ".azurewebsites.net/.auth/login/aad/callback"],
                "implicitGrantSettings": {"enableIdTokenIssuance": True, "enableAccessTokenIssuance": False}},
        "appRoles": [{"allowedMemberTypes": ["User", "Application"], "description": name,
                      "displayName": name, "id": rid, "isEnabled": True, "value": name}
                     for name, rid in roles.items()]})
    state = {"tenantId": account["tenantId"], "portalApp": app,
             "roles": roles, "testApps": [], "userAssignments": []}
    # Spara också vid ett avbrott så städningen vet vilka nya objekt som skapats.
    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(state, indent=2), encoding="utf-8")
    save()
    graph("PATCH", "applications/" + app["id"], {"identifierUris": ["api://" + app["appId"]]})
    sp = graph("POST", "servicePrincipals", {"appId": app["appId"], "appRoleAssignmentRequired": True})
    state["portalPrincipal"] = sp
    state["authClientSecret"] = secret(app)
    save()
    assignment = graph("POST", "servicePrincipals/" + sp["id"] + "/appRoleAssignedTo",
                       {"principalId": user["id"], "resourceId": sp["id"], "appRoleId": roles["Tenant"]})
    state["userAssignments"].append({"userId": user["id"], "assignmentId": assignment["id"]})
    state["assignments"] = {user["id"]: {"properties": ["F001"]}}
    save()
    for name, role, properties in [
            ("tenant-a", "Tenant", ["F001"]), ("tenant-b", "Tenant", ["F002"]),
            ("manager", "PropertyManager", ["F001"]), ("manager-b", "PropertyManager", ["F002"]), ("finance", "Finance", [])]:
        test_app = graph("POST", "applications", {"displayName": "app-nordvik-test-" + name,
                         "signInAudience": "AzureADMyOrg"})
        test = {"name": name, "appId": test_app["appId"], "objectId": test_app["id"], "role": role}
        state["testApps"].append(test)
        save()
        test_sp = graph("POST", "servicePrincipals", {"appId": test_app["appId"]})
        test["principalId"] = test_sp["id"]
        test["secret"] = secret(test_app)
        graph("POST", "servicePrincipals/" + sp["id"] + "/appRoleAssignedTo",
              {"principalId": test_sp["id"], "resourceId": sp["id"], "appRoleId": roles[role]})
        state["assignments"][test_sp["id"]] = {"properties": properties, "testOnly": True}
        save()
    print("Entra approller och labbidentiteter skapade. Hemligheter finns endast i den privata filen.")
