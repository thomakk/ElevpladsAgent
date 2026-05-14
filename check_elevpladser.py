"""
Elevplads-agent for Randers
Søger efter aktuelle elevpladser og sender email-opsummering.
"""

import anthropic
import smtplib
import json
import os
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def search_elevpladser(keyword: str = "elevplads Randers") -> list[dict]:
    """Kalder Claude med web search for at finde aktuelle elevpladser."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""Du er en dansk elevplads-agent. Søg grundigt efter AKTUELLE ledige elevpladser, lærepladser og praktikpladser i Randers (8900) eller Randers Kommune.

Søg på disse kilder: Jobnet.dk, Elevplads.dk, Elevportalen.dk, samt generelle jobsøgninger.
Inkluder alle typer: EUD/erhvervsuddannelse, kontor/admin, handel, SOSU, teknisk, IT og andre.

Søgeord: "{keyword}"

Returnér KUN et JSON-objekt uden markdown eller forklaring:
{{"listings": [{{"title": "stillingsbetegnelse", "company": "virksomhedsnavn", "type": "uddannelsestype fx EUD/Handel/SOSU/Kontor", "deadline": "ansøgningsfrist eller Hurtigst muligt", "start": "opstartstidspunkt eller ukendt", "url": "direkte link eller null", "source": "Jobnet/Elevplads.dk/Elevportalen/andet"}}]}}

Maks 10 opslag. Hvis ingen: {{"listings": []}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )

    # Udtræk tekst fra responsen
    json_str = ""
    for block in response.content:
        if block.type == "text":
            json_str += block.text

    # Rens og parsér JSON
    json_str = json_str.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(json_str)
        return data.get("listings", [])
    except json.JSONDecodeError:
        # Forsøg at finde JSON-objekt i teksten
        import re
        match = re.search(r"\{[\s\S]*\}", json_str)
        if match:
            try:
                data = json.loads(match.group())
                return data.get("listings", [])
            except Exception:
                pass
    return []


def load_seen_hashes(filepath: str = "seen_listings.json") -> set:
    """Indlæser tidligere sete opslag fra fil."""
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_hashes(hashes: set, filepath: str = "seen_listings.json"):
    """Gemmer sete opslag til fil."""
    with open(filepath, "w") as f:
        json.dump(list(hashes), f)


def listing_hash(listing: dict) -> str:
    """Laver et unikt fingeraftryk for et opslag."""
    key = (listing.get("title", "") + listing.get("company", "")).lower().strip()
    return hashlib.md5(key.encode()).hexdigest()


def build_email(listings: list[dict], new_count: int, keyword: str) -> tuple[str, str]:
    """Bygger emne og brødtekst til emailen."""
    now = datetime.now().strftime("%d/%m/%Y kl. %H:%M")
    subject = (
        f"Elevpladser i Randers — {datetime.now().strftime('%d/%m/%Y')} "
        f"({len(listings)} opslag, {new_count} nye)"
    )

    lines = [
        f"Hej,",
        f"",
        f"Her er de aktuelle elevpladser i Randers fundet {now}.",
        f"",
        f"Fandt {len(listings)} opslag i alt — heraf {new_count} nye siden sidst.",
        f"",
        "─" * 40,
        "",
    ]

    for i, l in enumerate(listings, 1):
        type_str = f" ({l['type']})" if l.get("type") else ""
        lines.append(f"{i}. {l.get('title', 'Ukendt stilling')}{type_str}")
        lines.append(f"   Virksomhed : {l.get('company', 'Ukendt')}")
        lines.append(f"   Frist      : {l.get('deadline', '?')}")
        lines.append(f"   Opstart    : {l.get('start', 'Ukendt')}")
        lines.append(f"   Kilde      : {l.get('source', '?')}")
        if l.get("url"):
            lines.append(f"   Link       : {l['url']}")
        lines.append("")

    lines += [
        "─" * 40,
        "",
        "Agent kørt automatisk — Elevplads-agent Randers",
        f"Søgeord: {keyword}",
    ]

    return subject, "\n".join(lines)


def send_email(subject: str, body: str):
    """Sender email via Gmail SMTP."""
    sender = os.environ["EMAIL_SENDER"]
    recipient = os.environ["EMAIL_RECIPIENT"]
    password = os.environ["EMAIL_PASSWORD"]

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"✅ Email sendt til {recipient}")


def main():
    keyword = os.environ.get("SEARCH_KEYWORD", "elevplads Randers")
    seen_file = os.environ.get("SEEN_FILE", "seen_listings.json")

    print(f"🔍 Søger efter: {keyword}")
    listings = search_elevpladser(keyword)
    print(f"   Fandt {len(listings)} opslag")

    # Find nye opslag
    seen = load_seen_hashes(seen_file)
    new_listings = [l for l in listings if listing_hash(l) not in seen]
    print(f"   Heraf {len(new_listings)} nye siden sidst")

    # Opdater gemte hashes
    for l in listings:
        seen.add(listing_hash(l))
    save_seen_hashes(seen, seen_file)

    # Send kun email hvis der er opslag (eller altid ved morgen-tjek)
    send_always = os.environ.get("SEND_ALWAYS", "false").lower() == "true"
    if listings and (new_listings or send_always):
        subject, body = build_email(listings, len(new_listings), keyword)
        send_email(subject, body)
    else:
        print("ℹ️  Ingen nye opslag — sender ikke email.")


if __name__ == "__main__":
    main()
