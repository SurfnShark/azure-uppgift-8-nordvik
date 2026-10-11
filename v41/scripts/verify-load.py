import sys,time,json,base64,urllib.parse
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor,as_completed
from threading import Barrier
import argparse
from portal_client import PortalClient
from azure_cli import az
parser=argparse.ArgumentParser()
parser.add_argument('--identities',required=True)
parser.add_argument('--parameters',required=True)
parser.add_argument('--output',required=True)
parser.add_argument('--picture',required=True)
parser.add_argument('--allow-load',action='store_true')
args=parser.parse_args()
if not args.allow_load: raise RuntimeError('Use --allow-load only in the separate Nordvik lab environment.')
client=PortalClient(args.identities,args.parameters)
call=client.call
P=Path(args.output).resolve().parent
P.mkdir(parents=True,exist_ok=True)
RESULT={'scope':'120 concurrent virtual clients, not 120 separate identities; realistic image; emails disabled for these records','reads':{},'uploads':{},'integration':{}}
OUT=Path(args.output)
def save(): OUT.write_text(json.dumps(RESULT,indent=2),encoding='utf-8')
def setting(mode):az('functionapp','config','appsettings','set','-g','rg-nordvik','-n',client.parameters['functionName']['value'],'--settings','NORDVIK_NOTIFICATION_MODE='+mode)
def warm():
 for _ in range(60):
  try:
   if call('/api/me')[0]==200:return
  except Exception:pass
  time.sleep(5)
 raise RuntimeError('Portal failed to become ready')
if __name__=='__main__':
 warm();print('Load records require explicit silent email mode.',flush=True)
 try:
  picture=base64.b64encode(Path(args.picture).read_bytes()).decode();RESULT['inputImageBytes']=len(Path(args.picture).read_bytes());ids=[];started=time.monotonic()
  def upload(i):
   actor='tenant-a' if i%2==0 else 'tenant-b';prop='F001' if i%2==0 else 'F002';body={'requestId':str(uuid4()),'propertyId':prop,'category':'ovrigt','title':'Fictional load test '+str(i),'description':'Artificial load test. No real property data.','image':picture,'labSilent':True};attempts=[]
   for retry in range(4):
    begin=time.monotonic()
    try:status,value=call('/api/tickets',actor,'POST',body)
    except Exception as error:status=0;value={'errorType':type(error).__name__}
    attempts.append({'code':status,'seconds':round(time.monotonic()-begin,3)})
    if status in [200,201]:
     verified,stored=call('/api/tickets/'+value['id'],actor)
     if verified!=200 or stored.get('notificationMode')!='test-silent':raise RuntimeError('Silent mode not confirmed. Stop the flow before continuing.')
     return {'id':value['id'],'actor':actor,'attempts':attempts,'passed':True}
    time.sleep(2**retry)
   return {'actor':actor,'attempts':attempts,'passed':False}
  probe=upload(-1)
  if not probe['passed']:raise RuntimeError('Silent preflight failed')
  RESULT['silentPreflight']=True;save()
  done=[]
  with ThreadPoolExecutor(max_workers=12) as pool:
   for future in as_completed([pool.submit(upload,i) for i in range(300)]):
    done.append(future.result());RESULT['uploads']={'requested':300,'completed':len(done),'passed':sum(x['passed'] for x in done),'seconds':round(time.monotonic()-started,2),'records':done};save()
    if len(done)%25==0:print('Uploads',len(done),'accepted',sum(x['passed'] for x in done),flush=True)
  if not all(x['passed'] for x in done):raise RuntimeError('At least one upload failed after retry')
  if time.monotonic()-started>3600:raise RuntimeError('300/hour goal missed')
  barrier=Barrier(120)
  def read(i):
   barrier.wait();begin=time.monotonic()
   try:code,value=call('/api/tickets','tenant-a' if i%2==0 else 'tenant-b');size=len(value.get('items',[])) if isinstance(value,dict) else 0
   except Exception:code=0;size=0
   return {'code':code,'seconds':round(time.monotonic()-begin,3),'items':size}
  readstart=time.monotonic()
  with ThreadPoolExecutor(max_workers=120) as pool:reads=list(pool.map(read,range(120)))
  timings=sorted(x['seconds'] for x in reads);RESULT['reads']={'clients':120,'successful':sum(x['code']==200 for x in reads),'p95Seconds':timings[int(.95*(len(timings)-1))],'maxSeconds':max(timings),'wallSeconds':round(time.monotonic()-readstart,2),'records':reads};save();print('Concurrent clients',RESULT['reads']['successful'],'of 120; p95',RESULT['reads']['p95Seconds'],flush=True)
  if any(x['code']!=200 for x in reads):raise RuntimeError('Concurrent read failed')
  paged={}
  for actor,prop in [('tenant-a','F001'),('tenant-b','F002')]:
   ids=[];cursor=None;pages=0
   while True:
    code,value=call('/api/tickets'+('?cursor='+urllib.parse.quote(cursor,safe='') if cursor else ''),actor)
    if code!=200:raise RuntimeError('Pagination failed')
    if any(x['propertyId']!=prop for x in value['items']):raise RuntimeError('Property isolation failed')
    ids += [x['id'] for x in value['items']];pages+=1;cursor=value['nextCursor']
    if not cursor:break
    if pages>100:raise RuntimeError('Cursor loop')
   if len(ids)!=len(set(ids)) or len(ids)<150:raise RuntimeError('Pagination lost or duplicated records')
   paged[actor]={'records':len(ids),'pages':pages,'unique':True,'isolated':True}
  RESULT['pagination']=paged;save();print('Pagination verified.',flush=True)
  pending={x['id']:x['actor'] for x in done};deadline=started+3600
  while pending:
   for ticket,actor in list(pending.items()):
    code,record=call('/api/tickets/'+ticket,actor)
    if code==200 and record.get('automationComplete'):del pending[ticket]
   RESULT['integration']={'completed':300-len(pending),'pending':len(pending),'seconds':round(time.monotonic()-started,2)};save();print('SharePoint completion',300-len(pending),'of 300',flush=True)
   if pending:
    if time.monotonic()>deadline:raise RuntimeError('Integration goal exceeded one hour')
    time.sleep(10)
  code,costs=call('/api/costs','finance');RESULT['costAllocation']=costs;save()
  RESULT['passed']=True;save();print('Load test complete.',flush=True)
 finally:
  RESULT['emailSettingsUnchanged']=True;save();print('Email settings were not changed.',flush=True)
