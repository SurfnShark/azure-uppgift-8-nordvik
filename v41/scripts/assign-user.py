"""Tilldela en befintlig labbanvändare en roll i Nordviks portal.

Filen med identiteter och privata parametrar ska ligga utanför Git.
Detta ändrar inte användarens Azure roller eller andra applikationer.
"""
import argparse
import json
import tempfile
from pathlib import Path
from azure_cli import az


def graph(method, path, value=None):
    arguments = ["rest", "--method", method, "--url", "https://graph.microsoft.com/v1.0/" + path]
    if value is None:
        return az(*arguments)
    with tempfile.TemporaryDirectory() as folder:
        body = Path(folder) / "body.json"
        body.write_text(json.dumps(value), encoding="utf-8")
        return az(*arguments, "--headers", "Content-Type=application/json", "--body", "@" + str(body))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--identities", required=True)
    p.add_argument("--user-id", required=True)
    p.add_argument("--role", choices=["Tenant", "PropertyManager", "Finance"], required=True)
    p.add_argument("--property", action="append", default=[])
    args = p.parse_args()
    path = Path(args.identities)
    state = json.loads(path.read_text(encoding="utf-8"))
    principal = state["portalPrincipal"]["id"]
    role = state["roles"][args.role]
    assignments = graph("GET", "servicePrincipals/" + principal + "/appRoleAssignedTo")["value"]
    previous = [a for a in assignments if a["principalId"] == args.user_id]
    if previous and any(a["appRoleId"] != role for a in previous):
        raise RuntimeError("Användaren har redan en annan portalroll. Granska innan ändring.")
    if not previous:
        result = graph("POST", "servicePrincipals/" + principal + "/appRoleAssignedTo", {
            "principalId": args.user_id, "resourceId": principal, "appRoleId": role})
        state["userAssignments"].append({"userId": args.user_id, "assignmentId": result["id"]})
    state["assignments"][args.user_id] = {"properties": args.property}
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print("Portalrollen är tilldelad. Kopiera den uppdaterade fastighetsmappningen till de privata ARM parametrarna och driftsätt.")
