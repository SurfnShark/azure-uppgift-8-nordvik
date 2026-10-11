"""Ta bort endast Nordviks disponibla Azurelab och dess nya appregistreringar.

Befintliga användare, Novatrixresurser och Microsoft 365 ändras inte.
Detta tar bort labbdata. Spara bevisen före körning.
"""
import argparse,json
from pathlib import Path
from azure_cli import az

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--identities",required=True)
    p.add_argument("--confirm-lab-cleanup",action="store_true")
    args=p.parse_args()
    if not args.confirm_lab_cleanup:
        raise RuntimeError("Bekräfta uttryckligen att Nordviks labbdata får tas bort.")
    state=json.loads(Path(args.identities).read_text(encoding="utf-8"))
    account=az("account","show")
    if account["tenantId"]!=state["tenantId"]:
        raise RuntimeError("Fel katalog är inloggad. Ingen städning utförs.")
    group="rg-nordvik"
    if az("group","exists","-n",group):
        resource_group=az("group","show","-n",group)
        if resource_group.get("tags",{}).get("lab")!="nordvik-v41":
            raise RuntimeError("Resursgruppen saknar rätt labbtagg. Den får inte tas bort.")
        az("group","delete","-n",group,"--yes")
        print("Nordviks labbresurser är borttagna.",flush=True)
    for obj in [state["portalApp"],*({"id":a["objectId"],"appId":a["appId"]} for a in state["testApps"])]:
        found=az("ad","app","list","--filter","appId eq '"+obj["appId"]+"'")
        if not found: continue
        if len(found)!=1 or found[0]["id"]!=obj["id"] or not found[0]["displayName"].startswith("app-nordvik-"):
            raise RuntimeError("Appidentiteten matchar inte labbens registrering. Ingen borttagning utförs.")
        az("ad","app","delete","--id",obj["id"])
    print("Nordviks nya appregistreringar är borttagna. Befintliga användarkonton och Novatrix är bevarade.")
