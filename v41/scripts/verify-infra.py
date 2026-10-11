"""Kontrollera faktisk nätverksisolering och lagringsinställningar utan att skriva ut hemligheter."""
import argparse,json,urllib.request,urllib.error
from pathlib import Path
from azure_cli import az

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--parameters",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    values=json.loads(Path(args.parameters).read_text(encoding="utf-8"))["parameters"]
    name=values["functionName"]["value"]
    storage=values["ticketStorageName"]["value"]
    checks=[]
    def check(label,actual,expected):
        passed=actual==expected
        checks.append({"name":label,"actual":actual,"expected":expected,"passed":passed})
        Path(args.output).write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding="utf-8")
        print(label+": "+("OK" if passed else "MISSLYCKADES"),flush=True)
        if not passed: raise RuntimeError(label)
    account=az("storage","account","show","-g","rg-nordvik","-n",storage)
    check("Publik lagringsanslutning avstängd",account["publicNetworkAccess"],"Disabled")
    check("Anonyma blobbar avstängda",account["allowBlobPublicAccess"],False)
    check("Lagringsnycklar avstängda",account["allowSharedKeyAccess"],False)
    function=az("resource","show","-g","rg-nordvik","-n",name,"--resource-type","Microsoft.Web/sites")
    check("Function har nätverksintegration",bool(function["properties"].get("virtualNetworkSubnetId")),True)
    scale=function["properties"]["functionAppConfig"]["scaleAndConcurrency"]
    check("Ingen alltid aktiv instans",bool(scale.get("alwaysReady")),False)
    check("Instansgräns enligt parametrarna",scale["maximumInstanceCount"],values["maximumInstances"]["value"])
    auth=az("resource","show","--ids",function["id"]+"/config/authsettingsV2","--api-version","2024-04-01")
    check("Inloggning krävs i Azure",auth["properties"]["globalValidation"]["requireAuthentication"],True)
    endpoints=az("network","private-endpoint","list","-g","rg-nordvik")
    check("Två privata anslutningar",len(endpoints),2)
    for endpoint in endpoints:
        check("Privat anslutning godkänd "+endpoint["name"],
              endpoint["privateLinkServiceConnections"][0]["privateLinkServiceConnectionState"]["status"],"Approved")
    try:
        response=urllib.request.urlopen("https://"+storage+".blob.core.windows.net/felanmalningar?restype=container&comp=list",timeout=30)
        status=response.status
        response.close()
    except urllib.error.HTTPError as error:
        status=error.code
    check("Anonym åtkomst från internet nekas",status,403)
    policy=az("storage","account","management-policy","show","-g","rg-nordvik","--account-name",storage)
    rules=policy["policy"]["rules"]
    check("Dokument kyls automatiskt efter 90 dagar",any(
        r["enabled"] and r["definition"]["filters"].get("prefixMatch")==["dokument/"] and
        r["definition"]["actions"]["baseBlob"]["tierToCool"]["daysAfterModificationGreaterThan"]==90
        for r in rules),True)
    print("Infrastrukturens kontroller är klara.")
