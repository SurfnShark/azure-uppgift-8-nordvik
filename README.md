# Nordvik Azure uppgift 8

## Mål

Nordvik behöver en portal där hyresgäster loggar in och skickar felanmälningar med rubrik, beskrivning och bild. Hyresgäster får endast se egna ärenden. Förvaltare hanterar ärenden för sina fastigheter och ekonomi har läsande insyn.

## Lösning

Azure Functions med Flex Consumption tar emot korta anrop. Microsoft Entra sköter inloggning och approller. Portalen kontrollerar dessutom ägare och fastighet för varje åtkomst. En hanterad identitet når privat Blob Storage och en beständig kö via nätverket. Bilder läses genom den behörighetskontrollerade portalen, inte med publika lagringslänkar.

En separat lista i den befintliga Microsoft 365 labbmiljön används för Nordvik. Power Automate skapar listposten och skickar Outlooknotis till ansvarig förvaltare. Värme, vatten och lås ger även ett akut mejl. Detta följer kompletteringen att automationens verktyg är ett designval. Tidigare Novatrixflöden ska inte ändras.

```text
Inloggad hyresgäst -> HTTPS -> Azure Functions
                                -> privat Blob Storage: uppgifter och bild
                                -> beständig kö
                                -> Power Automate -> SharePoint -> Outlook
Inloggad förvaltare eller ekonomi -> kontroll av roll och fastighet -> portalens läsvy
```

## Virtualiseringsnivåer

En VM är en virtuell dator med ett eget operativsystem. Microsoft driver den fysiska datorn medan teamet ansvarar för operativsystemets uppdateringar och appen. En container paketerar appen och dess beroenden men delar kärnan i värdens operativsystem. Den körs på en värd eller en hanterad containerplattform. Serverless betyder att plattformen sköter värdar och skalning medan teamet skriver funktionerna. Det finns fortfarande servrar, men teamet administrerar inte deras operativsystem.

Nordvik använder serverless med Azure Functions eftersom trafiken varierar och anropen är korta. Det privata nätverket består av VNet, subnät, privata anslutningar och privat DNS. Blob Storage lagrar uppgifter och bilder medan Queue Storage innehåller ärendenummer för arbetet som återstår.

## Krav och verifiering

| Del | Genomförande och verifiering |
| --- | --- |
| Compute | Azure driftsättning, två API inlämningar med bild och verkliga portalvyer. |
| IAM | Egna ärenden, nekad åtkomst till annans ärende och nekad ekonomiskrivning verifierade via API. Förvaltaren sparade status i webben. |
| Nätverk | Publik HTTPS portal med inloggning och två godkända privata anslutningar. Inställningarna är verifierade. |
| Storage | Bilder och ärenden återlästes. Anonym internetåtkomst till lagringen gav HTTP 403. |
| IaC | Parametriserad ARM och dokumenterade identitetssteg. |
| Integration | Ärendenumren stämmer mellan portal och SharePoint. Mottagaren bekräftade vanliga och akuta mejl. |
| Robusthet | Beständig kö, återförsök och skydd mot dubbla listposter. |
| VG | Motiverat val, kostnadsmodell, optimering, säkerhet och återskapande. |

## Viktiga avgränsningar

Detta är en labbmiljö med påhittade hyresgäster och fastigheter. Verksamhetens 48 fastigheter och 5 500 hyresgäster ska ligga till grund för designen, men alla konton och fastigheter skapas inte i testet. En kort verifiering bevisar inte 99,5 procent tillgänglighet på kontorstid. Tålighet vid instansfel och skalning ska redovisas som design samt separata tester där de genomförts.

Riktvärdet 2 500 kronor per månad gäller hela portalens tänkta miljö, inte bara Function. Lagring, privat nätverk, autentisering, integration, övervakning och eventuella Microsoft 365 licenser ska räknas separat. Beräkningsresurser startas bara när de behövs. Labbresurser ska städas efter bevisinsamling.

## Status

Miljön har driftsatts och verifierats. 35 API kontroller och 12 infrastrukturkontroller har gått igenom. Både vanliga och akuta notiser har bekräftats av mottagaren. Webbinloggning med hyresgäst, förvaltare och ekonomi fungerar. Driftkontot ser endast F001 och har sparat statusen Avslutad genom portalen. Ekonomi är verifierad både via API och i webben. Rapport och bildbevis finns lokalt. Nordviks Azuregrupp och nya appregistreringar är borttagna efter testerna, och Nordvikflödet är pausat. Befintliga Novatrixresurser och användare är bevarade. Portallänken fungerar inte efter städningen; koden kan återskapa miljön. Koden och README publiceras här. Rapporten hålls separat.

## Körinstruktioner

1. Logga in med Azure CLI i rätt prenumeration och katalog. Installera Python och bibliotek som behövs för verifieringen, bland annat Pillow.
2. Skapa approller med `v41/scripts/setup-identities.py`. Godkänn portalens grundprofil och inloggningsåtkomst som administratör i målmiljön om katalogen kräver det. Spara resultatfilen utanför repot. Den innehåller tillfälliga hemligheter och får inte publiceras.
3. Tilldela befintliga förvaltar och ekonomikonton med `v41/scripts/assign-user.py`. Ange också vilka fastigheter förvaltaren får hantera.
4. Skapa en separat SharePointlista enligt `v41/integration/list.schema.json`. TicketId ska vara obligatoriskt och unikt. Koppla flödesdefinitionen till SharePoint och Outlook enligt integrationsanvisningen.
5. Kopiera `v41/parameters.example.json` till en privat fil utanför Git. Fyll i unika resursnamn, appens ID, hemligheter, fastighetsmappning och flödets hemliga URL.
6. Portalens och testapparnas hemligheter gäller bara två dagar i labben. Återskapa eller rotera dem privat om de har gått ut. I en driftmiljö behövs planerad rotation.
7. Driftsätt och kontrollera med kommandona nedan. Testerna skickar påhittade ärenden och riktiga mejl till den konfigurerade labbmottagaren.

```text
python v41/scripts/deploy.py --parameters YOUR_PRIVATE_PARAMETERS.json
python v41/scripts/verify.py --identities YOUR_PRIVATE_IDENTITIES.json \
  --parameters YOUR_PRIVATE_PARAMETERS.json --output YOUR_PRIVATE_RESULTS.json \
  --wait-integration
python v41/scripts/verify-infra.py --parameters YOUR_PRIVATE_PARAMETERS.json \
  --output YOUR_PRIVATE_INFRA_RESULTS.json
```

## Val av compute

| Alternativ | Bedömning för Nordvik |
| --- | --- |
| Virtuella maskiner | Ger kontroll över operativsystemet men kräver patchning och extra instanser för tålighet. Påslagna instanser kostar även när ingen använder portalen. |
| Containerplattform | Passar en större eller mer specialiserad app. Kan skala vid behov men innebär ytterligare containerbygge och driftinställningar. |
| Azure Functions | Valet för labben. Korta anrop och beständiga kömeddelanden passar ojämn trafik. Flex Consumption stöder nätverksintegration och kan skala ned utan alltid aktiva instanser. |

## Kostnad och optimering

Labben använder ingen alltid aktiv Functioninstans och en låg instansgräns. Gränsen gäller per skalningsgrupp och är inget hårt kostnadstak. Två privata anslutningar har tillsammans ett riktpris på cirka 0,20 kronor per timme, ungefär 146 kronor för 730 timmar, före moms och trafik. De kostar även när ingen besöker portalen.

Ett planeringsexempel för Azure är 146 kronor för privat nätverk, cirka 31 kronor för 170 GB varm lagring och en separat reserv för Functionkörning, lagringstransaktioner, DNS, trafik och övervakning. Functionkostnaden beror på verkliga GB sekunder och antal körningar. Budgetmålet 2 500 kronor kan därför inte intygas med några korta tester. Följ faktisk kostnad och sätt budgetvarningar. Varningar stoppar inte resurser.

Microsoft 365 och Power Automate licenser räknas separat. Labben använder befintliga provlicenser; fortsatt drift kräver giltiga licenser. Månadskvoter delas med andra appar i prenumerationen och ska inte räknas som garanterat gratis utrymme.

Instruktionens 70 bilder per dag med 2 till 5 MB motsvarar ungefär 51 till 128 GB per år. Det är mer än riktvärdet 5 till 10 GB per år i samma instruktion. Kapacitetsplaneringen använder därför det högre intervallet plus dokumentens 40 GB. Bilderna kodas om för att ta bort metadata, men lägre filstorlek är inget löfte om framtida lagringsvolym.

Dokument flyttas automatiskt till Cool efter 90 dagar. Inga dokument tas bort genom den regeln. Lägre lagringspris kan innebära högre läsavgifter.

En kopierbar planeringsmodell finns i `v41/cost-model.example.json`. Där fördelas budgeten mellan nätverk, lagring, körning, trafik och övervakning med kvarvarande marginal. Detta är reserver i en plan, inte bevis på att verklig drift håller budgeten.

## Städa labben

Spara rapport och bevis innan labbdata tas bort. Skriptet kontrollerar rätt katalog och labbtagg och tar endast bort `rg-nordvik` och de nya Nordvikregistreringarna som finns i den privata identitetsfilen. Befintliga användare, `rg-novatrix` och Microsoft 365 ändras inte.

```text
python v41/scripts/cleanup.py --identities YOUR_PRIVATE_IDENTITIES.json \
  --confirm-lab-cleanup
```

Stäng av Nordviks nya Microsoft 365 flöde när testerna är klara. Avsluta eventuella provlicenser enligt deras villkor om de inte längre behövs. För att återskapa en borttagen miljö används en ny privat identitetsfil och uppdaterade parametrar.

## Dokument och verifiering

Miljön har driftsatts igen med portaladressen `/api/portal`, identiteten `id-nordvik-portal` och planen `asp-nordvik-portal`. 35 API kontroller, 12 infrastrukturkontroller och 22 extra kontroller för dokument, ekonomi och sidindelning är godkända.

Slutkontrollen kompletterade taggar på de två DNS-länkarna i ARM mallen. Azure validerade den uppdaterade mallen. Den ändringen är inte driftsatt efter städningen. Exempelkonfigurationen använder nu samma gräns på 10 instanser per skalningsgrupp som belastningsprovet.

Förvaltare kan ladda upp och läsa PDF för tilldelade fastigheter. Ekonomi läser båda labbfastigheterna. Hyresgäster saknar dokumentåtkomst. Fel fastighet, ogiltig PDF och otillåtet filnamn nekas. Filgränsen är 5 MB och dokumentlistan visar högst 100 filer. Dokumentens Coolregel efter 90 dagar är konfigurerad; 90 dagars verklig förvaring och hela arkivet på 40 GB är inte provade.

F001 och F002 har olika godkända mottagare. Vanliga och akuta mejl till den andra mottagaren är bekräftade. SharePointposten är en kopia av inskickade uppgifter. Senare statusändringar görs i Azure och synkroniseras inte tillbaka i denna labbversion.

## Kapacitet och återhämtning

300 ärenden med bilder på cirka 2 MB sparades på 74.41 sekunder och fick färdiga listposter på 135.66 sekunder. Alla 120 samtidiga virtuella klientanrop lyckades; 95 procent svarade inom 3.032 sekunder. Varje sida innehåller högst 20 ärenden och är indexerad efter ägare och fastighet. Sidindelningen kontrolleras utan dubbletter eller åtkomst till fel fastighet. Testet använder två hyresgästidentiteter och är inte 120 separata inloggningar.

Tre ärenden sparades när Microsoft 365 flödet var avstängt, överlevde en omstart och slutfördes automatiskt efter återstart. Detta är ett integrationsavbrott och en omstart av hela appen, inte ett fysiskt instansfel. Målet 99,5 procent tillgänglighet över en månad är inte uppmätt i ett kort labbprov.

En beständig outbox och kö bevarar ej bekräftat arbete. Ett tidsbegränsat lås förhindrar samtidig behandling av samma ärende. Unikt TicketId förhindrar dubbla SharePointposter. Om ett mejl skickas men bekräftelsen försvinner kan nästa försök ändå ge en extra notis. Exakt en mejlleverans garanteras inte.

Belastningsprov använder `labSilent: true`, som endast är tillåtet för särskilt märkta testidentiteter. Lagrad tyst status kontrolleras för varje ärende före fortsatt test. Listposter skapas, men mejlstegen hoppas över. Vanliga användares notiser påverkas inte.

```text
python v41/scripts/verify-load.py --identities PRIVATE_IDENTITIES.json \
  --parameters PRIVATE_PARAMETERS.json --output PRIVATE_LOAD_RESULTS.json \
  --picture FICTIONAL_2MB_PICTURE.png --allow-load

# Pausa Nordvikflödet först. Återaktivera när skriptet begär återhämtning.
python v41/scripts/verify-recovery.py --identities PRIVATE_IDENTITIES.json \
  --parameters PRIVATE_PARAMETERS.json --output PRIVATE_RECOVERY_RESULTS.json \
  --allow-fault --flow-paused
```

## Kostnadsuppföljning och övervakning

Application Insights och Log Analytics samlar driftdata. Ett aktiverat metriklarm reagerar på undantag i appen. Fel från det pausade integrationsflödet har registrerats i mätvärdet. Larmets mejlleverans är inte bekräftad. Loggarnas dagliga insamling begränsas till 0,1 GB och behålls i 30 dagar.

En månadsbudget på 2 500 SEK ger varningar vid 80 och 100 procent. Varningarna stoppar inte kostnader. Taggar anger bolag, avdelning, miljö och gemensam fastighetskostnad. Ekonomivyn visar ärendenas antal och bildstorlek per fastighet. Gemensamma Azurekostnader kan fördelas efter dessa andelar. Det är en fördelningsmetod, inte separata fakturor per fastighet. Verklig månadskostnad behöver följas upp i Cost Management.

Koden versionshanteras i detta publika GitHubrepo. PDF, råa bevis och privata filer hålls utanför GitHub. Miljön kan återskapas med nya privata identiteter, uppdaterade parametrar och de godkända Microsoft 365 anslutningarna.

## Källor

- [Flex Consumption och skalning](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan)
- [Funktionspriser och fria mängder](https://learn.microsoft.com/azure/azure-functions/pricing)
- [Azure Private Link](https://azure.microsoft.com/en-us/pricing/details/private-link/)
- [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [Microsoft Entra och App Service autentisering](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad)
