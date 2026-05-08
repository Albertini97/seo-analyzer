# 🔍 SEO Analyzer

Herramienta web para analizar el SEO on-page de cualquier URL. Construida con **Python + Flask + BeautifulSoup** en el backend y **HTML/CSS/JS vanilla** en el frontend.

## ✨ Qué analiza

| Sección | Checks |
|---|---|
| **Título** | Existencia, longitud (30-60 chars) |
| **Meta Description** | Existencia, longitud (70-160 chars) |
| **Headings** | Estructura H1-H6, unicidad del H1 |
| **Imágenes** | Alt text ausente o vacío |
| **Performance** | Tiempo de carga, tamaño del HTML |
| **SEO Técnico** | Canonical, robots, viewport, lang, HTTPS |
| **Enlazado** | Links internos, externos, nofollow |
| **Open Graph** | og:title, og:description, og:image, og:url, Twitter Cards |
| **Puntuación** | Score 0-100 con desglose de penalizaciones |

## 🚀 Instalación y uso

```bash
# 1. Clona el repositorio
git clone https://github.com/Albertini97/seo-analyzer
cd seo-analyzer

# 2. Instala dependencias
pip install -r requirements.txt

# 3. Lanza el servidor
python app.py

# 4. Abre el navegador en
http://localhost:5050
```

## 🛠️ Stack

- **Backend:** Python · Flask · BeautifulSoup4 · Requests
- **Frontend:** HTML5 · CSS3 · JavaScript vanilla

## 📁 Estructura

```
seo-analyzer/
├── app.py              # Backend Flask + lógica de análisis
├── requirements.txt    # Dependencias Python
├── templates/
│   └── index.html      # Frontend completo
└── README.md
```

## 🔮 Próximas mejoras

- [ ] Exportar informe a PDF
- [ ] Comparar dos URLs
- [ ] Historial de análisis con base de datos
- [ ] API REST pública
- [ ] Deploy en Railway / Render

---

Construido por [Alberto Labarta](https://github.com/Albertini97) · Zaragoza, España 🇪🇸
