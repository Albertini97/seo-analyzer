from flask import Flask, request, jsonify, render_template, Response
from flask_cors import CORS
from bs4 import BeautifulSoup
import requests
import time
import re
import io
from urllib.parse import urljoin, urlparse
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SEOAnalyzer/1.0; +https://github.com/Albertini97)"
}

PAGESPEED_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

def fetch_page(url):
    start = time.time()
    resp = requests.get(url, headers=HEADERS, timeout=15)
    load_time = round(time.time() - start, 2)
    resp.raise_for_status()
    return resp.text, load_time, len(resp.content)

def fetch_pagespeed(url):
    try:
        params = {"url": url, "strategy": "mobile", "category": ["performance", "seo", "accessibility"]}
        resp = requests.get(PAGESPEED_API, params=params, timeout=30)
        data = resp.json()
        cats = data.get("lighthouseResult", {}).get("categories", {})
        audits = data.get("lighthouseResult", {}).get("audits", {})
        lcp = audits.get("largest-contentful-paint", {}).get("displayValue", "N/A")
        tbt = audits.get("total-blocking-time", {}).get("displayValue", "N/A")
        cls = audits.get("cumulative-layout-shift", {}).get("displayValue", "N/A")
        fcp = audits.get("first-contentful-paint", {}).get("displayValue", "N/A")
        perf_score = int((cats.get("performance", {}).get("score") or 0) * 100)
        seo_score = int((cats.get("seo", {}).get("score") or 0) * 100)
        a11y_score = int((cats.get("accessibility", {}).get("score") or 0) * 100)
        return {
            "available": True,
            "performance_score": perf_score,
            "seo_score": seo_score,
            "accessibility_score": a11y_score,
            "lcp": lcp,
            "tbt": tbt,
            "cls": cls,
            "fcp": fcp,
        }
    except Exception:
        return {"available": False}

def analyze_title(soup):
    tag = soup.find("title")
    title = tag.get_text(strip=True) if tag else ""
    length = len(title)
    issues = []
    if not title:
        issues.append("❌ No tiene etiqueta <title>")
    elif length < 30:
        issues.append(f"⚠️ Título demasiado corto ({length} caracteres, mínimo recomendado: 30)")
    elif length > 60:
        issues.append(f"⚠️ Título demasiado largo ({length} caracteres, máximo recomendado: 60)")
    else:
        issues.append(f"✅ Longitud correcta ({length} caracteres)")
    return {"text": title, "length": length, "issues": issues}

def analyze_meta_description(soup):
    tag = soup.find("meta", attrs={"name": "description"})
    desc = tag.get("content", "").strip() if tag else ""
    length = len(desc)
    issues = []
    if not desc:
        issues.append("❌ No tiene meta description")
    elif length < 70:
        issues.append(f"⚠️ Meta description corta ({length} caracteres, mínimo recomendado: 70)")
    elif length > 160:
        issues.append(f"⚠️ Meta description larga ({length} caracteres, máximo recomendado: 160)")
    else:
        issues.append(f"✅ Longitud correcta ({length} caracteres)")
    return {"text": desc, "length": length, "issues": issues}

def analyze_headings(soup):
    result = {}
    issues = []
    for level in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        tags = soup.find_all(level)
        result[level] = [t.get_text(strip=True) for t in tags]
    h1s = result["h1"]
    if not h1s:
        issues.append("❌ No hay ningún H1 en la página")
    elif len(h1s) > 1:
        issues.append(f"⚠️ Hay {len(h1s)} H1 — se recomienda solo uno")
    else:
        issues.append(f"✅ Un único H1: \"{h1s[0][:60]}\"")
    if not result["h2"]:
        issues.append("⚠️ No hay H2 — considera estructurar el contenido con subtítulos")
    else:
        issues.append(f"✅ {len(result['h2'])} H2 encontrados")
    return {"headings": result, "issues": issues}

def analyze_images(soup, base_url):
    imgs = soup.find_all("img")
    total = len(imgs)
    without_alt, empty_alt = [], []
    for img in imgs:
        alt = img.get("alt")
        src = img.get("src", "")
        if alt is None:
            without_alt.append(src)
        elif alt.strip() == "":
            empty_alt.append(src)
    issues = []
    if without_alt:
        issues.append(f"❌ {len(without_alt)} imagen(es) sin atributo alt")
    if empty_alt:
        issues.append(f"⚠️ {len(empty_alt)} imagen(es) con alt vacío")
    if not without_alt and not empty_alt:
        issues.append(f"✅ Todas las imágenes ({total}) tienen alt text")
    if total == 0:
        issues.append("ℹ️ No se encontraron imágenes en la página")
    return {"total": total, "without_alt": len(without_alt), "empty_alt": len(empty_alt), "issues": issues}

def analyze_links(soup, base_url):
    links = soup.find_all("a", href=True)
    internal, external, nofollow = [], [], []
    base_domain = urlparse(base_url).netloc
    for a in links:
        href = a.get("href", "")
        rel = a.get("rel", [])
        full_url = urljoin(base_url, href)
        domain = urlparse(full_url).netloc
        text = a.get_text(strip=True)
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if domain == base_domain:
            internal.append({"url": full_url, "text": text[:50]})
        else:
            external.append({"url": full_url, "text": text[:50]})
        if "nofollow" in rel:
            nofollow.append(full_url)
    issues = [f"ℹ️ {len(internal)} enlaces internos · {len(external)} enlaces externos"]
    if nofollow:
        issues.append(f"ℹ️ {len(nofollow)} enlace(s) con rel='nofollow'")
    return {"internal_count": len(internal), "external_count": len(external), "nofollow_count": len(nofollow), "issues": issues}

def analyze_technical(soup, url):
    issues = []
    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href", "") if canonical else ""
    if not canonical_url:
        issues.append("⚠️ No tiene URL canónica (rel=canonical)")
    else:
        issues.append(f"✅ Canonical: {canonical_url[:60]}")
    robots = soup.find("meta", attrs={"name": re.compile("robots", re.I)})
    robots_content = robots.get("content", "") if robots else ""
    if "noindex" in robots_content.lower():
        issues.append("❌ La página tiene meta robots=noindex — Google no la indexará")
    elif robots_content:
        issues.append(f"✅ Meta robots: {robots_content}")
    else:
        issues.append("ℹ️ No tiene meta robots (se asume indexable)")
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if not viewport:
        issues.append("❌ Sin meta viewport — puede no ser móvil-friendly")
    else:
        issues.append("✅ Meta viewport presente (móvil-friendly)")
    html_tag = soup.find("html")
    lang = html_tag.get("lang", "") if html_tag else ""
    if not lang:
        issues.append("⚠️ El atributo lang no está definido en <html>")
    else:
        issues.append(f"✅ Idioma declarado: {lang}")
    if url.startswith("https://"):
        issues.append("✅ Usa HTTPS")
    else:
        issues.append("❌ No usa HTTPS — penalización SEO y de seguridad")
    return {"canonical": canonical_url, "robots": robots_content, "viewport": bool(viewport), "lang": lang, "https": url.startswith("https://"), "issues": issues}

def analyze_opengraph(soup):
    og_tags = {}
    for tag in soup.find_all("meta", property=re.compile("^og:")):
        og_tags[tag.get("property", "")] = tag.get("content", "")
    twitter_tags = {}
    for tag in soup.find_all("meta", attrs={"name": re.compile("^twitter:")}):
        twitter_tags[tag.get("name", "")] = tag.get("content", "")
    issues = []
    essential_og = ["og:title", "og:description", "og:image", "og:url"]
    missing = [k for k in essential_og if k not in og_tags]
    if missing:
        issues.append(f"⚠️ Open Graph incompleto — faltan: {', '.join(missing)}")
    else:
        issues.append("✅ Open Graph completo (title, description, image, url)")
    if not twitter_tags:
        issues.append("⚠️ Sin Twitter/X Card meta tags")
    else:
        issues.append("✅ Twitter/X Card meta tags presentes")
    return {"og": og_tags, "twitter": twitter_tags, "issues": issues}

def analyze_performance(load_time, page_size_bytes):
    issues = []
    size_kb = round(page_size_bytes / 1024, 1)
    if load_time < 1.0:
        issues.append(f"✅ Tiempo de carga del servidor: {load_time}s (excelente)")
    elif load_time < 2.5:
        issues.append(f"✅ Tiempo de carga del servidor: {load_time}s (bueno)")
    elif load_time < 4.0:
        issues.append(f"⚠️ Tiempo de carga del servidor: {load_time}s (mejorable)")
    else:
        issues.append(f"❌ Tiempo de carga del servidor: {load_time}s (lento)")
    if size_kb < 200:
        issues.append(f"✅ Tamaño HTML: {size_kb} KB (ligero)")
    elif size_kb < 500:
        issues.append(f"ℹ️ Tamaño HTML: {size_kb} KB (normal)")
    else:
        issues.append(f"⚠️ Tamaño HTML: {size_kb} KB (considera optimizar)")
    return {"load_time": load_time, "size_kb": size_kb, "issues": issues}

def compute_score(results):
    score = 100
    deductions = []
    if not results["title"]["text"]:
        score -= 15; deductions.append("Sin título (-15)")
    elif results["title"]["length"] > 60 or results["title"]["length"] < 30:
        score -= 5; deductions.append("Título fuera de rango (-5)")
    if not results["meta_description"]["text"]:
        score -= 10; deductions.append("Sin meta description (-10)")
    elif results["meta_description"]["length"] > 160 or results["meta_description"]["length"] < 70:
        score -= 3; deductions.append("Meta description fuera de rango (-3)")
    h1s = results["headings"]["headings"]["h1"]
    if not h1s:
        score -= 10; deductions.append("Sin H1 (-10)")
    elif len(h1s) > 1:
        score -= 5; deductions.append("Múltiples H1 (-5)")
    if results["images"]["without_alt"] > 0:
        score -= min(results["images"]["without_alt"] * 2, 10)
        deductions.append(f"Imágenes sin alt (-{min(results['images']['without_alt']*2,10)})")
    if not results["technical"]["canonical"]:
        score -= 5; deductions.append("Sin canonical (-5)")
    if not results["technical"]["viewport"]:
        score -= 8; deductions.append("Sin viewport (-8)")
    if not results["technical"]["https"]:
        score -= 10; deductions.append("Sin HTTPS (-10)")
    if not results["technical"]["lang"]:
        score -= 3; deductions.append("Sin lang (-3)")
    essential_og = ["og:title", "og:description", "og:image", "og:url"]
    missing_og = [k for k in essential_og if k not in results["open_graph"]["og"]]
    if len(missing_og) >= 3:
        score -= 5; deductions.append("Open Graph incompleto (-5)")
    if results["performance"]["load_time"] > 4:
        score -= 8; deductions.append("Carga muy lenta (-8)")
    elif results["performance"]["load_time"] > 2.5:
        score -= 4; deductions.append("Carga lenta (-4)")
    return max(score, 0), deductions

def build_pdf_reportlab(d):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    GREEN = colors.HexColor('#00E5A0')
    RED   = colors.HexColor('#EF4444')
    YELLOW= colors.HexColor('#FBBF24')
    DARK  = colors.HexColor('#0D1017')
    GRAY  = colors.HexColor('#6B7A94')
    LIGHT = colors.HexColor('#F3F4F6')

    score_color = GREEN if d['score'] >= 80 else YELLOW if d['score'] >= 60 else RED

    styles = getSampleStyleSheet()
    title_style   = ParagraphStyle('title',   fontName='Helvetica-Bold', fontSize=18, textColor=GREEN,   spaceAfter=4)
    sub_style     = ParagraphStyle('sub',     fontName='Helvetica',      fontSize=9,  textColor=GRAY,    spaceAfter=2)
    h2_style      = ParagraphStyle('h2',      fontName='Helvetica-Bold', fontSize=11, textColor=DARK,    spaceBefore=10, spaceAfter=4)
    body_style    = ParagraphStyle('body',    fontName='Helvetica',      fontSize=8,  textColor=colors.HexColor('#374151'), spaceAfter=3, leading=12)
    mono_style    = ParagraphStyle('mono',    fontName='Courier',        fontSize=8,  textColor=DARK,    spaceAfter=3, backColor=LIGHT, borderPad=4)
    issue_style   = ParagraphStyle('issue',   fontName='Helvetica',      fontSize=8,  textColor=colors.HexColor('#374151'), spaceAfter=2, leading=11)
    footer_style  = ParagraphStyle('footer',  fontName='Helvetica',      fontSize=7,  textColor=GRAY,    alignment=TA_CENTER)

    story = []
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Header table
    header_data = [[
        Paragraph('🔍 SEO Analyzer Report', title_style),
        Paragraph(f'Generado: {now}<br/>by Alberto Labarta · github.com/Albertini97', sub_style)
    ]]
    header_table = Table(header_data, colWidths=[10*cm, 7*cm])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), DARK),
        ('PADDING', (0,0), (-1,-1), 12),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4*cm))

    # Score box
    score_label = '✅ Buen SEO' if d['score'] >= 80 else '⚠️ SEO mejorable' if d['score'] >= 60 else '❌ SEO deficiente'
    ded_text = '  ·  '.join(d['deductions']) if d['deductions'] else 'Sin penalizaciones'
    score_data = [[
        Paragraph(f'<font size=28><b>{d["score"]}</b></font><font size=10 color="#6B7A94"> / 100</font>', ParagraphStyle('sc', fontName='Helvetica-Bold', fontSize=28, textColor=score_color)),
        [Paragraph(f'<b>{score_label}</b>', ParagraphStyle('sl', fontName='Helvetica-Bold', fontSize=12, textColor=score_color, spaceAfter=4)),
         Paragraph(d['url'], ParagraphStyle('su', fontName='Courier', fontSize=7, textColor=GRAY, spaceAfter=6)),
         Paragraph(ded_text, ParagraphStyle('sd', fontName='Helvetica', fontSize=7, textColor=RED))]
    ]]
    score_table = Table(score_data, colWidths=[3.5*cm, 13.5*cm])
    score_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LIGHT),
        ('LEFTPADDING', (0,0), (0,0), 16),
        ('PADDING', (1,0), (1,0), 12),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LINEAFTER', (0,0), (0,0), 1, score_color),
        ('BOX', (0,0), (-1,-1), 0.5, score_color),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 0.5*cm))

    # PageSpeed
    ps = d.get('pagespeed', {})
    if ps.get('available'):
        story.append(Paragraph('⚡ Core Web Vitals · Google PageSpeed (móvil)', h2_style))
        cwv_data = [
            ['Performance', 'SEO Score', 'Accesibilidad', 'LCP', 'TBT', 'CLS'],
            [str(ps['performance_score']), str(ps['seo_score']), str(ps['accessibility_score']),
             ps['lcp'], ps['tbt'], ps['cls']]
        ]
        cwv_table = Table(cwv_data, colWidths=[2.8*cm]*6)
        cwv_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), DARK),
            ('TEXTCOLOR', (0,0), (-1,0), GREEN),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [LIGHT, colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
            ('PADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(cwv_table)
        story.append(Spacer(1, 0.4*cm))

    def section(title, issues, value=None):
        story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#E5E7EB'), spaceAfter=6))
        story.append(Paragraph(title, h2_style))
        if value is not None:
            story.append(Paragraph(value or '(vacío)', mono_style))
        for i in issues:
            story.append(Paragraph(i, issue_style))
        story.append(Spacer(1, 0.2*cm))

    section('📝 Título', d['title']['issues'], d['title']['text'])
    section('📄 Meta Description', d['meta_description']['issues'], d['meta_description']['text'])

    # Headings table
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#E5E7EB'), spaceAfter=6))
    story.append(Paragraph('🏗️ Headings', h2_style))
    hd = d['headings']['headings']
    h_data = [['H1','H2','H3','H4','H5','H6']]
    max_rows = max(len(hd[f'h{i}']) for i in range(1,7)) or 1
    for r in range(max_rows):
        row = []
        for i in range(1,7):
            items = hd[f'h{i}']
            row.append(Paragraph(items[r][:40] if r < len(items) else '—', ParagraphStyle('hc', fontName='Helvetica', fontSize=7, textColor=colors.HexColor('#374151'))))
        h_data.append(row)
    h_table = Table(h_data, colWidths=[2.8*cm]*6)
    h_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), DARK),
        ('TEXTCOLOR', (0,0), (-1,0), GREEN),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [LIGHT, colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(h_table)
    for i in d['headings']['issues']:
        story.append(Paragraph(i, issue_style))
    story.append(Spacer(1, 0.3*cm))

    # Images + links side by side
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#E5E7EB'), spaceAfter=6))
    img_text = [Paragraph('🖼️ Imágenes', h2_style)] + [Paragraph(i, issue_style) for i in d['images']['issues']]
    lnk_text = [Paragraph('🔗 Enlazado', h2_style)] + [Paragraph(i, issue_style) for i in d['links']['issues']]
    two_col = Table([[img_text, lnk_text]], colWidths=[8.5*cm, 8.5*cm])
    two_col.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),0)]))
    story.append(two_col)
    story.append(Spacer(1, 0.3*cm))

    section('🔧 SEO Técnico', d['technical']['issues'])
    section('⚡ Performance del servidor', d['performance']['issues'])

    # Open Graph
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#E5E7EB'), spaceAfter=6))
    story.append(Paragraph('📱 Open Graph', h2_style))
    og = d['open_graph']['og']
    if og:
        og_rows = [[Paragraph(f'<font color="#00E5A0"><b>{k}</b></font>', ParagraphStyle('ogk', fontName='Helvetica-Bold', fontSize=7)),
                    Paragraph(v[:80], ParagraphStyle('ogv', fontName='Helvetica', fontSize=7, textColor=colors.HexColor('#374151')))]
                   for k,v in list(og.items())[:8]]
        og_table = Table(og_rows, colWidths=[4*cm, 13*cm])
        og_table.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [LIGHT, colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(og_table)
    for i in d['open_graph']['issues']:
        story.append(Paragraph(i, issue_style))

    story.append(Spacer(1, 0.6*cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=GREEN))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph('SEO Analyzer · Alberto Labarta Holgado · github.com/Albertini97 · soyalbertolabartaholgado@gmail.com', footer_style))

    doc.build(story)
    buf.seek(0)
    return buf.read()

def build_pdf_html(d):
    score_color = "#00E5A0" if d["score"] >= 80 else "#FBBF24" if d["score"] >= 60 else "#EF4444"
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    def issues_html(issues):
        return "".join(f'<li>{i}</li>' for i in issues)

    ps = d.get("pagespeed", {})
    pagespeed_section = ""
    if ps.get("available"):
        pagespeed_section = f"""
        <div class="section">
          <h2>⚡ Core Web Vitals (Google PageSpeed)</h2>
          <div class="cwv-grid">
            <div class="cwv-item"><div class="cwv-val">{ps['performance_score']}</div><div class="cwv-label">Performance</div></div>
            <div class="cwv-item"><div class="cwv-val">{ps['seo_score']}</div><div class="cwv-label">SEO Score</div></div>
            <div class="cwv-item"><div class="cwv-val">{ps['accessibility_score']}</div><div class="cwv-label">Accesibilidad</div></div>
            <div class="cwv-item"><div class="cwv-val">{ps['lcp']}</div><div class="cwv-label">LCP</div></div>
            <div class="cwv-item"><div class="cwv-val">{ps['tbt']}</div><div class="cwv-label">TBT</div></div>
            <div class="cwv-item"><div class="cwv-val">{ps['cls']}</div><div class="cwv-label">CLS</div></div>
          </div>
        </div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <style>
      body{{font-family:Arial,sans-serif;color:#1a1a1a;margin:0;padding:0;font-size:13px}}
      .header{{background:#060810;color:#E8EDF5;padding:2rem 2.5rem;display:flex;justify-content:space-between;align-items:center}}
      .header h1{{margin:0;font-size:1.4rem;color:#00E5A0}}
      .header .meta{{font-size:0.75rem;color:#6B7A94;text-align:right}}
      .score-box{{background:#f8f9fa;border-left:4px solid {score_color};padding:1.5rem 2rem;margin:1.5rem 2rem;display:flex;align-items:center;gap:2rem}}
      .score-circle{{width:70px;height:70px;border-radius:50%;border:3px solid {score_color};display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0}}
      .score-num{{font-size:1.6rem;font-weight:bold;color:{score_color};line-height:1}}
      .score-label{{font-size:0.55rem;color:#888;text-transform:uppercase}}
      .score-url{{font-size:0.75rem;color:#666;margin-top:0.3rem;word-break:break-all}}
      .deductions{{display:flex;flex-wrap:wrap;gap:6px;margin-top:0.8rem}}
      .ded{{font-size:0.65rem;padding:2px 8px;background:#fee2e2;color:#dc2626;border-radius:2px}}
      .section{{margin:0 2rem 1.5rem;padding-bottom:1rem;border-bottom:1px solid #e5e7eb}}
      .section h2{{font-size:0.95rem;color:#111;margin-bottom:0.8rem;border-left:3px solid #00E5A0;padding-left:0.7rem}}
      .value-box{{background:#f8f9fa;padding:0.6rem 0.8rem;font-size:0.8rem;color:#374151;margin-bottom:0.7rem;border-left:2px solid #00E5A0;word-break:break-all}}
      .value-box.empty{{border-left-color:#EF4444;color:#9ca3af}}
      ul{{margin:0;padding-left:1.2rem}}
      li{{margin-bottom:4px;font-size:0.8rem;line-height:1.5}}
      .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}
      .stats-row{{display:flex;gap:2rem;margin-bottom:0.8rem}}
      .stat-item{{text-align:center}}
      .stat-num{{font-size:1.3rem;font-weight:bold;color:#111}}
      .stat-label{{font-size:0.65rem;color:#888;text-transform:uppercase}}
      .cwv-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:0.8rem;margin-bottom:0.8rem}}
      .cwv-item{{background:#f8f9fa;padding:0.8rem;text-align:center}}
      .cwv-val{{font-size:1.1rem;font-weight:bold;color:#111}}
      .cwv-label{{font-size:0.65rem;color:#888;margin-top:2px}}
      .footer{{background:#f8f9fa;padding:1rem 2rem;font-size:0.7rem;color:#888;text-align:center;margin-top:1rem}}
      .heading-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:0.8rem;margin-bottom:0.8rem}}
      .heading-group .hl{{font-size:0.65rem;font-weight:bold;color:#00E5A0;margin-bottom:4px;text-transform:uppercase}}
      .heading-group .hi{{font-size:0.75rem;color:#555;border-bottom:1px solid #e5e7eb;padding:2px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
      .og-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-bottom:0.8rem}}
      .og-item{{background:#f8f9fa;padding:0.5rem 0.7rem}}
      .og-key{{font-size:0.6rem;color:#00E5A0;font-weight:bold}}
      .og-val{{font-size:0.72rem;color:#555;word-break:break-all}}
    </style></head><body>
    <div class="header">
      <div><h1>🔍 SEO Analyzer Report</h1><div style="color:#6B7A94;font-size:0.8rem;margin-top:4px">{d['url']}</div></div>
      <div class="meta"><div>Generado el {now}</div><div style="margin-top:4px">by Alberto Labarta · github.com/Albertini97</div></div>
    </div>
    <div class="score-box">
      <div class="score-circle"><div class="score-num">{d['score']}</div><div class="score-label">/ 100</div></div>
      <div>
        <div style="font-weight:bold;font-size:1rem">{'✅ Buen SEO' if d['score'] >= 80 else '⚠️ SEO mejorable' if d['score'] >= 60 else '❌ SEO deficiente'}</div>
        <div class="score-url">{d['url']}</div>
        <div class="deductions">{''.join(f'<span class="ded">{x}</span>' for x in d['deductions'])}</div>
      </div>
    </div>
    {pagespeed_section}
    <div class="grid2" style="margin:0 2rem 1.5rem">
      <div><div class="section" style="margin:0 0 1rem"><h2>📝 Título</h2>
        <div class="value-box {'empty' if not d['title']['text'] else ''}">{d['title']['text'] or '(sin título)'}</div>
        <ul>{issues_html(d['title']['issues'])}</ul></div></div>
      <div><div class="section" style="margin:0 0 1rem"><h2>📄 Meta Description</h2>
        <div class="value-box {'empty' if not d['meta_description']['text'] else ''}">{d['meta_description']['text'] or '(sin meta description)'}</div>
        <ul>{issues_html(d['meta_description']['issues'])}</ul></div></div>
    </div>
    <div class="section"><h2>🏗️ Headings</h2>
      <div class="heading-grid">{''.join(f"""<div class="heading-group"><div class="hl">{lv.upper()} ({len(d['headings']['headings'][lv])})</div>{''.join(f'<div class="hi">{t or "(vacío)"}</div>' for t in d['headings']['headings'][lv][:3]) or '<div style="font-size:0.72rem;color:#9ca3af;font-style:italic">— ninguno</div>'}</div>""" for lv in ['h1','h2','h3','h4','h5','h6'])}</div>
      <ul>{issues_html(d['headings']['issues'])}</ul></div>
    <div class="grid2" style="margin:0 2rem 1.5rem">
      <div><div class="section" style="margin:0 0 1rem"><h2>🖼️ Imágenes</h2>
        <div class="stats-row">
          <div class="stat-item"><div class="stat-num">{d['images']['total']}</div><div class="stat-label">Total</div></div>
          <div class="stat-item"><div class="stat-num" style="color:#EF4444">{d['images']['without_alt']}</div><div class="stat-label">Sin alt</div></div>
          <div class="stat-item"><div class="stat-num" style="color:#FBBF24">{d['images']['empty_alt']}</div><div class="stat-label">Alt vacío</div></div>
        </div><ul>{issues_html(d['images']['issues'])}</ul></div></div>
      <div><div class="section" style="margin:0 0 1rem"><h2>🔗 Enlazado</h2>
        <div class="stats-row">
          <div class="stat-item"><div class="stat-num">{d['links']['internal_count']}</div><div class="stat-label">Internos</div></div>
          <div class="stat-item"><div class="stat-num">{d['links']['external_count']}</div><div class="stat-label">Externos</div></div>
          <div class="stat-item"><div class="stat-num">{d['links']['nofollow_count']}</div><div class="stat-label">Nofollow</div></div>
        </div><ul>{issues_html(d['links']['issues'])}</ul></div></div>
    </div>
    <div class="grid2" style="margin:0 2rem 1.5rem">
      <div><div class="section" style="margin:0 0 1rem"><h2>🔧 SEO Técnico</h2><ul>{issues_html(d['technical']['issues'])}</ul></div></div>
      <div><div class="section" style="margin:0 0 1rem"><h2>⚡ Performance</h2><ul>{issues_html(d['performance']['issues'])}</ul></div></div>
    </div>
    <div class="section"><h2>📱 Open Graph</h2>
      {'<div class="og-grid">' + ''.join(f'<div class="og-item"><div class="og-key">{k}</div><div class="og-val">{v[:80]}</div></div>' for k,v in list(d['open_graph']['og'].items())[:8]) + '</div>' if d['open_graph']['og'] else '<p style="font-size:0.8rem;color:#9ca3af">No se encontraron etiquetas Open Graph</p>'}
      <ul>{issues_html(d['open_graph']['issues'])}</ul></div>
    <div class="footer">SEO Analyzer · Construido por Alberto Labarta · github.com/Albertini97</div>
    </body></html>"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    url = data.get("url", "").strip()
    include_pagespeed = data.get("pagespeed", True)
    if not url:
        return jsonify({"error": "URL requerida"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        html, load_time, page_size = fetch_page(url)
    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout: la página tardó demasiado en responder (>15s)"}), 400
    except requests.exceptions.SSLError:
        return jsonify({"error": "Error SSL al conectar con la página"}), 400
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "No se pudo conectar con la URL"}), 400
    except Exception as e:
        return jsonify({"error": f"Error al acceder a la URL: {str(e)}"}), 400
    soup = BeautifulSoup(html, "html.parser")
    results = {
        "url": url,
        "title": analyze_title(soup),
        "meta_description": analyze_meta_description(soup),
        "headings": analyze_headings(soup),
        "images": analyze_images(soup, url),
        "links": analyze_links(soup, url),
        "technical": analyze_technical(soup, url),
        "open_graph": analyze_opengraph(soup),
        "performance": analyze_performance(load_time, page_size),
        "pagespeed": fetch_pagespeed(url) if include_pagespeed else {"available": False},
    }
    score, deductions = compute_score(results)
    results["score"] = score
    results["deductions"] = deductions
    return jsonify(results)

@app.route("/export-pdf", methods=["POST"])
def export_pdf():
    d = request.get_json()
    try:
        pdf = build_pdf_reportlab(d)
        domain = urlparse(d.get("url", "")).netloc.replace("www.", "")
        filename = f"seo-report-{domain}.pdf"
        return Response(pdf, mimetype="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5050)
