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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak, KeepTogether
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SEOAnalyzer/1.0; +https://github.com/Albertini97)"
}

import os

PAGESPEED_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PAGESPEED_KEY = os.environ.get("PAGESPEED_KEY", "")

def fetch_page(url):
    start = time.time()
    resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True, verify=True)
    load_time = round(time.time() - start, 2)
    resp.raise_for_status()
    return resp.text, load_time, len(resp.content)

def fetch_pagespeed(url):
    try:
        params = {"url": url, "strategy": "mobile", "category": ["performance", "seo", "accessibility"]}
        if PAGESPEED_KEY:
            params["key"] = PAGESPEED_KEY
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
    from reportlab.platypus import PageBreak, KeepTogether
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.graphics.shapes import Drawing, Rect, String, Circle
    from reportlab.graphics import renderPDF

    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4

    # ── Colores ────────────────────────────────────────────────
    GREEN   = colors.HexColor('#00C48C')
    GREEN_D = colors.HexColor('#009970')
    RED     = colors.HexColor('#EF4444')
    YELLOW  = colors.HexColor('#F59E0B')
    BLUE    = colors.HexColor('#3B82F6')
    DARK    = colors.HexColor('#0F172A')
    DARK2   = colors.HexColor('#1E293B')
    DARK3   = colors.HexColor('#334155')
    GRAY    = colors.HexColor('#64748B')
    LGRAY   = colors.HexColor('#94A3B8')
    LIGHT   = colors.HexColor('#F1F5F9')
    LIGHT2  = colors.HexColor('#F8FAFC')
    WHITE   = colors.white
    BORDER  = colors.HexColor('#E2E8F0')

    GREEN_BG  = colors.HexColor('#ECFDF5')
    GREEN_TXT = colors.HexColor('#065F46')
    RED_BG    = colors.HexColor('#FEF2F2')
    RED_TXT   = colors.HexColor('#991B1B')
    YEL_BG    = colors.HexColor('#FFFBEB')
    YEL_TXT   = colors.HexColor('#92400E')
    BLU_BG    = colors.HexColor('#EFF6FF')
    BLU_TXT   = colors.HexColor('#1E40AF')

    score_color = GREEN if d['score'] >= 80 else YELLOW if d['score'] >= 60 else RED
    score_bg    = GREEN_BG if d['score'] >= 80 else YEL_BG if d['score'] >= 60 else RED_BG
    score_txt   = GREEN_TXT if d['score'] >= 80 else YEL_TXT if d['score'] >= 60 else RED_TXT
    score_label = 'Buen SEO' if d['score'] >= 80 else 'SEO mejorable' if d['score'] >= 60 else 'SEO deficiente'
    now    = datetime.now().strftime("%d/%m/%Y  %H:%M")
    domain = urlparse(d['url']).netloc

    # ── Estilos ────────────────────────────────────────────────
    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    s_cover_h    = S('ch',  fontName='Helvetica-Bold', fontSize=28, textColor=WHITE,   leading=32, spaceAfter=6)
    s_cover_sub  = S('cs',  fontName='Helvetica',      fontSize=10, textColor=LGRAY,   leading=14)
    s_cover_url  = S('cu',  fontName='Courier-Bold',   fontSize=9,  textColor=GREEN,   spaceAfter=2)
    s_section    = S('sec', fontName='Helvetica-Bold', fontSize=13, textColor=WHITE,   leading=16)
    s_h2         = S('h2',  fontName='Helvetica-Bold', fontSize=10, textColor=DARK,    spaceBefore=6, spaceAfter=3)
    s_body       = S('bd',  fontName='Helvetica',      fontSize=8,  textColor=DARK3,   leading=12, spaceAfter=2)
    s_mono       = S('mn',  fontName='Courier',        fontSize=8,  textColor=DARK2,   backColor=LIGHT, leading=12, spaceAfter=4, leftIndent=8)
    s_ok         = S('ok',  fontName='Helvetica',      fontSize=8,  textColor=GREEN_TXT, leading=12, spaceAfter=2)
    s_warn       = S('wn',  fontName='Helvetica',      fontSize=8,  textColor=YEL_TXT,  leading=12, spaceAfter=2)
    s_err        = S('er',  fontName='Helvetica',      fontSize=8,  textColor=RED_TXT,  leading=12, spaceAfter=2)
    s_info       = S('inf', fontName='Helvetica',      fontSize=8,  textColor=GRAY,     leading=12, spaceAfter=2)
    s_label      = S('lb',  fontName='Helvetica-Bold', fontSize=7,  textColor=GRAY,     spaceAfter=1, leading=10)
    s_bignum     = S('bn',  fontName='Helvetica-Bold', fontSize=20, textColor=DARK,     leading=22)
    s_footer     = S('ft',  fontName='Helvetica',      fontSize=7,  textColor=LGRAY,    alignment=TA_CENTER)
    s_tag        = S('tg',  fontName='Helvetica-Bold', fontSize=7,  textColor=WHITE,    alignment=TA_CENTER)
    s_exec_title = S('et',  fontName='Helvetica-Bold', fontSize=9,  textColor=DARK,     spaceAfter=5, spaceBefore=4)

    def clean(text):
        for e, r in [('✅','[OK]'),('⚠️','[!]'),('❌','[X]'),('ℹ️','[i]'),
                     ('🔍',''),('📝',''),('📄',''),('🏗',''),('🖼',''),
                     ('🔗',''),('🔧',''),('⚡',''),('📱',''),('→','->'),('—','-')]:
            text = text.replace(e, r)
        return text.strip()

    def issue_para(text):
        t = clean(text)
        if '[OK]' in t:  return Paragraph(t, s_ok)
        if '[!]'  in t:  return Paragraph(t, s_warn)
        if '[X]'  in t:  return Paragraph(t, s_err)
        return Paragraph(t, s_info)

    def tag_cell(text, bg, fg):
        return Table([[Paragraph(text, S('tgi', fontName='Helvetica-Bold', fontSize=7, textColor=fg, alignment=TA_CENTER))]],
                     colWidths=[2.2*cm]).__class__

    def section_header(title, color=GREEN):
        d2 = Table([[Paragraph(title, s_section)]], colWidths=[17*cm])
        d2.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), color),
            ('PADDING',(0,0),(-1,-1), 10),
            ('BOTTOMPADDING',(0,0),(-1,-1), 8),
        ]))
        return d2

    def mini_bar(pct, color, width=16*cm):
        filled = max(0.5, min(pct/100, 1)) * width
        empty  = width - filled
        bar = Table([['','']], colWidths=[filled, max(empty,0.1)])
        bar.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(0,0), color),
            ('BACKGROUND',(1,0),(1,0), BORDER),
            ('ROWHEIGHT',(0,0),(-1,-1), 7),
            ('PADDING',(0,0),(-1,-1), 0),
        ]))
        return bar

    def area_row(label, pct):
        c = GREEN if pct >= 75 else YELLOW if pct >= 50 else RED
        bg = GREEN_BG if pct >= 75 else YEL_BG if pct >= 50 else RED_BG
        txt_c = GREEN_TXT if pct >= 75 else YEL_TXT if pct >= 50 else RED_TXT
        bar_w = 10*cm
        filled = max(0.5, min(pct/100,1)) * bar_w
        empty  = bar_w - filled
        bar = Table([['','']], colWidths=[filled, max(empty,0.1)])
        bar.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(0,0), c),
            ('BACKGROUND',(1,0),(1,0), BORDER),
            ('ROWHEIGHT',(0,0),(-1,-1), 8),
            ('PADDING',(0,0),(-1,-1), 0),
        ]))
        pct_p = Paragraph(f'{pct}%', S('pp', fontName='Helvetica-Bold', fontSize=8, textColor=txt_c))
        lbl_p = Paragraph(label, S('lp', fontName='Helvetica', fontSize=8, textColor=DARK3))
        row = Table([[lbl_p, bar, pct_p]], colWidths=[4.5*cm, bar_w, 1.5*cm])
        row.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('PADDING',(0,0),(-1,-1), 0),
            ('RIGHTPADDING',(0,0),(0,0), 8),
            ('LEFTPADDING',(2,0),(2,0), 8),
            ('BACKGROUND',(0,0),(-1,-1), bg),
            ('TOPPADDING',(0,0),(-1,-1), 5),
            ('BOTTOMPADDING',(0,0),(-1,-1), 5),
            ('LEFTPADDING',(0,0),(0,0), 8),
        ]))
        return row

    def stat_box(num, label, color=DARK):
        t = Table([
            [Paragraph(str(num), S('sn', fontName='Helvetica-Bold', fontSize=20, textColor=color, alignment=TA_CENTER))],
            [Paragraph(label,    S('sl', fontName='Helvetica',      fontSize=7,  textColor=GRAY,  alignment=TA_CENTER))]
        ], colWidths=[3*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), LIGHT2),
            ('BOX',(0,0),(-1,-1), 0.5, BORDER),
            ('PADDING',(0,0),(-1,-1), 6),
            ('TOPPADDING',(0,0),(-1,0), 10),
        ]))
        return t

    # ── Footer canvas con paginación ──────────────────────────
    class FooterCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            pdfcanvas.Canvas.__init__(self, *args, **kwargs)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for i, state in enumerate(self._saved):
                self.__dict__.update(state)
                if i > 0:
                    self.setFont('Helvetica', 7)
                    self.setFillColor(LGRAY)
                    self.drawString(2*cm, 1.2*cm, 'SEO Analyzer · Alberto Labarta Holgado · github.com/Albertini97')
                    self.drawRightString(PAGE_W-2*cm, 1.2*cm, f'Pagina {i} de {total-1}')
                    self.setStrokeColor(BORDER)
                    self.setLineWidth(0.5)
                    self.line(2*cm, 1.5*cm, PAGE_W-2*cm, 1.5*cm)
                pdfcanvas.Canvas.showPage(self)
            pdfcanvas.Canvas.save(self)

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=0, bottomMargin=2.5*cm,
        title=f'SEO Report - {domain}',
        author='Alberto Labarta Holgado')

    story = []

    # ══════════════════════════════════════════════════════════
    # PORTADA
    # ══════════════════════════════════════════════════════════
    # Cabecera oscura
    cover_top = Table([[
        Paragraph('SEO ANALYZER', S('logo', fontName='Helvetica-Bold', fontSize=9, textColor=GREEN, spaceAfter=0)),
        Paragraph(now, S('date', fontName='Helvetica', fontSize=8, textColor=LGRAY, alignment=TA_RIGHT))
    ]], colWidths=[8.5*cm, 8.5*cm])
    cover_top.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), DARK),
        ('PADDING',(0,0),(-1,-1), 14),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
    ]))

    # Bloque hero portada
    hero = Table([[
        Paragraph('Informe de<br/>Auditoria SEO', s_cover_h),
    ]], colWidths=[17*cm])
    hero.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), DARK2),
        ('PADDING',(0,0),(-1,-1), 28),
        ('BOTTOMPADDING',(0,0),(-1,-1), 20),
    ]))

    # Dominio y URL
    domain_block = Table([[
        Paragraph(domain, S('db', fontName='Helvetica-Bold', fontSize=16, textColor=DARK, spaceAfter=4)),
    ],[
        Paragraph(clean(d['url'][:90]) + ('...' if len(d['url'])>90 else ''), S('ub', fontName='Courier', fontSize=7, textColor=GRAY)),
    ]], colWidths=[17*cm])
    domain_block.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), LIGHT),
        ('PADDING',(0,0),(-1,-1), 16),
        ('LINEBELOW',(0,-1),(-1,-1), 2, GREEN),
    ]))

    story.append(cover_top)
    story.append(hero)
    story.append(domain_block)
    story.append(Spacer(1, 0.6*cm))

    # Score grande centrado
    score_big = Table([[
        Table([[
            Paragraph(str(d['score']), S('sc', fontName='Helvetica-Bold', fontSize=64, textColor=score_color, leading=64, alignment=TA_CENTER)),
            Paragraph('/ 100', S('sc2', fontName='Helvetica', fontSize=12, textColor=LGRAY, alignment=TA_CENTER)),
            Paragraph(score_label, S('sl2', fontName='Helvetica-Bold', fontSize=14, textColor=score_color, alignment=TA_CENTER)),
        ]], colWidths=[8*cm]),
        Table([[
            Paragraph('PENALIZACIONES', S('ped', fontName='Helvetica-Bold', fontSize=8, textColor=RED_TXT, spaceAfter=8)),
        ]] + ([[Paragraph(f'  - {clean(x)}', S('pi', fontName='Helvetica', fontSize=8, textColor=RED_TXT, spaceAfter=3))] for x in d['deductions']] if d['deductions'] else [[Paragraph('Sin penalizaciones detectadas', S('np', fontName='Helvetica', fontSize=8, textColor=GREEN_TXT))]]), colWidths=[9*cm]),
    ]], colWidths=[8*cm, 9*cm])
    score_big.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BACKGROUND',(0,0),(0,0), score_bg),
        ('BACKGROUND',(1,0),(1,0), RED_BG if d['deductions'] else GREEN_BG),
        ('BOX',(0,0),(0,0), 1.5, score_color),
        ('BOX',(1,0),(1,0), 0.5, BORDER),
        ('PADDING',(0,0),(0,0), 16),
        ('PADDING',(1,0),(1,0), 14),
    ]))
    story.append(score_big)
    story.append(Spacer(1, 0.6*cm))

    # Info pie portada
    story.append(Table([[
        Paragraph('Alberto Labarta Holgado  ·  Full Stack Developer & SEO Specialist', S('ai', fontName='Helvetica', fontSize=8, textColor=LGRAY)),
        Paragraph('github.com/Albertini97  ·  soyalbertolabartaholgado@gmail.com', S('ai2', fontName='Helvetica', fontSize=8, textColor=LGRAY, alignment=TA_RIGHT)),
    ]], colWidths=[8.5*cm, 8.5*cm]))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════
    # RESUMEN EJECUTIVO
    # ══════════════════════════════════════════════════════════
    story.append(section_header('  Resumen ejecutivo'))
    story.append(Spacer(1, 0.4*cm))

    positives, issues_found = [], []

    if not d['title']['text']:
        issues_found.append('La pagina no tiene etiqueta titulo.')
    elif d['title']['length'] < 30 or d['title']['length'] > 60:
        issues_found.append(f'El titulo tiene {d["title"]["length"]} caracteres, fuera del rango optimo (30-60).')
    else:
        positives.append('El titulo tiene una longitud optima.')

    if not d['meta_description']['text']:
        issues_found.append('No hay meta description definida.')
    elif d['meta_description']['length'] < 70 or d['meta_description']['length'] > 160:
        issues_found.append(f'La meta description tiene {d["meta_description"]["length"]} caracteres, fuera del rango optimo (70-160).')
    else:
        positives.append('La meta description tiene longitud correcta.')

    h1s = d['headings']['headings']['h1']
    if not h1s:
        issues_found.append('No hay H1. Es uno de los factores SEO on-page mas importantes.')
    elif len(h1s) > 1:
        issues_found.append(f'Hay {len(h1s)} H1. Se recomienda usar solo uno.')
    else:
        positives.append('La estructura de H1 es correcta.')

    if not d['technical']['canonical']:
        issues_found.append('Falta la URL canonica (rel=canonical).')
    else:
        positives.append('La URL canonica esta correctamente definida.')

    if not d['technical']['https']:
        issues_found.append('La pagina no usa HTTPS.')
    else:
        positives.append('La pagina usa HTTPS correctamente.')

    if d['images']['without_alt'] > 0:
        issues_found.append(f'{d["images"]["without_alt"]} imagen(es) sin atributo alt.')

    lt = d['performance']['load_time']
    if lt > 4:
        issues_found.append(f'Tiempo de respuesta del servidor: {lt}s (demasiado alto).')
    elif lt < 1.5:
        positives.append(f'Excelente tiempo de respuesta: {lt}s.')

    # Dos columnas positivos / mejoras
    def bullet_table(items, bg, txt_color, prefix):
        if not items:
            return Spacer(1, 0.1*cm)
        rows = [[Paragraph(f'{prefix}  {i}', S('br', fontName='Helvetica', fontSize=8, textColor=txt_color, leading=12))] for i in items]
        t = Table(rows, colWidths=[7.8*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), bg),
            ('LEFTPADDING',(0,0),(-1,-1), 10),
            ('PADDING',(0,0),(-1,-1), 5),
            ('BOX',(0,0),(-1,-1), 0.5, txt_color),
            ('ROWBACKGROUNDS',(0,0),(-1,-1), [bg, colors.HexColor(bg.hexval()[:-2] + 'ee')]),
        ]))
        return t

    pos_title = Paragraph('Puntos fuertes', S('pt', fontName='Helvetica-Bold', fontSize=9, textColor=GREEN_TXT, spaceAfter=5))
    iss_title = Paragraph('A mejorar', S('it', fontName='Helvetica-Bold', fontSize=9, textColor=RED_TXT, spaceAfter=5))
    two = Table([[
        [pos_title, bullet_table(positives, GREEN_BG, GREEN_TXT, '+')],
        [iss_title, bullet_table(issues_found, RED_BG, RED_TXT, '-')]
    ]], colWidths=[8.5*cm, 8.5*cm])
    two.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('RIGHTPADDING',(0,0),(0,-1),10)]))
    story.append(two)
    story.append(Spacer(1, 0.5*cm))

    # Barras por area
    story.append(Paragraph('Puntuacion por areas', S('pa', fontName='Helvetica-Bold', fontSize=10, textColor=DARK, spaceAfter=8)))

    def area_score(issues_list):
        ok = sum(1 for i in issues_list if '✅' in i)
        return int((ok / len(issues_list)) * 100) if issues_list else 50

    areas = [
        ('Titulo y meta tags',      area_score(d['title']['issues'] + d['meta_description']['issues'])),
        ('Estructura de headings',  area_score(d['headings']['issues'])),
        ('SEO tecnico',             area_score(d['technical']['issues'])),
        ('Imagenes y accesibilidad',area_score(d['images']['issues'])),
        ('Performance',             area_score(d['performance']['issues'])),
    ]
    for label, pct in areas:
        story.append(area_row(label, pct))
        story.append(Spacer(1, 3))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════
    # ANALISIS DETALLADO
    # ══════════════════════════════════════════════════════════
    story.append(section_header('  Analisis detallado', DARK2))
    story.append(Spacer(1, 0.4*cm))

    def detail_section(icon_label, issues, value=None, accent=DARK):
        hdr = Table([[Paragraph(icon_label, S('dh', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE))]],
                    colWidths=[17*cm])
        hdr.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),accent),('PADDING',(0,0),(-1,-1),7)]))
        items = [hdr]
        if value is not None:
            v = clean(value) if value else '(sin valor)'
            items.append(Paragraph(v, s_mono))
        for i in issues:
            items.append(issue_para(i))
        items.append(Spacer(1, 0.3*cm))
        story.append(KeepTogether(items))

    detail_section('TITULO DE PAGINA', d['title']['issues'], d['title']['text'], DARK3)
    detail_section('META DESCRIPTION', d['meta_description']['issues'], d['meta_description']['text'], DARK3)

    # Headings con tabla visual
    hdr_h = Table([[Paragraph('ESTRUCTURA DE HEADINGS', S('hh', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE))]],
                   colWidths=[17*cm])
    hdr_h.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),DARK3),('PADDING',(0,0),(-1,-1),7)]))
    story.append(hdr_h)
    hd = d['headings']['headings']
    h_header = [Paragraph(f'H{i}  ({len(hd[f"h{i}"])})', S('hth', fontName='Helvetica-Bold', fontSize=7, textColor=WHITE, alignment=TA_CENTER)) for i in range(1,7)]
    h_data = [h_header]
    max_r = min(max(len(hd[f'h{i}']) for i in range(1,7)), 4) or 1
    for r in range(max_r):
        row = []
        for i in range(1,7):
            items2 = hd[f'h{i}']
            txt = clean(items2[r][:30]) if r < len(items2) else '-'
            row.append(Paragraph(txt, S('hc', fontName='Helvetica', fontSize=7, textColor=DARK3)))
        h_data.append(row)
    h_table = Table(h_data, colWidths=[2.83*cm]*6)
    h_table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0), DARK2),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [LIGHT, WHITE]),
        ('GRID',(0,0),(-1,-1), 0.5, BORDER),
        ('PADDING',(0,0),(-1,-1), 6),
        ('FONTSIZE',(0,0),(-1,-1), 7),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
    ]))
    story.append(h_table)
    for i in d['headings']['issues']:
        story.append(issue_para(i))
    story.append(Spacer(1, 0.4*cm))

    # Imágenes + Links con stat boxes
    hdr_il = Table([[Paragraph('IMAGENES Y ENLAZADO', S('il', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE))]],
                    colWidths=[17*cm])
    hdr_il.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),DARK3),('PADDING',(0,0),(-1,-1),7)]))
    story.append(hdr_il)

    img_c = RED if d['images']['without_alt'] > 0 else (YELLOW if d['images']['empty_alt'] > 0 else GREEN)
    img_stats = Table([[
        stat_box(d['images']['total'],       'Total imagenes'),
        stat_box(d['images']['without_alt'], 'Sin alt', RED if d['images']['without_alt']>0 else GREEN),
        stat_box(d['images']['empty_alt'],   'Alt vacio', YELLOW if d['images']['empty_alt']>0 else GREEN),
    ]], colWidths=[3*cm, 3*cm, 3*cm])
    img_stats.setStyle(TableStyle([('PADDING',(0,0),(-1,-1),3)]))

    lnk_stats = Table([[
        stat_box(d['links']['internal_count'], 'Internos'),
        stat_box(d['links']['external_count'], 'Externos'),
        stat_box(d['links']['nofollow_count'], 'Nofollow'),
    ]], colWidths=[2.5*cm, 2.5*cm, 2.5*cm])
    lnk_stats.setStyle(TableStyle([('PADDING',(0,0),(-1,-1),3)]))

    il_issues_img = [issue_para(i) for i in d['images']['issues']]
    il_issues_lnk = [issue_para(i) for i in d['links']['issues']]

    il_table = Table([[
        [img_stats, Spacer(1,4)] + il_issues_img,
        [lnk_stats, Spacer(1,4)] + il_issues_lnk,
    ]], colWidths=[8.5*cm, 8.5*cm])
    il_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('RIGHTPADDING',(0,0),(0,-1),10)]))
    story.append(il_table)
    story.append(Spacer(1, 0.4*cm))

    detail_section('SEO TECNICO', d['technical']['issues'], accent=DARK3)

    # Performance con barras
    hdr_p = Table([[Paragraph('PERFORMANCE DEL SERVIDOR', S('ph', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE))]],
                   colWidths=[17*cm])
    hdr_p.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),DARK3),('PADDING',(0,0),(-1,-1),7)]))
    story.append(hdr_p)

    lt = d['performance']['load_time']
    sz = d['performance']['size_kb']
    lt_c = GREEN if lt<1.5 else YELLOW if lt<3 else RED
    sz_c = GREEN if sz<200 else YELLOW if sz<500 else RED
    lt_pct = max(0, min(100, int((1-lt/6)*100)))
    sz_pct = max(0, min(100, int((1-sz/2000)*100)))

    for label, pct, c in [(f'Tiempo de respuesta: {lt}s', lt_pct, lt_c),(f'Tamano HTML: {sz} KB', sz_pct, sz_c)]:
        bg = GREEN_BG if c==GREEN else YEL_BG if c==YELLOW else RED_BG
        txt_c2 = GREEN_TXT if c==GREEN else YEL_TXT if c==YELLOW else RED_TXT
        bar_w = 11*cm
        filled = max(0.5, min(pct/100,1))*bar_w
        empty  = bar_w - filled
        bar = Table([['','']], colWidths=[filled, max(empty,0.1)])
        bar.setStyle(TableStyle([('BACKGROUND',(0,0),(0,0),c),('BACKGROUND',(1,0),(1,0),BORDER),('ROWHEIGHT',(0,0),(-1,-1),8),('PADDING',(0,0),(-1,-1),0)]))
        row = Table([[Paragraph(label, S('pl', fontName='Helvetica', fontSize=8, textColor=txt_c2)), bar, Paragraph(f'{pct}%', S('pp2', fontName='Helvetica-Bold', fontSize=8, textColor=txt_c2))]],
                    colWidths=[4.5*cm, bar_w, 1.5*cm])
        row.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BACKGROUND',(0,0),(-1,-1),bg),('PADDING',(0,0),(-1,-1),6),('LEFTPADDING',(0,0),(0,0),8),('LEFTPADDING',(2,0),(2,0),8)]))
        story.append(row)
        story.append(Spacer(1,3))
    for i in d['performance']['issues']:
        story.append(issue_para(i))
    story.append(Spacer(1, 0.4*cm))

    # Open Graph
    hdr_og = Table([[Paragraph('OPEN GRAPH Y SOCIAL', S('ogh', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE))]],
                    colWidths=[17*cm])
    hdr_og.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),DARK3),('PADDING',(0,0),(-1,-1),7)]))
    story.append(hdr_og)
    og = d['open_graph']['og']
    if og:
        og_rows = [[
            Paragraph(k, S('ok2', fontName='Helvetica-Bold', fontSize=7, textColor=GREEN)),
            Paragraph(clean(v[:85]), S('ov', fontName='Helvetica', fontSize=7, textColor=DARK3))
        ] for k,v in list(og.items())[:8]]
        og_t = Table(og_rows, colWidths=[4*cm, 13*cm])
        og_t.setStyle(TableStyle([
            ('ROWBACKGROUNDS',(0,0),(-1,-1),[LIGHT, WHITE]),
            ('GRID',(0,0),(-1,-1), 0.5, BORDER),
            ('PADDING',(0,0),(-1,-1), 5),
            ('LINEAFTER',(0,0),(0,-1), 1, GREEN),
        ]))
        story.append(og_t)
        story.append(Spacer(1, 0.3*cm))
    for i in d['open_graph']['issues']:
        story.append(issue_para(i))

    # PageSpeed
    ps = d.get('pagespeed', {})
    if ps.get('available') and ps.get('performance_score', 0) > 0:
        story.append(Spacer(1, 0.4*cm))
        hdr_ps = Table([[Paragraph('CORE WEB VITALS - GOOGLE PAGESPEED (MOVIL)', S('psh', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE))]],
                        colWidths=[17*cm])
        hdr_ps.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),BLUE),('PADDING',(0,0),(-1,-1),7)]))
        story.append(hdr_ps)

        def ps_score_color(v):
            return GREEN if int(v)>=80 else YELLOW if int(v)>=50 else RED

        cwv_header = [Paragraph(h, S('ch2', fontName='Helvetica-Bold', fontSize=7, textColor=WHITE, alignment=TA_CENTER))
                      for h in ['Performance','SEO Score','Accesibilidad','LCP','TBT','CLS']]
        cwv_vals   = [
            Paragraph(str(ps['performance_score']),  S('cv', fontName='Helvetica-Bold', fontSize=12, textColor=ps_score_color(ps['performance_score']),  alignment=TA_CENTER)),
            Paragraph(str(ps['seo_score']),           S('cv', fontName='Helvetica-Bold', fontSize=12, textColor=ps_score_color(ps['seo_score']),           alignment=TA_CENTER)),
            Paragraph(str(ps['accessibility_score']),S('cv', fontName='Helvetica-Bold', fontSize=12, textColor=ps_score_color(ps['accessibility_score']), alignment=TA_CENTER)),
            Paragraph(clean(ps['lcp']), S('cv2', fontName='Helvetica-Bold', fontSize=12, textColor=DARK, alignment=TA_CENTER)),
            Paragraph(clean(ps['tbt']), S('cv2', fontName='Helvetica-Bold', fontSize=12, textColor=DARK, alignment=TA_CENTER)),
            Paragraph(clean(ps['cls']), S('cv2', fontName='Helvetica-Bold', fontSize=12, textColor=DARK, alignment=TA_CENTER)),
        ]
        cwv_t = Table([cwv_header, cwv_vals], colWidths=[2.83*cm]*6)
        cwv_t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), DARK2),
            ('BACKGROUND',(0,1),(-1,1), LIGHT),
            ('GRID',(0,0),(-1,-1), 0.5, BORDER),
            ('PADDING',(0,0),(-1,-1), 10),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        story.append(cwv_t)
    elif ps.get('available'):
        story.append(Spacer(1,0.3*cm))
        story.append(Paragraph('[i] Core Web Vitals no disponibles: limite de la API de Google alcanzado. Activa una API key gratuita en console.cloud.google.com para obtener datos reales.', s_info))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width='100%', thickness=1, color=GREEN))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph('SEO Analyzer  ·  Alberto Labarta Holgado  ·  github.com/Albertini97  ·  soyalbertolabartaholgado@gmail.com', s_footer))

    doc.build(story, canvasmaker=FooterCanvas)
    buf.seek(0)
    return buf.read()
    from reportlab.platypus import PageBreak, KeepTogether
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas

    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4

    GREEN  = colors.HexColor('#00C48C')
    RED    = colors.HexColor('#EF4444')
    YELLOW = colors.HexColor('#F59E0B')
    DARK   = colors.HexColor('#0D1017')
    DARK2  = colors.HexColor('#1E2433')
    GRAY   = colors.HexColor('#6B7A94')
    LGRAY  = colors.HexColor('#9CA3AF')
    LIGHT  = colors.HexColor('#F3F4F6')
    WHITE  = colors.white
    BORDER = colors.HexColor('#E5E7EB')

    score_color = GREEN if d['score'] >= 80 else YELLOW if d['score'] >= 60 else RED
    score_label = 'Buen SEO' if d['score'] >= 80 else 'SEO mejorable' if d['score'] >= 60 else 'SEO deficiente'
    now = datetime.now().strftime("%d/%m/%Y a las %H:%M")
    domain = urlparse(d['url']).netloc

    # ── Styles ──────────────────────────────────────────────────
    cover_title  = ParagraphStyle('ct',  fontName='Helvetica-Bold', fontSize=32, textColor=WHITE,   leading=36, spaceAfter=8)
    cover_sub    = ParagraphStyle('cs',  fontName='Helvetica',      fontSize=11, textColor=LGRAY,   leading=16, spaceAfter=4)
    cover_url    = ParagraphStyle('cu',  fontName='Courier-Bold',   fontSize=10, textColor=GREEN,   spaceAfter=4)
    cover_date   = ParagraphStyle('cd',  fontName='Helvetica',      fontSize=9,  textColor=LGRAY)
    h1_style     = ParagraphStyle('h1',  fontName='Helvetica-Bold', fontSize=13, textColor=DARK,    spaceBefore=14, spaceAfter=5)
    h2_style     = ParagraphStyle('h2',  fontName='Helvetica-Bold', fontSize=10, textColor=DARK,    spaceBefore=8,  spaceAfter=3)
    body_style   = ParagraphStyle('bd',  fontName='Helvetica',      fontSize=8,  textColor=colors.HexColor('#374151'), leading=12, spaceAfter=2)
    mono_style   = ParagraphStyle('mn',  fontName='Courier',        fontSize=8,  textColor=DARK,    backColor=LIGHT, leading=12, spaceAfter=4, leftIndent=6, rightIndent=6)
    issue_ok     = ParagraphStyle('iok', fontName='Helvetica',      fontSize=8,  textColor=colors.HexColor('#065F46'), leading=12, spaceAfter=2)
    issue_warn   = ParagraphStyle('iw',  fontName='Helvetica',      fontSize=8,  textColor=colors.HexColor('#92400E'), leading=12, spaceAfter=2)
    issue_err    = ParagraphStyle('ie',  fontName='Helvetica',      fontSize=8,  textColor=colors.HexColor('#991B1B'), leading=12, spaceAfter=2)
    issue_info   = ParagraphStyle('ii',  fontName='Helvetica',      fontSize=8,  textColor=GRAY,    leading=12, spaceAfter=2)
    footer_style = ParagraphStyle('ft',  fontName='Helvetica',      fontSize=7,  textColor=LGRAY,   alignment=TA_CENTER)
    label_style  = ParagraphStyle('lb',  fontName='Helvetica-Bold', fontSize=7,  textColor=GRAY,    spaceAfter=1)
    val_style    = ParagraphStyle('vl',  fontName='Helvetica-Bold', fontSize=18, textColor=DARK,    leading=20)

    def issue_para(text):
        t = text.strip()
        if t.startswith('[OK]') or t.startswith('OK'):
            st = issue_ok
        elif t.startswith('[!]') or t.startswith('AVISO') or t.startswith('WARN'):
            st = issue_warn
        elif t.startswith('[X]') or t.startswith('ERROR'):
            st = issue_err
        else:
            st = issue_info
        # limpia emojis básicos y los reemplaza por texto
        replacements = [
            ('✅','[OK]'),('⚠️','[!]'),('❌','[X]'),('ℹ️','[i]'),
            ('🔍',''),('📝',''),('📄',''),('🏗️',''),('🖼️',''),
            ('🔗',''),('🔧',''),('⚡',''),('📱',''),('→','->'),
        ]
        for emoji, txt in replacements:
            t = t.replace(emoji, txt)
        if '[OK]' in t: st = issue_ok
        elif '[!]' in t: st = issue_warn
        elif '[X]' in t: st = issue_err
        return Paragraph(t, st)

    def clean(text):
        replacements = [
            ('✅','[OK]'),('⚠️','[!]'),('❌','[X]'),('ℹ️','[i]'),
            ('🔍','SEO'),('📝',''),('📄',''),('🏗️',''),('🖼️',''),
            ('🔗',''),('🔧',''),('⚡',''),('📱',''),
        ]
        for e, r in replacements:
            text = text.replace(e, r)
        return text.strip()

    def bar_table(label, value_pct, color, width=17*cm):
        bar_w = width
        filled = max(0.01, min(value_pct/100, 1)) * bar_w
        empty  = bar_w - filled
        data = [[
            Paragraph(label, label_style),
            Paragraph(f'{value_pct}%' if value_pct <= 100 else label, label_style)
        ]]
        t = Table(data, colWidths=[bar_w*0.7, bar_w*0.3])
        t.setStyle(TableStyle([
            ('ALIGN',(1,0),(1,0),'RIGHT'),
            ('PADDING',(0,0),(-1,-1),0),
            ('BOTTOMPADDING',(0,0),(-1,-1),2),
        ]))
        bar_data = [['','']]
        bar = Table(bar_data, colWidths=[filled, max(empty,0.1)])
        bar.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(0,0),color),
            ('BACKGROUND',(1,0),(1,0),BORDER),
            ('ROWHEIGHT',(0,0),(-1,-1),6),
            ('PADDING',(0,0),(-1,-1),0),
        ]))
        wrapper = Table([[t],[bar]], colWidths=[bar_w])
        wrapper.setStyle(TableStyle([
            ('PADDING',(0,0),(-1,-1),0),
            ('BOTTOMPADDING',(0,0),(-1,-1),6),
        ]))
        return wrapper

    # ── Page template with footer ────────────────────────────────
    class FooterCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            pdfcanvas.Canvas.__init__(self, *args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for i, state in enumerate(self._saved_page_states):
                self.__dict__.update(state)
                if i > 0:  # skip cover
                    self.draw_footer(i, num_pages)
                self.canvas_showPage()
            pdfcanvas.Canvas.save(self)

        def canvas_showPage(self):
            pdfcanvas.Canvas.showPage(self)

        def draw_footer(self, page_num, total):
            self.saveState()
            self.setFont('Helvetica', 7)
            self.setFillColor(LGRAY)
            self.drawString(2*cm, 1.2*cm, f'SEO Analyzer · Alberto Labarta Holgado · github.com/Albertini97')
            self.drawRightString(PAGE_W - 2*cm, 1.2*cm, f'Pagina {page_num} de {total}')
            self.setStrokeColor(BORDER)
            self.setLineWidth(0.5)
            self.line(2*cm, 1.5*cm, PAGE_W - 2*cm, 1.5*cm)
            self.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2.5*cm,
        title=f'SEO Report - {domain}',
        author='Alberto Labarta Holgado'
    )

    story = []

    # ══════════════════════════════════════════════════════════════
    # PORTADA
    # ══════════════════════════════════════════════════════════════
    story.append(Spacer(1, 3*cm))

    # Fondo oscuro simulado con tabla
    cover_data = [[
        Paragraph('SEO Analyzer', ParagraphStyle('cta', fontName='Helvetica-Bold', fontSize=10, textColor=GREEN, spaceAfter=16)),
    ]]
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph('Informe de Auditoria SEO', cover_title))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(domain, cover_url))
    story.append(Paragraph(d['url'], ParagraphStyle('fullurl', fontName='Courier', fontSize=8, textColor=LGRAY, spaceAfter=12)))
    story.append(Spacer(1, 1*cm))

    # Score grande en portada
    sc_label_color = colors.HexColor('#065F46') if d['score'] >= 80 else colors.HexColor('#92400E') if d['score'] >= 60 else colors.HexColor('#991B1B')
    sc_bg = colors.HexColor('#ECFDF5') if d['score'] >= 80 else colors.HexColor('#FFFBEB') if d['score'] >= 60 else colors.HexColor('#FEF2F2')

    cover_score_data = [[
        Paragraph(str(d['score']), ParagraphStyle('csn', fontName='Helvetica-Bold', fontSize=72, textColor=score_color, leading=72)),
        [
            Paragraph('/ 100', ParagraphStyle('csub', fontName='Helvetica', fontSize=14, textColor=LGRAY, spaceAfter=6)),
            Paragraph(score_label, ParagraphStyle('csl', fontName='Helvetica-Bold', fontSize=16, textColor=score_color, spaceAfter=8)),
            Paragraph(f'Generado el {now}', ParagraphStyle('csd', fontName='Helvetica', fontSize=9, textColor=LGRAY)),
        ]
    ]]
    cover_score_table = Table(cover_score_data, colWidths=[5*cm, 12*cm])
    cover_score_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,-1), sc_bg),
        ('BOX', (0,0), (-1,-1), 2, score_color),
        ('LEFTPADDING', (0,0), (0,0), 20),
        ('PADDING', (1,0), (1,0), 16),
        ('LINEAFTER', (0,0), (0,0), 2, score_color),
    ]))
    story.append(cover_score_table)
    story.append(Spacer(1, 1.5*cm))

    # Penalizaciones en portada
    if d['deductions']:
        story.append(Paragraph('Penalizaciones detectadas', ParagraphStyle('ped', fontName='Helvetica-Bold', fontSize=9, textColor=RED, spaceAfter=6)))
        ded_rows = [[Paragraph(f'- {clean(x)}', ParagraphStyle('dr', fontName='Helvetica', fontSize=8, textColor=colors.HexColor('#991B1B')))] for x in d['deductions']]
        ded_table = Table(ded_rows, colWidths=[17*cm])
        ded_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FEF2F2')),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('PADDING', (0,0), (-1,-1), 4),
            ('BOX', (0,0), (-1,-1), 0.5, RED),
        ]))
        story.append(ded_table)

    story.append(Spacer(1, 2*cm))
    story.append(Paragraph('Alberto Labarta Holgado · Full Stack Developer & SEO Specialist', ParagraphStyle('auth', fontName='Helvetica', fontSize=8, textColor=LGRAY)))
    story.append(Paragraph('github.com/Albertini97 · soyalbertolabartaholgado@gmail.com', ParagraphStyle('auth2', fontName='Helvetica', fontSize=8, textColor=LGRAY)))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # RESUMEN EJECUTIVO
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph('Resumen ejecutivo', h1_style))
    story.append(HRFlowable(width='100%', thickness=1.5, color=GREEN, spaceAfter=10))

    # Genera resumen automático
    issues_found = []
    positives = []

    if not d['title']['text']:
        issues_found.append('La pagina no tiene etiqueta de titulo, lo que perjudica gravemente el posicionamiento.')
    elif d['title']['length'] < 30 or d['title']['length'] > 60:
        issues_found.append(f'El titulo tiene {d["title"]["length"]} caracteres, fuera del rango optimo (30-60). Ajustarlo puede mejorar el CTR en Google.')
    else:
        positives.append('El titulo tiene una longitud optima.')

    if not d['meta_description']['text']:
        issues_found.append('No hay meta description. Google puede generar una automatica, pero es mejor definirla para controlar como aparece en resultados.')
    elif d['meta_description']['length'] < 70 or d['meta_description']['length'] > 160:
        issues_found.append(f'La meta description tiene {d["meta_description"]["length"]} caracteres, fuera del rango optimo (70-160).')
    else:
        positives.append('La meta description tiene una longitud correcta.')

    h1s = d['headings']['headings']['h1']
    if not h1s:
        issues_found.append('No hay H1 en la pagina. Es uno de los factores SEO on-page mas importantes.')
    elif len(h1s) > 1:
        issues_found.append(f'Hay {len(h1s)} etiquetas H1. Se recomienda usar solo una por pagina.')
    else:
        positives.append('La estructura de H1 es correcta.')

    if not d['technical']['canonical']:
        issues_found.append('Falta la URL canonica (rel=canonical), lo que puede generar contenido duplicado.')
    else:
        positives.append('La URL canonica esta correctamente definida.')

    if not d['technical']['https']:
        issues_found.append('La pagina no usa HTTPS, lo que implica penalizacion en rankings y perdida de confianza del usuario.')
    else:
        positives.append('La pagina usa HTTPS correctamente.')

    if d['images']['without_alt'] > 0:
        issues_found.append(f'Hay {d["images"]["without_alt"]} imagen(es) sin atributo alt, lo que perjudica accesibilidad y SEO de imagenes.')

    if d['performance']['load_time'] > 4:
        issues_found.append(f'El tiempo de respuesta del servidor es {d["performance"]["load_time"]}s, demasiado alto. Afecta al ranking y a la experiencia de usuario.')
    elif d['performance']['load_time'] < 1.5:
        positives.append(f'Excelente tiempo de respuesta del servidor: {d["performance"]["load_time"]}s.')

    if positives:
        story.append(Paragraph('Puntos fuertes', ParagraphStyle('pf', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#065F46'), spaceAfter=5)))
        pos_rows = [[Paragraph(f'+ {p}', ParagraphStyle('pr', fontName='Helvetica', fontSize=8, textColor=colors.HexColor('#065F46')))] for p in positives]
        pos_table = Table(pos_rows, colWidths=[17*cm])
        pos_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ECFDF5')),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('PADDING', (0,0), (-1,-1), 4),
            ('BOX', (0,0), (-1,-1), 0.5, GREEN),
        ]))
        story.append(pos_table)
        story.append(Spacer(1, 0.4*cm))

    if issues_found:
        story.append(Paragraph('Puntos a mejorar', ParagraphStyle('pm', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#991B1B'), spaceAfter=5)))
        iss_rows = [[Paragraph(f'- {i}', ParagraphStyle('ir', fontName='Helvetica', fontSize=8, textColor=colors.HexColor('#991B1B')))] for i in issues_found]
        iss_table = Table(iss_rows, colWidths=[17*cm])
        iss_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FEF2F2')),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('PADDING', (0,0), (-1,-1), 4),
            ('BOX', (0,0), (-1,-1), 0.5, RED),
        ]))
        story.append(iss_table)

    story.append(Spacer(1, 0.5*cm))

    # Barras de puntuacion visual
    story.append(Paragraph('Puntuacion por areas', h2_style))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=8))

    def area_score(issues_list):
        ok = sum(1 for i in issues_list if '✅' in i or '[OK]' in i)
        total = len(issues_list)
        return int((ok / total) * 100) if total else 50

    areas = [
        ('Titulo y meta tags', area_score(d['title']['issues'] + d['meta_description']['issues']), GREEN),
        ('Estructura de headings', area_score(d['headings']['issues']), GREEN),
        ('SEO tecnico', area_score(d['technical']['issues']), GREEN),
        ('Imagenes', area_score(d['images']['issues']), GREEN),
        ('Performance', area_score(d['performance']['issues']), GREEN),
    ]
    for label, pct, color in areas:
        c = GREEN if pct >= 75 else YELLOW if pct >= 50 else RED
        story.append(bar_table(label, pct, c))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # ANALISIS DETALLADO
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph('Analisis detallado', h1_style))
    story.append(HRFlowable(width='100%', thickness=1.5, color=GREEN, spaceAfter=10))

    def section(title, issues, value=None):
        items = [
            HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=4),
            Paragraph(title, h2_style),
        ]
        if value is not None:
            v = clean(value) if value else '(sin valor)'
            items.append(Paragraph(v, mono_style))
        for i in issues:
            items.append(issue_para(i))
        items.append(Spacer(1, 0.3*cm))
        story.append(KeepTogether(items))

    section('Titulo de pagina', d['title']['issues'], d['title']['text'])
    section('Meta Description', d['meta_description']['issues'], d['meta_description']['text'])

    # Headings
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=4))
    story.append(Paragraph('Estructura de Headings', h2_style))
    hd = d['headings']['headings']
    h_data = [['H1','H2','H3','H4','H5','H6']]
    max_rows = min(max(len(hd[f'h{i}']) for i in range(1,7)), 5) or 1
    for r in range(max_rows):
        row = []
        for i in range(1,7):
            items = hd[f'h{i}']
            txt = clean(items[r][:35]) if r < len(items) else '-'
            row.append(Paragraph(txt, ParagraphStyle('hc', fontName='Helvetica', fontSize=7, textColor=colors.HexColor('#374151'))))
        h_data.append(row)
    h_table = Table(h_data, colWidths=[2.8*cm]*6)
    h_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), DARK),
        ('TEXTCOLOR', (0,0), (-1,0), GREEN),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 7),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [LIGHT, WHITE]),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(h_table)
    for i in d['headings']['issues']:
        story.append(issue_para(i))
    story.append(Spacer(1, 0.4*cm))

    # Imagenes + Links en 2 columnas
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=4))
    img_items = [Paragraph('Imagenes', h2_style)] + [issue_para(i) for i in d['images']['issues']]
    lnk_items = [Paragraph('Enlazado', h2_style)] + [issue_para(i) for i in d['links']['issues']]

    # Stats imagenes
    img_stats = Table(
        [[Paragraph(str(d['images']['total']), val_style), Paragraph(str(d['images']['without_alt']), ParagraphStyle('vs2', fontName='Helvetica-Bold', fontSize=18, textColor=RED if d['images']['without_alt']>0 else GREEN)), Paragraph(str(d['images']['empty_alt']), ParagraphStyle('vs3', fontName='Helvetica-Bold', fontSize=18, textColor=YELLOW if d['images']['empty_alt']>0 else GREEN))],
         [Paragraph('Total', label_style), Paragraph('Sin alt', label_style), Paragraph('Alt vacio', label_style)]],
        colWidths=[2.5*cm]*3
    )
    img_stats.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('PADDING',(0,0),(-1,-1),2)]))

    lnk_stats = Table(
        [[Paragraph(str(d['links']['internal_count']), val_style), Paragraph(str(d['links']['external_count']), val_style), Paragraph(str(d['links']['nofollow_count']), val_style)],
         [Paragraph('Internos', label_style), Paragraph('Externos', label_style), Paragraph('Nofollow', label_style)]],
        colWidths=[2.5*cm]*3
    )
    lnk_stats.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('PADDING',(0,0),(-1,-1),2)]))

    two_col = Table([[img_items + [img_stats], lnk_items + [lnk_stats]]], colWidths=[8.5*cm, 8.5*cm])
    two_col.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(0,-1),12)]))
    story.append(two_col)
    story.append(Spacer(1, 0.3*cm))

    section('SEO Tecnico', d['technical']['issues'])

    # Performance con barras
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=4))
    story.append(Paragraph('Performance del servidor', h2_style))
    lt = d['performance']['load_time']
    sz = d['performance']['size_kb']
    lt_color = GREEN if lt < 1.5 else YELLOW if lt < 3 else RED
    sz_color = GREEN if sz < 200 else YELLOW if sz < 500 else RED
    lt_pct = max(0, min(100, int((1 - lt/6) * 100)))
    sz_pct = max(0, min(100, int((1 - sz/2000) * 100)))
    story.append(bar_table(f'Tiempo de respuesta: {lt}s', lt_pct, lt_color))
    story.append(bar_table(f'Tamano HTML: {sz} KB', sz_pct, sz_color))
    for i in d['performance']['issues']:
        story.append(issue_para(i))
    story.append(Spacer(1, 0.3*cm))

    # Open Graph
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=4))
    story.append(Paragraph('Open Graph y Social', h2_style))
    og = d['open_graph']['og']
    if og:
        og_rows = [
            [Paragraph(k, ParagraphStyle('ogk', fontName='Helvetica-Bold', fontSize=7, textColor=GREEN)),
             Paragraph(clean(v[:90]), ParagraphStyle('ogv', fontName='Helvetica', fontSize=7, textColor=colors.HexColor('#374151')))]
            for k,v in list(og.items())[:8]
        ]
        og_table = Table(og_rows, colWidths=[4*cm, 13*cm])
        og_table.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [LIGHT, WHITE]),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(og_table)
        story.append(Spacer(1, 0.3*cm))
    for i in d['open_graph']['issues']:
        story.append(issue_para(i))

    # PageSpeed
    ps = d.get('pagespeed', {})
    if ps.get('available') and ps.get('performance_score', 0) > 0:
        story.append(Spacer(1, 0.4*cm))
        story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=4))
        story.append(Paragraph('Core Web Vitals - Google PageSpeed (movil)', h2_style))
        cwv_data = [
            ['Performance', 'SEO Score', 'Accesibilidad', 'LCP', 'TBT', 'CLS'],
            [str(ps['performance_score']), str(ps['seo_score']), str(ps['accessibility_score']),
             clean(ps['lcp']), clean(ps['tbt']), clean(ps['cls'])]
        ]
        cwv_table = Table(cwv_data, colWidths=[2.8*cm]*6)
        cwv_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), DARK),
            ('TEXTCOLOR', (0,0), (-1,0), GREEN),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [LIGHT, WHITE]),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER),
            ('PADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(cwv_table)
    elif ps.get('available') and ps.get('performance_score', 0) == 0:
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph('[i] Core Web Vitals no disponibles: limite de la API de Google alcanzado. Activa una API key gratuita en console.cloud.google.com para obtener datos reales.', issue_info))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph('SEO Analyzer · Alberto Labarta Holgado · github.com/Albertini97 · soyalbertolabartaholgado@gmail.com', footer_style))

    doc.build(story, canvasmaker=FooterCanvas)
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
