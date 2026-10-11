"use strict";
const byId=id=>document.getElementById(id);
let roleInfo=null;
let nextCursor=null;
let requestId=crypto.randomUUID();
const labels={Tenant:"Hyresgäst",PropertyManager:"Förvaltare",Finance:"Ekonomi"};
async function api(path,options={}){
 const response=await fetch(path,{credentials:"same-origin",...options});
 if(response.status===401){throw new Error("Din inloggning har gått ut. Logga in igen.");}
 const value=await response.json();
 if(!response.ok)throw new Error(value.error||"Anropet kunde inte genomföras.");
 return value;
}
function text(tag,value,parent){const e=document.createElement(tag);e.textContent=value;parent.append(e);return e;}
async function refresh(cursor=null){
 byId("listStatus").textContent="Hämtar ärenden...";
 try{
 const data=await api("/api/tickets"+(cursor?"?cursor="+encodeURIComponent(cursor):""));nextCursor=data.nextCursor;byId("nextPage").hidden=!nextCursor;byId("tickets").replaceChildren();
 for(const record of data.items){
  const box=document.createElement("article");box.className="ticket";
  text("h3",record.title,box);text("p",`${record.propertyId} · ${record.category} · ${record.status}`,box);
  text("p",record.description,box);text("p",`Ärendenummer: ${record.id}`,box);
  text("p",record.automationComplete?"Automationen är bekräftad.":"Notisen väntar på bekräftelse.",box);
  const pic=document.createElement("img");pic.src=`/api/tickets/${encodeURIComponent(record.id)}/image`;pic.alt="Bild som hör till felanmälan";pic.loading="lazy";box.append(pic);
  if(roleInfo.roles.includes("PropertyManager")&&roleInfo.properties.includes(record.propertyId)){
   const select=document.createElement("select");select.setAttribute("aria-label","Ändra ärendets status");
   for(const value of ["Ny","Pågår","Avslutad"]){const option=document.createElement("option");option.value=value;option.textContent=value;select.append(option);}select.value=record.status;
   const save=text("button","Spara status",box);box.append(select);
   save.onclick=async()=>{save.disabled=true;try{await api(`/api/tickets/${record.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:select.value})});await refresh();}catch(error){byId("listStatus").textContent=error.message;save.disabled=false;}};
  }
  byId("tickets").append(box);
 }
 byId("listStatus").textContent=data.items.length?`${data.items.length} ärenden visas.`:"Inga ärenden att visa.";
 }catch(error){byId("listStatus").textContent=error.message;}
}
byId("refresh").onclick=()=>refresh();
byId("nextPage").onclick=()=>refresh(nextCursor);
byId("ticketForm").onsubmit=async event=>{
 event.preventDefault();byId("submit").disabled=true;byId("result").textContent="Sparar felanmälan...";
 try{
  const file=byId("image").files[0];if(!file||file.size>5*1024*1024)throw new Error("Välj en bild på högst 5 MB.");
  const bytes=new Uint8Array(await file.arrayBuffer());let binary="";for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  const value=await api("/api/tickets",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({requestId,title:byId("title").value,description:byId("description").value,propertyId:byId("property").value,category:byId("category").value,image:btoa(binary)})});
  byId("result").textContent=`Felanmälan är sparad. Ärendenummer: ${value.id}. Notisen behandlas automatiskt.`;requestId=crypto.randomUUID();byId("ticketForm").reset();await refresh();
 }catch(error){byId("result").textContent=error.message+" Om du försöker igen används samma ärendenummer.";}
 finally{byId("submit").disabled=false;}
};
(async()=>{try{roleInfo=await api("/api/me");byId("role").textContent="Din roll: "+roleInfo.roles.map(x=>labels[x]||x).join(", ");if(roleInfo.roles.includes("Tenant")){byId("create").hidden=false;for(const value of roleInfo.properties){const option=document.createElement("option");option.value=value;option.textContent=value;byId("property").append(option);}}await refresh();await refreshDocuments();if(roleInfo.roles.includes("PropertyManager")){byId("documentForm").hidden=false;for(const value of roleInfo.properties){const option=document.createElement("option");option.value=value;option.textContent=value;byId("documentProperty").append(option);}}if(roleInfo.roles.includes("Finance")){byId("costSection").hidden=false;const costs=await api("/api/costs");for(const [prop,row] of Object.entries(costs.properties)){text("p",`${prop}: ${row.reports} ärenden, ${(row.imageBytes/1048576).toFixed(2)} MB bilder, ${(row.reportShare*100).toFixed(1)} procent av ärendena.`,byId("costs"));}}}catch(error){byId("role").textContent=error.message;}})();

async function refreshDocuments(){
 try{const value=await api("/api/documents");byId("documents").replaceChildren();for(const doc of value.items){const a=text("a",`${doc.propertyId}: ${doc.name}`,byId("documents"));a.href=`/api/documents/${encodeURIComponent(doc.propertyId)}/${encodeURIComponent(doc.name)}`;a.setAttribute("download",doc.name);byId("documents").append(document.createElement("br"));}byId("documentStatus").textContent=value.items.length?"Dokument visas för dina behörigheter.":"Inga dokument att visa.";}catch(error){byId("documentStatus").textContent=error.message;}
}
byId("documentForm").onsubmit=async event=>{
 event.preventDefault();const button=byId("uploadDocument");button.disabled=true;
 try{const file=byId("documentFile").files[0];if(!file||file.size>5*1024*1024)throw new Error("Välj PDF högst 5 MB.");let binary="";const bytes=new Uint8Array(await file.arrayBuffer());for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));await api("/api/documents",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({propertyId:byId("documentProperty").value,name:file.name,content:btoa(binary)})});await refreshDocuments();byId("documentStatus").textContent="Dokumentet är sparat i privat lagring.";}catch(error){byId("documentStatus").textContent=error.message;}finally{button.disabled=false;}
};
