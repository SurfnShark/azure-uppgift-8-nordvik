"""Nordviks portal. Entra autentisering måste vara aktiverad i Azure."""
import base64
import json
import logging
import os
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from contextlib import contextmanager
from threading import Event, Thread
from uuid import UUID, NAMESPACE_URL, uuid5
import azure.functions as func
from azure.core import MatchConditions
from azure.core.exceptions import AzureError, ResourceNotFoundError, ResourceExistsError
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.storage.queue import QueueClient
from domain import AccessDenied, identity, assignment, can_read, can_manage, validate_ticket, image_bytes, STATUSES

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
MAX_BODY = 7 * 1024 * 1024 + 10000
PAGE_SIZE = 20


def reply(value, status=200):
    return func.HttpResponse(json.dumps(value, ensure_ascii=False), status_code=status,
        mimetype="application/json", headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"})


def settings():
    return json.loads(os.environ["NORDVIK_ASSIGNMENTS"])


def current_user(req):
    try:
        principal = json.loads(base64.b64decode(req.headers.get("x-ms-client-principal", ""), validate=True))
        return identity(principal, os.environ["NORDVIK_TENANT_ID"])
    except (ValueError, KeyError, AccessDenied):
        raise AccessDenied("Logga in med ett behörigt Nordvikkonto.") from None


def body(req):
    # Webbläsarens cookies får inte användas av en annan origin för skrivning.
    origin = req.headers.get("origin", "")
    expected = "https://" + os.environ["WEBSITE_HOSTNAME"]
    if origin != expected and not req.headers.get("authorization", "").lower().startswith("bearer "):
        raise AccessDenied("Skrivningen måste komma från portalen.")
    raw = req.get_body()
    if len(raw) > MAX_BODY:
        raise ValueError("Anropet är för stort.")
    if req.headers.get("content-type", "").split(";")[0].lower().strip() != "application/json":
        raise ValueError("Skicka JSON.")
    return json.loads(raw)


def credential():
    return ManagedIdentityCredential(client_id=os.environ["NORDVIK_IDENTITY_CLIENT_ID"])


def storage(cred):
    return BlobServiceClient(os.environ["NORDVIK_BLOB_URL"], credential=cred,
                             retry_total=2, connection_timeout=10, read_timeout=20)


def queue(cred):
    return QueueClient(os.environ["NORDVIK_QUEUE_URL"], "felanmalningar", credential=cred,
                       retry_total=2, connection_timeout=10, read_timeout=20)


def record_blob(client, ticket_id):
    if len(ticket_id) != 32 or any(x not in "0123456789abcdef" for x in ticket_id):
        raise ValueError("Ogiltigt ärendenummer.")
    return client.get_blob_client("felanmalningar", "tickets/"+ticket_id+"/record.json")


def load_record(client, ticket_id):
    b = record_blob(client, ticket_id)
    d = b.download_blob()
    return json.loads(d.readall()), d.properties.etag


def outbox(client, ticket_id):
    return client.get_blob_client("felanmalningar", "outbox/"+ticket_id+".json")


def index_ticket(client, record):
    """Indexen innehåller bara ärendenummer och storlek, inte kundens text."""
    for prefix in ["indexes/all/", "indexes/property/"+record["propertyId"]+"/",
                   "indexes/tenant/"+record["ownerId"]+"/"]:
        blob=client.get_blob_client("felanmalningar",prefix+record["id"])
        try:
            blob.upload_blob(b"",overwrite=False,metadata={"propertyid":record["propertyId"],
                "imagebytes":str(record.get("imageBytes",0))})
        except ResourceExistsError:
            pass


def ticket_prefixes(user):
    if "Finance" in user["roles"]:
        return ["indexes/all/"]
    prefixes=[]
    if "PropertyManager" in user["roles"]:
        prefixes += ["indexes/property/"+p+"/" for p in sorted(assignment(user,settings()))]
    if "Tenant" in user["roles"]:
        prefixes += ["indexes/tenant/"+user["oid"]+"/"]
    return prefixes


def cursor_read(raw,prefixes):
    if not raw:
        return 0,None
    if len(raw)>10000:
        raise ValueError("Ogiltig sidmarkör.")
    value=json.loads(base64.urlsafe_b64decode(raw))
    position=value["position"]
    if not isinstance(position,int) or not 0<=position<len(prefixes):
        raise ValueError("Ogiltig sida.")
    # Klienten kan inte välja ett annat index eller en annan persons fastigheter.
    if value.get("prefix")!=prefixes[position]:
        raise AccessDenied("Sidmarkören hör inte till din åtkomst.")
    return position,value.get("token")


def cursor_write(position,token,prefixes):
    return base64.urlsafe_b64encode(json.dumps({"position":position,"token":token,
        "prefix":prefixes[position]}).encode()).decode()


def enqueue(client, q, record):
    pending = outbox(client, record["id"])
    try:
        pending.upload_blob(json.dumps({"id":record["id"]}), overwrite=False)
    except ResourceExistsError:
        pass
    # Outbox bevaras tills automationen bekräftats. Timer kan skicka igen.
    q.send_message(record["id"])


@app.route(route="health", methods=["GET"])
def health(req):
    return reply({"status":"ok", "company":"Nordvik", "revision":"completion-v2"})


@app.route(route="portal", methods=["GET"])
def portal(req):
    try:
        current_user(req)
    except AccessDenied:
        return reply({"error":"Kontot saknar portalbehörighet."}, 403)
    return func.HttpResponse(Path(__file__).with_name("index.html").read_text(encoding="utf-8"),
        mimetype="text/html", headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff",
        "Content-Security-Policy":"default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'"})


@app.route(route="portal.js", methods=["GET"])
def javascript(req):
    return func.HttpResponse(Path(__file__).with_name("portal.js").read_text(encoding="utf-8"), mimetype="application/javascript")


@app.route(route="portal.css", methods=["GET"])
def css(req):
    return func.HttpResponse(Path(__file__).with_name("portal.css").read_text(encoding="utf-8"), mimetype="text/css")


@app.route(route="me", methods=["GET"])
def me(req):
    try:
        u = current_user(req)
        return reply({"roles":sorted(u["roles"]), "properties":sorted(assignment(u, settings()))})
    except AccessDenied:
        return reply({"error":"Ingen portalbehörighet."}, 403)


@app.route(route="tickets", methods=["POST"])
def create_ticket(req):
    try:
        u = current_user(req)
        data = body(req)
        record = validate_ticket(data, u, settings())
        request_id = str(UUID(data["requestId"]))
        ticket_id = uuid5(NAMESPACE_URL, "nordvik:"+u["oid"]+":"+request_id).hex
        picture = image_bytes(data.get("image"))
        digest = hashlib.sha256(picture).hexdigest()
        fingerprint = hashlib.sha256(json.dumps(record,sort_keys=True).encode()+picture).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        record.update(id=ticket_id, ownerId=u["oid"], status="Ny", createdAt=now,
                      contentHash=fingerprint,imagePath="tickets/"+ticket_id+"/"+digest+".jpg")
        with credential() as cred, storage(cred) as client, queue(cred) as q:
            b = record_blob(client, ticket_id)
            try:
                old, _ = load_record(client, ticket_id)
                if old["ownerId"] != u["oid"]:
                    raise AccessDenied("Ingen åtkomst.")
                if old.get("contentHash") != fingerprint:
                    return reply({"error":"Samma anropsnummer får inte användas för ändrade uppgifter."},409)
                index_ticket(client,old)
                return reply({"id":old["id"], "status":old["status"], "replayed":True}, 200)
            except ResourceNotFoundError:
                pass
            image_blob = client.get_blob_client("felanmalningar", record["imagePath"])
            record["imageBytes"]=len(picture)
            # Ett belastningsprov får bara stänga av mejl med en separat labbidentitet.
            # Vanliga användare kan inte välja tyst läge. En miljöändring räcker inte:
            # Azure kan under en övergång fortfarande använda äldre instanser.
            silent = data.get("labSilent", False)
            if not isinstance(silent, bool):
                raise ValueError("Ogiltigt testläge.")
            if silent and settings().get(u["oid"], {}).get("testOnly") is not True:
                raise AccessDenied("Testläget kräver en separat labbidentitet.")
            record["notificationMode"] = "test-silent" if silent else "normal"
            try:
                image_blob.upload_blob(picture, overwrite=False, content_settings=ContentSettings(content_type="image/jpeg"))
            except ResourceExistsError:
                pass
            # Skriv en beständig avsikt före ärendeposten. Timern läser bara denna
            # aktiva kö, inte alla historiska ärenden, och väntar om posten saknas.
            try:
                outbox(client,ticket_id).upload_blob(json.dumps({"id":ticket_id}),overwrite=False)
            except ResourceExistsError:
                pass
            try:
                b.upload_blob(json.dumps(record, ensure_ascii=False), overwrite=False,
                    content_settings=ContentSettings(content_type="application/json"))
            except ResourceExistsError:
                old, _ = load_record(client, ticket_id)
                if old.get("contentHash") != fingerprint:
                    return reply({"error":"Anropsnumret hör redan till andra uppgifter."},409)
                index_ticket(client,old)
                return reply({"id":old["id"], "status":old["status"], "replayed":True}, 200)
            # Enqueue kan återförsökas av timern om Azure avslutar processen här.
            try:
                index_ticket(client,record)
                enqueue(client, q, record)
            except AzureError:
                logging.warning("Köinlägg väntar på återförsök för %s", ticket_id)
        return reply({"id":ticket_id, "status":"Ny", "automation":"pending"}, 201)
    except AccessDenied:
        return reply({"error":"Du saknar behörighet för denna felanmälan."}, 403)
    except (ValueError, KeyError, TypeError):
        return reply({"error":"Kontrollera rubrik, beskrivning, fastighet, kategori och bild."}, 400)
    except AzureError:
        return reply({"error":"Lagringen kunde inte bekräftas. Försök igen med samma ärende."}, 503)


@app.route(route="tickets", methods=["GET"])
def list_tickets(req):
    try:
        u = current_user(req)
        result = []
        prefixes=ticket_prefixes(u)
        position,token=cursor_read(req.params.get("cursor"),prefixes) if prefixes else (0,None)
        next_cursor=None
        with credential() as cred, storage(cred) as client:
            container=client.get_container_client("felanmalningar")
            while position<len(prefixes) and not result:
                pages=container.list_blobs(name_starts_with=prefixes[position],results_per_page=PAGE_SIZE).by_page(continuation_token=token)
                try:
                    entries=list(next(pages))
                except StopIteration:
                    entries=[]
                for b in entries:
                    record,_=load_record(client,Path(b.name).name)
                    if can_read(u,record,settings()):
                        result.append(record)
                token=pages.continuation_token
                if token:
                    next_cursor=cursor_write(position,token,prefixes)
                elif position+1<len(prefixes):
                    position+=1;token=None
                    next_cursor=cursor_write(position,None,prefixes)
                else:
                    position=len(prefixes)
        return reply({"items":result,"nextCursor":next_cursor,"pageSize":PAGE_SIZE})
    except AccessDenied:
        return reply({"error":"Ingen portalbehörighet."}, 403)
    except AzureError:
        return reply({"error":"Ärendena kunde inte hämtas."}, 503)
    except (ValueError,KeyError,TypeError):
        return reply({"error":"Ogiltig sidmarkör."},400)


def document_name(value):
    if not isinstance(value,str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}\.pdf",value):
        raise ValueError("Använd ett PDF namn med bokstäver, siffror och understreck.")
    return value


def document_access(user,property_id):
    return "Finance" in user["roles"] or ("PropertyManager" in user["roles"] and property_id in assignment(user,settings()))


@app.route(route="documents",methods=["GET","POST"])
def documents(req):
    try:
        user=current_user(req)
        with credential() as cred,storage(cred) as client:
            if req.method=="POST":
                data=body(req);prop=data["propertyId"];name=document_name(data["name"])
                if "PropertyManager" not in user["roles"] or prop not in assignment(user,settings()):
                    raise AccessDenied("Bara ansvarig förvaltare laddar upp dokument.")
                content=base64.b64decode(data["content"],validate=True)
                if not content.startswith(b"%PDF-") or len(content)>5*1024*1024:
                    raise ValueError("Använd PDF upp till 5 MB.")
                from pypdf import PdfReader
                from pypdf.errors import PdfReadError
                import io
                try:
                    pdf=PdfReader(io.BytesIO(content))
                except PdfReadError as error:
                    raise ValueError("PDF-filen kan inte läsas") from error
                if pdf.is_encrypted or not pdf.pages or any(k in pdf.trailer["/Root"] for k in ["/OpenAction","/AA","/Names"]):
                    raise ValueError("Använd en enkel PDF utan aktivt innehåll.")
                for page_ in pdf.pages:
                    if page_.get("/Annots") or page_.get("/AA"):
                        raise ValueError("Använd en enkel PDF utan formulär eller länkar.")
                client.get_blob_client("dokument",prop+"/"+name).upload_blob(content,overwrite=True,
                    content_settings=ContentSettings(content_type="application/pdf"))
                return reply({"name":name,"propertyId":prop},201)
            prefixes=sorted(assignment(user,settings())) if "PropertyManager" in user["roles"] else []
            if "Finance" in user["roles"]:
                prefixes=sorted(json.loads(os.environ["NORDVIK_MANAGERS"]))
            items=[]
            for prop in prefixes:
                for b in client.get_container_client("dokument").list_blobs(name_starts_with=prop+"/"):
                    items.append({"name":Path(b.name).name,"propertyId":prop})
                    if len(items)>=100:
                        return reply({"items":items,"limited":True})
            return reply({"items":items,"limited":False})
    except AccessDenied:
        return reply({"error":"Ingen dokumentbehörighet."},403)
    except (ValueError,KeyError,TypeError):
        return reply({"error":"Kontrollera fastighet och PDF fil."},400)
    except AzureError:
        return reply({"error":"Dokumenten kunde inte bekräftas."},503)


@app.route(route="documents/{propertyId}/{name}",methods=["GET"])
def read_document(req):
    try:
        user=current_user(req);prop=req.route_params["propertyId"];name=document_name(req.route_params["name"])
        if not document_access(user,prop):
            return reply({"error":"Dokumentet hittades inte."},404)
        with credential() as cred,storage(cred) as client:
            raw=client.get_blob_client("dokument",prop+"/"+name).download_blob().readall()
        return func.HttpResponse(raw,mimetype="application/pdf",headers={"Cache-Control":"private, no-store",
            "Content-Disposition":"attachment; filename=\""+name+"\"","X-Content-Type-Options":"nosniff"})
    except (AccessDenied,ResourceNotFoundError):
        return reply({"error":"Dokumentet hittades inte."},404)
    except ValueError:
        return reply({"error":"Ogiltigt dokumentnamn."},400)
    except AzureError:
        return reply({"error":"Dokumentet kunde inte hämtas."},503)


@app.route(route="costs",methods=["GET"])
def costs(req):
    try:
        if "Finance" not in current_user(req)["roles"]:
            raise AccessDenied("Kostnadsunderlaget visas för ekonomi.")
        properties={}
        with credential() as cred,storage(cred) as client:
            for b in client.get_container_client("felanmalningar").list_blobs(name_starts_with="indexes/all/",include=["metadata"]):
                prop=b.metadata["propertyid"];row=properties.setdefault(prop,{"reports":0,"imageBytes":0})
                row["reports"]+=1;row["imageBytes"]+=int(b.metadata["imagebytes"])
        total=sum(x["reports"] for x in properties.values())
        for row in properties.values():
            row["reportShare"]=row["reports"]/total if total else 0
        return reply({"properties":properties,"department":"forvaltning","sharedResourceTag":"shared",
            "scope":"Uppmätt användning. Kostnaden för gemensamma resurser fördelas efter vald fördelningsnyckel, inte separat Azurefakturering."})
    except AccessDenied:
        return reply({"error":"Endast ekonomi får läsa kostnadsunderlaget."},403)
    except AzureError:
        return reply({"error":"Kostnadsunderlaget kunde inte hämtas."},503)


@app.route(route="tickets/{id}", methods=["GET", "PATCH"])
def ticket(req):
    try:
        u = current_user(req)
        with credential() as cred, storage(cred) as client:
            record, etag = load_record(client, req.route_params["id"])
            if not can_read(u,record,settings()):
                return reply({"error":"Ärendet hittades inte."},404)
            if req.method == "PATCH":
                if not can_manage(u,record,settings()):
                    raise AccessDenied("Ingen skrivbehörighet.")
                data = body(req)
                if data.get("status") not in STATUSES:
                    raise ValueError("Ogiltig status.")
                record.update(status=data["status"],updatedAt=datetime.now(timezone.utc).isoformat())
                record_blob(client,record["id"]).upload_blob(json.dumps(record,ensure_ascii=False),overwrite=True,
                    etag=etag,match_condition=MatchConditions.IfNotModified,
                    content_settings=ContentSettings(content_type="application/json"))
            return reply(record)
    except ResourceNotFoundError:
        return reply({"error":"Ärendet hittades inte."},404)
    except AccessDenied:
        return reply({"error":"Ingen behörighet att ändra ärendet."},403)
    except (ValueError,TypeError):
        return reply({"error":"Kontrollera ärendenummer och status."},400)
    except AzureError:
        return reply({"error":"Ärendet ändrades eller lagringen svarar inte. Läs om innan nytt försök."},409)


@app.route(route="tickets/{id}/image", methods=["GET"])
def picture(req):
    try:
        u = current_user(req)
        with credential() as cred, storage(cred) as client:
            record,_ = load_record(client,req.route_params["id"])
            if not can_read(u,record,settings()):
                return reply({"error":"Bilden hittades inte."},404)
            data = client.get_blob_client("felanmalningar",record["imagePath"]).download_blob().readall()
        return func.HttpResponse(data,mimetype="image/jpeg",headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})
    except (ResourceNotFoundError,AccessDenied):
        return reply({"error":"Bilden hittades inte."},404)
    except ValueError:
        return reply({"error":"Ogiltigt ärendenummer."},400)
    except AzureError:
        return reply({"error":"Bilden kunde inte hämtas."},503)


@app.queue_trigger(arg_name="message",queue_name="felanmalningar",connection="NordvikQueue")
def dispatch(message: func.QueueMessage):
    ticket_id = message.get_body().decode("utf-8")
    url = os.environ["NORDVIK_FLOW_URL"]
    host = urlsplit(url)
    if host.scheme != "https" or not host.hostname or not host.hostname.endswith(".environment.api.powerplatform.com"):
        raise RuntimeError("Automationens serveradress är ogiltig.")
    with credential() as cred, storage(cred) as client:
        # Ett tidsbegränsat lås hindrar dubbla kömeddelanden från att behandlas samtidigt.
        pending = outbox(client,ticket_id)
        record,_ = load_record(client,ticket_id)
        if record.get("automationComplete"):
            return
        with ticket_lock(pending) as lease:
            dispatch_locked(client,ticket_id,pending,lease,url)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def ticket_lock(blob):
    lease = blob.acquire_lease(lease_duration=60)
    stop = Event()
    failed = Event()
    def renew():
        while not stop.wait(20):
            try:
                lease.renew()
            except AzureError:
                failed.set()
                return
    worker = Thread(target=renew,daemon=True)
    worker.start()
    try:
        yield lease
        if failed.is_set():
            raise RuntimeError("Ärendets lås kunde inte förnyas. Bekräftelsen måste kontrolleras.")
    finally:
        stop.set()
        worker.join(timeout=5)
        try:
            lease.release()
        except AzureError:
            pass


def dispatch_locked(client,ticket_id,pending,lease,url):
    record, _ = load_record(client,ticket_id)
    if record.get("automationComplete"):
        return
    payload = {k:record[k] for k in ("id","title","description","propertyId","category","urgent")}
    payload["imagePath"] = record["imagePath"]
    payload["notify"]=record.get("notificationMode")!="test-silent"
    # Detaljer och bildlänk är privata. Servern avgör förvaltare per fastighet.
    payload["managerEmail"] = json.loads(os.environ["NORDVIK_MANAGERS"])[record["propertyId"]]
    request = Request(url,data=json.dumps(payload).encode("utf-8"),headers={"Content-Type":"application/json"},method="POST")
    try:
        with build_opener(NoRedirect()).open(request,timeout=90) as response:
            confirmation = json.loads(response.read())
            if response.status != 200 or confirmation.get("id") != ticket_id or not confirmation.get("completed"):
                raise RuntimeError("Automation saknar slutlig bekräftelse.")
    except Exception:
        # Undvik att skriva den hemliga URL:en i loggar.
        raise RuntimeError("Automation kunde inte bekräftas; kömeddelandet återförsöks.") from None
    # Hämta om posten efter extern anropstid så förvaltarens status inte skrivs över.
    record, etag = load_record(client,ticket_id)
    record["automationComplete"] = True
    record_blob(client,ticket_id).upload_blob(json.dumps(record,ensure_ascii=False),overwrite=True,
        etag=etag,match_condition=MatchConditions.IfNotModified)
    try:
        pending.delete_blob(lease=lease)
    except ResourceNotFoundError:
        pass

@app.timer_trigger(arg_name="timer",schedule="0 */5 * * * *",run_on_startup=False,use_monitor=True)
def retry_outbox(timer: func.TimerRequest):
    # Records utan slutlig automationsbekräftelse läggs tillbaka i kön.
    with credential() as cred, storage(cred) as client, queue(cred) as q:
        count = 0
        for b in client.get_container_client("felanmalningar").list_blobs(name_starts_with="outbox/"):
            ticket_id=Path(b.name).stem
            try:
                record,_=load_record(client,ticket_id)
            except ResourceNotFoundError:
                continue
            if record.get("automationComplete"):
                try:
                    outbox(client,ticket_id).delete_blob()
                except AzureError:
                    pass
                continue
            if not record.get("automationComplete"):
                index_ticket(client,record)
                enqueue(client,q,record)
                count += 1
                if count >= 100:
                    break
