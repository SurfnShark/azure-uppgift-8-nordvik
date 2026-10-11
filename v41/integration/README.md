# Nordviks Microsoft 365 integration

En separat SharePointlista ska ha ett unikt ärendenummer, fastighet, kategori, status, ansvarig förvaltare och notisstatus. Hyresgäster får inte direkt tillgång till listan. Portalen kontrollerar användarens åtkomst före läsning av ärende eller bild.

Kön skickar samma ärendenummer vid omförsök. Flödet ska först hitta eller skapa listposten och sedan utföra återstående notissteg. Ett lyckat HTTP svar ska skickas först när notisstegen är klara. Enbart ett 202 svar bevisar inte att en notis skickats.

En felkedja ska kunna återupptas. Mejlleverans kan vara osäker om ett steg skickar mejlet men svaret försvinner. Då kan ett omförsök ge en dubbel notis. Det ska redovisas ärligt; unikt ärendenummer hindrar dubbla listposter men är ingen garanti för exakt en mejlleverans.

Länken till flödet är hemlig och finns endast i privat serverkonfiguration. Repot innehåller inte anslutningarnas ID eller anropslänk.

## Skapa lösningen i en annan labbmiljö

1. Skapa en lista med namnet `Nordvik Felanmälningar` och kolumnerna i `list.schema.json`. TicketId ska vara obligatoriskt och unikt, med högst 32 tecken. Behåll listan privat för behöriga förvaltare och ekonomi. Ge inte hyresgäster direkt läsåtkomst.
2. Skapa ett nytt flöde med HTTP start och använd schemat från `flow.definition.example.json`. Byt båda exempeladresserna till godkända mottagare och SharePointadressen till rätt Microsoft 365 miljö. F001 och F002 har olika mottagare i Till fältet. Lägg till fler fastigheter genom en godkänd mappning. Koppla SharePoint och Outlookanslutningarna.
3. Återskapa stegen enligt definitionen. Schemat använder längdkontroll för ID eftersom Power Automate inte stöder regexfältet `pattern` tillsammans med anslutningsstegen. Azureportalen validerar ID formatet.
4. Behåll startstegets samtidighetsbegränsning avstängd. Ett synkront Response steg går inte att kombinera med den begränsningen. Azurefunktionen låser varje ärende under bearbetningen.
5. Spara och kopiera den hemliga HTTP adressen till de privata ARM parametrarna. Låt Azure anropa den efter att lagringen och kön har skapats.
6. Kontrollera samma ärendenummer i Azure och SharePoint och bekräfta att vanliga och akuta notiser kommit fram. Ett test av listan utan bild ersätter inte hela portaltestet.

Den publika JSON filen är en arbetsflödesdefinition, inte ett färdigt importpaket. Anslutningar måste väljas i målmiljön. Ett exporterat paket kan innehålla privata anslutningsuppgifter och ska hållas utanför Git.

Status: ett separat flöde och en separat Nordviklista är skapade. Båda portalärendenas listposter och notissteg är bekräftade. Mottagaren har också bekräftat vanliga och akuta mejl.

Fältet `notify: false` används bara för påhittade belastningsprov. Azure kräver en särskild testidentitet innan ett ärende får denna inställning. Flödet skapar fortfarande listposten, men hoppar över båda mejlstegen. Vanliga ärenden skickar notiser. Förvaltarmappningen i serverns parametrar och flödets Till fält måste stämma överens.
