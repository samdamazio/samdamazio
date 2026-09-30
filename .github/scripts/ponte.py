#!/usr/bin/env python3
"""Ponte de comando — gera os painéis SVG do perfil (sonar, casa de máquinas,
diário de bordo e sinais). Só usa a biblioteca padrão.

Uso: GH_TOKEN=... python .github/scripts/ponte.py [--user samdamazio] [--out assets]
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import urllib.request
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
W = 840
FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"

THEMES = {
    "dark": dict(bg="#07111f", panel="#0b1a2e", grid="#15304c", line="#1f4a73", text="#d6e6f5",
                 muted="#6f8cab", accent="#35e0a1", warn="#ffb347", danger="#ff5d5d", brass="#d4a857",
                 sea="#1b6fb3"),
    "light": dict(bg="#f5f9fc", panel="#ffffff", grid="#dbe7f1", line="#b7cde0", text="#0b2239",
                  muted="#5a7591", accent="#0a8f64", warn="#c77700", danger="#c62828", brass="#9a7424",
                  sea="#2b7bc0"),
}

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name isPrivate stargazerCount pushedAt
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


# ───────────────────────────── dados ─────────────────────────────

def fetch(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": "ponte-de-comando"})
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL: {payload['errors']}")
    return payload["data"]["user"]


def summarize(u, login):
    now = dt.datetime.now(TZ)
    today = now.date()
    repos = u["repositories"]["nodes"]
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [(dt.date.fromisoformat(d["date"]), d["contributionCount"])
            for w in cal["weeks"] for d in w["contributionDays"]]
    days = [d for d in days if d[0] <= today]

    longest = run = 0
    for _, c in days:
        run = run + 1 if c else 0
        longest = max(longest, run)
    current = 0
    tail = days[:-1] if days and days[-1][1] == 0 else days  # hoje ainda não conta como quebra
    for _, c in reversed(tail):
        if not c:
            break
        current += 1

    weeks = [(dt.date.fromisoformat(w["contributionDays"][0]["date"]),
              sum(d["contributionCount"] for d in w["contributionDays"])) for w in cal["weeks"]]

    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            size, color = langs.get(n, (0, e["node"]["color"]))
            langs[n] = (size + e["size"], color or "#8b949e")
    total_bytes = sum(s for s, _ in langs.values()) or 1
    top_langs = sorted(((n, s / total_bytes * 100, c) for n, (s, c) in langs.items()),
                       key=lambda x: -x[1])[:6]

    public = [r for r in repos if not r["isPrivate"] and r["name"].lower() != login.lower()]  # nomes privados nunca vão pro SVG
    contacts = []
    for r in public[:7]:
        pushed = dt.datetime.fromisoformat(r["pushedAt"].replace("Z", "+00:00")).astimezone(TZ)
        contacts.append(dict(name=r["name"], stars=r["stargazerCount"], age=(now - pushed).days))

    busiest = max(days, key=lambda d: d[1]) if days else (today, 0)
    return dict(
        now=now,
        total=cal["totalContributions"],
        current=current,
        longest=longest,
        busiest=busiest,
        active_days=sum(1 for _, c in days if c),
        repos=u["repositories"]["totalCount"],
        stars=sum(r["stargazerCount"] for r in repos),
        followers=u["followers"]["totalCount"],
        since=u["createdAt"][:4],
        sea_days=(today - dt.datetime.fromisoformat(u["createdAt"].replace("Z", "+00:00")).date()).days,
        weeks=weeks,
        langs=top_langs,
        contacts=contacts,
    )


# ─────────────────────────── utilidades ───────────────────────────

def fmt(n):
    return f"{n:,}".replace(",", ".")


def polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def arc(cx, cy, r, a0, a1):
    x0, y0 = polar(cx, cy, r, a0)
    x1, y1 = polar(cx, cy, r, a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return f"M{x0:.2f},{y0:.2f} A{r},{r} 0 {large} 1 {x1:.2f},{y1:.2f}"


def frame(h, t, body, css=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" font-family="{FONT}">
<style>
  text{{fill:{t['text']}}}
  .muted{{fill:{t['muted']}}} .brass{{fill:{t['brass']}}} .accent{{fill:{t['accent']}}}
  .cap{{font-size:10px;letter-spacing:2px}}
  .rise{{opacity:0;animation:rise .7s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes rise{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
  @media (prefers-reduced-motion:reduce){{*{{animation:none!important}}.rise{{opacity:1}}}}
  {css}
</style>
<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="14" fill="{t['bg']}" stroke="{t['line']}"/>
{body}
</svg>
"""


def header(t, icon, title, right):
    return (f'<text x="24" y="34" class="cap brass">{icon} {escape(title)}</text>'
            f'<text x="{W - 24}" y="34" class="cap muted" text-anchor="end">{escape(right)}</text>'
            f'<line x1="24" y1="46" x2="{W - 24}" y2="46" stroke="{t["grid"]}"/>')


# ───────────────────────────── sonar ─────────────────────────────

def sonar(s, t):
    h, cx, cy, R, period = 350, 185, 198, 132, 6.0
    out = [header(t, "◉", "SONAR · CONTATOS NO RADAR", "22°54′S 043°10′W · RIO DE JANEIRO")]

    out.append(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="{t["panel"]}" stroke="{t["line"]}"/>')
    for k in (0.25, 0.5, 0.75):
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{R * k:.1f}" fill="none" stroke="{t["grid"]}" stroke-dasharray="2 4"/>')
    for deg in range(0, 360, 10):
        x0, y0 = polar(cx, cy, R - (9 if deg % 30 == 0 else 4), deg)
        x1, y1 = polar(cx, cy, R, deg)
        out.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{t["line"]}"/>')
    out.append(f'<path d="M{cx - R},{cy}H{cx + R}M{cx},{cy - R}V{cy + R}" stroke="{t["grid"]}"/>')
    for label, deg in (("000", -90), ("090", 0), ("180", 90), ("270", 180)):
        x, y = polar(cx, cy, R + 13, deg)
        out.append(f'<text x="{x:.1f}" y="{y + 3:.1f}" font-size="9" class="muted" text-anchor="middle">{label}</text>')

    # varredura: fatias com opacidade crescente até a borda de ataque
    wedge = []
    for i in range(18):
        a0, a1 = -54 + i * 3, -54 + (i + 1) * 3
        x0, y0 = polar(cx, cy, R, a0)
        x1, y1 = polar(cx, cy, R, a1)
        wedge.append(f'<path d="M{cx},{cy}L{x0:.2f},{y0:.2f}A{R},{R} 0 0 1 {x1:.2f},{y1:.2f}Z" '
                     f'fill="{t["accent"]}" fill-opacity="{0.012 + i * 0.017:.3f}"/>')
    out.append(f'<g>{"".join(wedge)}<line x1="{cx}" y1="{cy}" x2="{cx + R}" y2="{cy}" stroke="{t["accent"]}" stroke-width="1.6"/>'
               f'<animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" '
               f'dur="{period}s" repeatCount="indefinite"/></g>')

    # contatos = repositórios públicos; mais perto do centro = navegado há menos tempo
    n = len(s["contacts"])
    seed = int(hashlib.md5("".join(c["name"] for c in s["contacts"]).encode()).hexdigest(), 16)
    for i, c in enumerate(s["contacts"]):
        jitter = (int(hashlib.md5(c["name"].encode()).hexdigest(), 16) % 24) - 12
        ang = (seed % 360 + i * 360 / max(n, 1) + jitter) % 360
        rr = R * min(0.92, 0.2 + 0.72 * math.log1p(c["age"]) / math.log1p(900))
        x, y = polar(cx, cy, rr, ang)
        hit = ang / 360 * period
        size = 3 + min(c["stars"], 4)
        out.append(
            f'<g><circle cx="{x:.1f}" cy="{y:.1f}" r="{size}" fill="none" stroke="{t["accent"]}" opacity="0">'
            f'<animate attributeName="r" values="{size};{size + 14};{size + 14}" keyTimes="0;.3;1" dur="{period}s" begin="{hit:.2f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values=".9;0;0" keyTimes="0;.3;1" dur="{period}s" begin="{hit:.2f}s" repeatCount="indefinite"/></circle>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size}" fill="{t["accent"]}" opacity=".25">'
            f'<animate attributeName="opacity" values="1;.25;.25" keyTimes="0;.75;1" dur="{period}s" begin="{hit:.2f}s" repeatCount="indefinite"/></circle></g>')
        name = c["name"] if len(c["name"]) <= 16 else c["name"][:15] + "…"
        right = math.cos(math.radians(ang)) >= 0
        if not right and x - size - 5 - len(name) * 5.9 < 12:
            right = True
        lx = x + (size + 5) * (1 if right else -1)
        out.append(f'<text x="{lx:.1f}" y="{y + 3:.1f}" font-size="9.5" class="muted" '
                   f'text-anchor="{"start" if right else "end"}">{escape(name)}</text>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="3" fill="{t["accent"]}"/>')

    # painel de navegação
    px, py = 372, 76
    out.append(f'<text x="{px}" y="{py}" class="cap muted">PAINEL DE NAVEGAÇÃO</text>')
    bd, bc = s["busiest"]
    tiles = [
        ("CONTRIBUIÇÕES", fmt(s["total"]), "últimos 12 meses", t["accent"]),
        ("SEQUÊNCIA ATUAL", f'{s["current"]}d', "dias seguidos", t["warn"]),
        ("MAIOR SEQUÊNCIA", f'{s["longest"]}d', "no último ano", t["text"]),
        ("RECORDE NUM DIA", fmt(bc), bd.strftime("%d/%m/%Y"), t["text"]),
        ("REPOSITÓRIOS", fmt(s["repos"]), "próprios, sem forks", t["text"]),
        ("DIAS ATIVOS", fmt(s["active_days"]), "de 365", t["text"]),
        ("SEGUIDORES", fmt(s["followers"]), f'{fmt(s["stars"])} estrelas', t["text"]),
        ("DIAS DE MAR", fmt(s["sea_days"]), f'a bordo desde {s["since"]}', t["brass"]),
    ]
    tw, th, gap = 106, 92, 8
    for i, (label, value, sub, color) in enumerate(tiles):
        x = px + (i % 4) * (tw + gap)
        y = py + 14 + (i // 4) * (th + gap)
        out.append(
            f'<g class="rise" style="animation-delay:{0.15 + i * 0.09:.2f}s">'
            f'<rect x="{x}" y="{y}" width="{tw}" height="{th}" rx="8" fill="{t["panel"]}" stroke="{t["grid"]}"/>'
            f'<text x="{x + 10}" y="{y + 22}" font-size="8" letter-spacing=".4" class="muted">{label}</text>'
            f'<text x="{x + 10}" y="{y + 58}" font-size="26" font-weight="700" style="fill:{color}">{value}</text>'
            f'<text x="{x + 10}" y="{y + 78}" font-size="9" class="muted">{escape(sub)}</text></g>')

    last = s["contacts"][0] if s["contacts"] else None
    status = (f'▸ ÚLTIMO CONTATO: {last["name"]} · há {last["age"]}d' if last else "▸ SEM CONTATOS")
    out.append(f'<text x="{px}" y="{h - 28}" font-size="10" class="accent">{escape(status)}'
               f'<animate attributeName="opacity" values="1;.35;1" dur="2.4s" repeatCount="indefinite"/></text>')
    out.append(f'<text x="{W - 24}" y="{h - 28}" font-size="9" class="muted" text-anchor="end">'
               f'atualizado {s["now"].strftime("%d/%m/%Y %H:%M")} BRT</text>')
    return frame(h, t, "\n".join(out))


# ──────────────────────── casa de máquinas ────────────────────────

def maquinas(s, t):
    h = 262
    out = [header(t, "⚙", "CASA DE MÁQUINAS · LINGUAGENS POR VOLUME DE CÓDIGO",
                  "OFICIAL MAQUINISTA · ESCOLA NAVAL 2022")]
    langs = s["langs"]
    top = langs[0][1] if langs else 100
    ceiling = min(100, max(10, math.ceil(top / 10) * 10))
    n = max(len(langs), 1)
    cw = (W - 48) / n
    a0, sweep, r = 135, 270, 50
    for i, (name, pct, color) in enumerate(langs):
        cx, cy = 24 + cw * i + cw / 2, 122
        g = [f'<circle cx="{cx:.1f}" cy="{cy}" r="{r + 10}" fill="{t["panel"]}" stroke="{t["line"]}" stroke-width="2"/>',
             f'<circle cx="{cx:.1f}" cy="{cy}" r="{r + 5}" fill="none" stroke="{t["grid"]}"/>',
             f'<path d="{arc(cx, cy, r, a0 + sweep * .82, a0 + sweep)}" stroke="{t["danger"]}" stroke-width="4" fill="none" opacity=".75"/>',
             f'<path d="{arc(cx, cy, r, a0, a0 + sweep * pct / ceiling)}" stroke="{color}" stroke-width="4" fill="none" '
             f'stroke-linecap="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1">'
             f'<animate attributeName="stroke-dashoffset" from="1" to="0" dur="2.2s" begin="{0.2 + i * .12:.2f}s" fill="freeze" '
             f'calcMode="spline" keySplines=".2 .8 .2 1"/></path>']
        for k in range(11):
            deg = a0 + sweep * k / 10
            x0, y0 = polar(cx, cy, r - (9 if k % 5 == 0 else 5), deg)
            x1, y1 = polar(cx, cy, r - 2, deg)
            g.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{t["muted"]}" stroke-width="{1.4 if k % 5 == 0 else .8}"/>')
        for k, label in ((0, "0"), (10, f"{ceiling}")):
            x, y = polar(cx, cy, r - 18, a0 + sweep * k / 10)
            g.append(f'<text x="{x:.1f}" y="{y + 3:.1f}" font-size="8" class="muted" text-anchor="middle">{label}</text>')

        target = a0 + sweep * pct / ceiling - 270  # ponteiro desenhado apontando para cima (-90°)
        start = a0 - 270
        nx, ny = cx, cy - r + 8
        g.append(
            f'<g><g><path d="M{cx - 2.2:.1f},{cy} L{nx:.1f},{ny:.1f} L{cx + 2.2:.1f},{cy} Z" fill="{t["warn"]}"/>'
            f'<animateTransform attributeName="transform" type="rotate" values="{start} {cx:.1f} {cy};{target + 6:.1f} {cx:.1f} {cy};{target:.1f} {cx:.1f} {cy}" '
            f'keyTimes="0;.75;1" dur="2.2s" begin="{0.2 + i * .12:.2f}s" fill="freeze" calcMode="spline" keySplines=".3 .7 .3 1;.4 0 .6 1"/></g>'
            f'<animateTransform attributeName="transform" type="rotate" values="0 {cx:.1f} {cy};1.6 {cx:.1f} {cy};-1.2 {cx:.1f} {cy};0 {cx:.1f} {cy}" '
            f'dur="{0.35 + (i % 3) * .07:.2f}s" begin="{2.4 + i * .12:.2f}s" repeatCount="indefinite"/></g>'
            f'<circle cx="{cx:.1f}" cy="{cy}" r="5" fill="{t["brass"]}"/><circle cx="{cx:.1f}" cy="{cy}" r="2" fill="{t["bg"]}"/>')
        g.append(f'<text x="{cx:.1f}" y="{cy + 88}" font-size="17" font-weight="700" text-anchor="middle">{pct:.1f}%</text>')
        lx = cx - (len(name) * 6.6 + 12) / 2  # fonte monoespaçada: ~0.6em por caractere
        g.append(f'<circle cx="{lx + 4:.1f}" cy="{cy + 102}" r="4" fill="{color}"/>'
                 f'<text x="{lx + 12:.1f}" y="{cy + 106}" font-size="11" class="muted">{escape(name)}</text>')
        out.append(f'<g class="rise" style="animation-delay:{i * .08:.2f}s">{"".join(g)}</g>')
    return frame(h, t, "\n".join(out))


# ───────────────────────── diário de bordo ─────────────────────────

def smooth(pts):
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(len(pts) - 1):
        p0, p1, p2 = pts[max(i - 1, 0)], pts[i], pts[i + 1]
        p3 = pts[min(i + 2, len(pts) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def diario(s, t):
    h, x0, x1, base, amp = 280, 34, W - 34, 232, 138
    weeks = s["weeks"]
    peak = max((c for _, c in weeks), default=0) or 1
    step = (x1 - x0) / max(len(weeks) - 1, 1)
    # raiz quadrada: semanas calmas ainda aparecem como marola
    pts = [(x0 + i * step, base - 6 - amp * math.sqrt(c / peak)) for i, (_, c) in enumerate(weeks)]
    line = smooth(pts)
    out = [header(t, "⚓", "DIÁRIO DE BORDO · CONTRIBUIÇÕES POR SEMANA",
                  f'{fmt(s["total"])} CONTRIBUIÇÕES EM 12 MESES')]
    out.append(f'<defs><linearGradient id="mar" x1="0" y1="0" x2="0" y2="1">'
               f'<stop offset="0" stop-color="{t["sea"]}" stop-opacity=".55"/>'
               f'<stop offset="1" stop-color="{t["sea"]}" stop-opacity=".04"/></linearGradient>'
               f'<clipPath id="reveal"><rect x="0" y="0" width="0" height="{h}">'
               f'<animate attributeName="width" from="0" to="{W}" dur="2.6s" fill="freeze" calcMode="spline" keySplines=".3 .7 .2 1"/></rect></clipPath></defs>')
    for k in (0.25, 0.5, 0.75, 1):
        y = base - 6 - amp * k
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{t["grid"]}" stroke-dasharray="1 5"/>')
    out.append(f'<g clip-path="url(#reveal)"><path d="{line} L{x1},{base} L{x0},{base} Z" fill="url(#mar)"/>'
               f'<path d="{line}" fill="none" stroke="{t["sea"]}" stroke-width="2"/></g>')
    out.append(f'<line x1="{x0}" y1="{base}" x2="{x1}" y2="{base}" stroke="{t["line"]}"/>')

    last_m = None
    for i, (d, _) in enumerate(weeks):
        if d.month != last_m and i < len(weeks) - 2:
            last_m = d.month
            if i == 0 and weeks[1][0].month != d.month:
                continue
            out.append(f'<text x="{x0 + i * step:.1f}" y="{base + 18}" font-size="9" class="muted">{MESES[d.month - 1]}</text>')

    bi = max(range(len(weeks)), key=lambda i: weeks[i][1]) if weeks else 0
    if weeks:
        bx, by = pts[bi]
        anchor = "end" if bx > W - 160 else "start"
        dx = -8 if anchor == "end" else 8
        out.append(f'<g class="rise" style="animation-delay:2.4s"><line x1="{bx:.1f}" y1="{by - 4:.1f}" x2="{bx:.1f}" y2="{by - 26:.1f}" stroke="{t["brass"]}"/>'
                   f'<path d="M{bx:.1f},{by - 26:.1f} l9,4 l-9,4 Z" fill="{t["danger"]}"/>'
                   f'<text x="{bx + dx:.1f}" y="{by - 30:.1f}" font-size="9.5" class="brass" text-anchor="{anchor}">'
                   f'semana recorde · {fmt(weeks[bi][1])} em {weeks[bi][0].strftime("%d/%m")}</text></g>')

    ship = (f'<g><path d="M-17,-8 L19,-8 L12,0 L-13,0 Z" fill="{t["text"]}"/>'
            f'<rect x="-10" y="-14" width="15" height="6" fill="{t["text"]}"/>'
            f'<rect x="-6" y="-19" width="8" height="5" fill="{t["text"]}"/>'
            f'<rect x="-4.5" y="-17.5" width="5" height="2" fill="{t["bg"]}"/>'
            f'<line x1="6" y1="-8" x2="6" y2="-27" stroke="{t["text"]}" stroke-width="1.2"/>'
            f'<path d="M6,-27 l8,2.5 l-8,2.5 Z" fill="{t["accent"]}"/>'
            f'<animateMotion dur="26s" repeatCount="indefinite" rotate="auto" path="{line}"/></g>')
    out.append(ship)
    return frame(h, t, "\n".join(out))


# ───────────────────────────── sinais ─────────────────────────────

RED, BLUE, YEL, BLK, WHT = "#d52b1e", "#0b3d91", "#f7d117", "#151515", "#ffffff"


def flag(letter, s=34):
    """Bandeiras do Código Internacional de Sinais, desenhadas em (0,0)–(s,s)."""
    m = s / 2
    if letter == "A":
        return (f'<path d="M0,0H{m}V{s}H0Z" fill="{WHT}"/>'
                f'<path d="M{m},0H{s}L{s * .72:.1f},{m}L{s},{s}H{m}Z" fill="{BLUE}"/>'
                f'<path d="M0,0H{s}L{s * .72:.1f},{m}L{s},{s}H0Z" fill="none" stroke="#00000033"/>')
    shapes = {
        "B": f'<path d="M0,0H{s}L{s * .72:.1f},{m}L{s},{s}H0Z" fill="{RED}"/>',
        "D": f'<rect width="{s}" height="{s}" fill="{YEL}"/><rect y="{s / 4}" width="{s}" height="{m}" fill="{BLUE}"/>',
        "I": f'<rect width="{s}" height="{s}" fill="{YEL}"/><circle cx="{m}" cy="{m}" r="{s * .24:.1f}" fill="{BLK}"/>',
        "M": f'<rect width="{s}" height="{s}" fill="{BLUE}"/><path d="M0,0L{s},{s}M{s},0L0,{s}" stroke="{WHT}" stroke-width="{s * .2:.1f}"/>',
        "O": f'<path d="M0,0H{s}V{s}Z" fill="{RED}"/><path d="M0,0V{s}H{s}Z" fill="{YEL}"/>',
        "S": f'<rect width="{s}" height="{s}" fill="{WHT}"/><rect x="{s * .3:.1f}" y="{s * .3:.1f}" width="{s * .4:.1f}" height="{s * .4:.1f}" fill="{BLUE}"/>',
        "Z": (f'<path d="M0,0H{s}L{m},{m}Z" fill="{YEL}"/><path d="M{s},0V{s}L{m},{m}Z" fill="{BLUE}"/>'
              f'<path d="M0,{s}H{s}L{m},{m}Z" fill="{RED}"/><path d="M0,0V{s}L{m},{m}Z" fill="{BLK}"/>'),
    }
    body = shapes[letter]
    if letter in "B":
        return body
    return f'{body}<rect width="{s}" height="{s}" fill="none" stroke="#00000033"/>'


def sinais(s, t):
    h = 196
    out = [header(t, "⚑", "SINAIS · CÓDIGO INTERNACIONAL", "ATÉ A PRÓXIMA ESCALA")]
    words = ["SAM", "DAMAZIO", " ", "BZ"]
    seq = " ".join(words).replace("   ", "  ")
    fs, gap = 34, 8
    total = sum(fs + gap if ch != " " else 18 for ch in seq)
    x, y_rope = (W - total) / 2, 74
    sag = 12
    out.append(f'<path d="M24,{y_rope - 8} Q{W / 2},{y_rope + sag * 2} {W - 24},{y_rope - 8}" fill="none" stroke="{t["muted"]}" stroke-width="1.2"/>')

    def rope_y(px):
        u = (px - 24) / (W - 48)
        return (1 - u) ** 2 * (y_rope - 8) + 2 * u * (1 - u) * (y_rope + sag * 2) + u ** 2 * (y_rope - 8)

    for i, ch in enumerate(seq):
        if ch == " ":
            x += 18
            continue
        top = rope_y(x + fs / 2)
        pivot = f"{fs / 2} 0"
        out.append(
            f'<g transform="translate({x:.1f},{top + 4:.1f})"><line x1="{fs / 2}" y1="-4" x2="{fs / 2}" y2="0" stroke="{t["muted"]}"/>'
            f'<g><svg width="{fs}" height="{fs}" overflow="hidden">{flag(ch, fs)}</svg><animateTransform attributeName="transform" type="rotate" '
            f'values="-3 {pivot};3 {pivot};-3 {pivot}" dur="{3 + (i % 4) * .4:.1f}s" begin="{-i * .37:.2f}s" repeatCount="indefinite"/></g>'
            f'<text x="{fs / 2}" y="{fs + 16}" font-size="10" class="muted" text-anchor="middle">{ch}</text></g>')
        x += fs + gap

    lead, rest = "BZ · Bravo Zulu", " — na Marinha, “bom trabalho”. Obrigado pela visita!"
    lx = W / 2 - (len(lead) + len(rest)) * 7.2 / 2
    out.append(f'<text x="{lx:.1f}" y="{h - 42}" font-size="12" font-weight="700" class="brass">{lead}</text>'
               f'<text x="{lx + len(lead) * 7.2:.1f}" y="{h - 42}" font-size="12">{escape(rest)}</text>')
    out.append(f'<text x="{W / 2}" y="{h - 22}" font-size="9.5" class="muted" text-anchor="middle">'
               f'painéis gerados por .github/scripts/ponte.py e atualizados pelo GitHub Actions</text>')
    return frame(h, t, "\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="samdamazio")
    ap.add_argument("--out", default="assets")
    args = ap.parse_args()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("defina GH_TOKEN")
    s = summarize(fetch(args.user, token), args.user)
    os.makedirs(args.out, exist_ok=True)
    for name, render in (("sonar", sonar), ("maquinas", maquinas), ("diario", diario), ("sinais", sinais)):
        for theme, t in THEMES.items():
            with open(os.path.join(args.out, f"{name}-{theme}.svg"), "w", encoding="utf-8") as f:
                f.write(render(s, t))
    print(f"ok · {s['total']} contribuições · {len(s['langs'])} linguagens · {len(s['contacts'])} contatos")


if __name__ == "__main__":
    main()
