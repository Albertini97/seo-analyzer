from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from bs4 import BeautifulSoup
import requests
import time
import re
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SEOAnalyzer/1.0; +https://github.com/Albertini97)"
}

def fetch_page(url):
    start = time.time()
    resp = requests.get(url, headers=HEADERS, timeout=15)
    load_time = round(time.time() - start, 2)
    resp.raise_for_status()
    return resp.text, load_time, len(resp.content)

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
    without_alt = []
    empty_alt = []
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
    elif total == 0:
        issues.append("ℹ️ No se encontraron imágenes en la página")

    return {
        "total": total,
        "without_alt": len(without_alt),
        "empty_alt": len(empty_alt),
        "without_alt_srcs": without_alt[:5],
        "issues": issues
    }

def analyze_links(soup, base_url):
    links = soup.find_all("a", href=True)
    internal = []
    external = []
    nofollow = []
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

    issues = []
    issues.append(f"ℹ️ {len(internal)} enlaces internos · {len(external)} enlaces externos")
    if nofollow:
        issues.append(f"ℹ️ {len(nofollow)} enlace(s) con rel='nofollow'")

    return {
        "internal_count": len(internal),
        "external_count": len(external),
        "nofollow_count": len(nofollow),
        "internal": internal[:10],
        "external": external[:10],
        "issues": issues
    }

def analyze_technical(soup, url):
    issues = []

    # Canonical
    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href", "") if canonical else ""
    if not canonical_url:
        issues.append("⚠️ No tiene URL canónica (rel=canonical)")
    else:
        issues.append(f"✅ Canonical: {canonical_url[:60]}")

    # Robots meta
    robots = soup.find("meta", attrs={"name": re.compile("robots", re.I)})
    robots_content = robots.get("content", "") if robots else ""
    if "noindex" in robots_content.lower():
        issues.append("❌ La página tiene meta robots=noindex — Google no la indexará")
    elif robots_content:
        issues.append(f"✅ Meta robots: {robots_content}")
    else:
        issues.append("ℹ️ No tiene meta robots (se asume indexable)")

    # Viewport
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if not viewport:
        issues.append("❌ Sin meta viewport — puede no ser móvil-friendly")
    else:
        issues.append("✅ Meta viewport presente (móvil-friendly)")

    # Lang
    html_tag = soup.find("html")
    lang = html_tag.get("lang", "") if html_tag else ""
    if not lang:
        issues.append("⚠️ El atributo lang no está definido en <html>")
    else:
        issues.append(f"✅ Idioma declarado: {lang}")

    # HTTPS
    if url.startswith("https://"):
        issues.append("✅ Usa HTTPS")
    else:
        issues.append("❌ No usa HTTPS — penalización SEO y de seguridad")

    return {
        "canonical": canonical_url,
        "robots": robots_content,
        "viewport": bool(viewport),
        "lang": lang,
        "https": url.startswith("https://"),
        "issues": issues
    }

def analyze_opengraph(soup):
    og_tags = {}
    for tag in soup.find_all("meta", property=re.compile("^og:")):
        prop = tag.get("property", "")
        content = tag.get("content", "")
        og_tags[prop] = content

    twitter_tags = {}
    for tag in soup.find_all("meta", attrs={"name": re.compile("^twitter:")}):
        name = tag.get("name", "")
        content = tag.get("content", "")
        twitter_tags[name] = content

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
        issues.append(f"✅ Tiempo de carga: {load_time}s (excelente)")
    elif load_time < 2.5:
        issues.append(f"✅ Tiempo de carga: {load_time}s (bueno)")
    elif load_time < 4.0:
        issues.append(f"⚠️ Tiempo de carga: {load_time}s (mejorable, objetivo &lt;2.5s)")
    else:
        issues.append(f"❌ Tiempo de carga: {load_time}s (lento, objetivo &lt;2.5s)")

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

    # Title
    if not results["title"]["text"]:
        score -= 15; deductions.append("Sin título (-15)")
    elif results["title"]["length"] > 60 or results["title"]["length"] < 30:
        score -= 5; deductions.append("Título fuera de rango (-5)")

    # Meta desc
    if not results["meta_description"]["text"]:
        score -= 10; deductions.append("Sin meta description (-10)")
    elif results["meta_description"]["length"] > 160 or results["meta_description"]["length"] < 70:
        score -= 3; deductions.append("Meta description fuera de rango (-3)")

    # H1
    h1s = results["headings"]["headings"]["h1"]
    if not h1s:
        score -= 10; deductions.append("Sin H1 (-10)")
    elif len(h1s) > 1:
        score -= 5; deductions.append("Múltiples H1 (-5)")

    # Images
    if results["images"]["without_alt"] > 0:
        score -= min(results["images"]["without_alt"] * 2, 10)
        deductions.append(f"Imágenes sin alt (-{min(results['images']['without_alt']*2,10)})")

    # Technical
    if not results["technical"]["canonical"]:
        score -= 5; deductions.append("Sin canonical (-5)")
    if not results["technical"]["viewport"]:
        score -= 8; deductions.append("Sin viewport (-8)")
    if not results["technical"]["https"]:
        score -= 10; deductions.append("Sin HTTPS (-10)")
    if not results["technical"]["lang"]:
        score -= 3; deductions.append("Sin lang (-3)")

    # Open Graph
    essential_og = ["og:title", "og:description", "og:image", "og:url"]
    missing_og = [k for k in essential_og if k not in results["open_graph"]["og"]]
    if len(missing_og) >= 3:
        score -= 5; deductions.append("Open Graph incompleto (-5)")

    # Performance
    if results["performance"]["load_time"] > 4:
        score -= 8; deductions.append("Carga muy lenta (-8)")
    elif results["performance"]["load_time"] > 2.5:
        score -= 4; deductions.append("Carga lenta (-4)")

    return max(score, 0), deductions

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        html, load_time, page_size = fetch_page(url)
    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout: la página tardó demasiado en responder"}), 400
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
    }

    score, deductions = compute_score(results)
    results["score"] = score
    results["deductions"] = deductions

    return jsonify(results)

if __name__ == "__main__":
    app.run(debug=True, port=5050)
