from flask import Flask, render_template, request, jsonify
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
import re, io, os, json, hashlib

from PIL import Image, ImageOps
import pytesseract

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

USER_AGENT = "Mozilla/5.0 (compatible; IntegratedSiteContentAnalyzer/1.0)"
TIMEOUT = 15
MAX_PAGES = 40
MAX_IMAGES_PER_PAGE = 6
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# Optional vision provider configuration:
# OPENAI_API_KEY should be set in your environment, never hard-code it into this file.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini").strip()

KPOP_WOMEN_IDOLS = [
    "IU", "아이유", "태연", "Taeyeon", "윤아", "Yoona", "보아", "BoA", "현아", "HyunA",
    "선미", "Sunmi", "청하", "Chungha", "화사", "Hwasa", "솔라", "Solar", "문별", "Moonbyul",
    "휘인", "Wheein", "슬기", "Seulgi", "아이린", "Irene", "조이", "Joy", "웬디", "Wendy",
    "지수", "Jisoo", "제니", "Jennie", "로제", "Rosé", "Rose", "리사", "Lisa",
    "장원영", "Jang Wonyoung", "안유진", "An Yujin", "카리나", "Karina", "윈터", "Winter",
    "지젤", "Giselle", "닝닝", "Ningning", "민지", "Minji", "하니", "Hanni",
    "다니엘", "Danielle", "해린", "Haerin", "혜인", "Hyein", "나연", "Nayeon",
    "정연", "Jeongyeon", "모모", "Momo", "사나", "Sana", "지효", "Jihyo", "미나", "Mina",
    "다현", "Dahyun", "채영", "Chaeyoung", "쯔위", "Tzuyu", "미연", "Miyeon",
    "민니", "Minnie", "소연", "Soyeon", "우기", "Yuqi", "슈화", "Shuhua",
    "예지", "Yeji", "리아", "Lia", "류진", "Ryujin", "채령", "Chaeryeong", "유나", "Yuna",
    "사쿠라", "Sakura", "김채원", "Kim Chaewon", "허윤진", "Huh Yunjin",
    "카즈하", "Kazuha", "홍은채", "Hong Eunchae", "해원", "Haewon", "설윤", "Sullyoon",
    "키스오브라이프", "KISS OF LIFE", "스테이씨", "STAYC", "아이브", "IVE", "에스파", "aespa",
    "블랙핑크", "BLACKPINK", "뉴진스", "NewJeans", "트와이스", "TWICE", "레드벨벳", "Red Velvet",
    "르세라핌", "LE SSERAFIM", "엔믹스", "NMIXX", "있지", "ITZY", "(여자)아이들", "여자아이들",
    "i-dle", "오마이걸", "OH MY GIRL", "마마무", "MAMAMOO", "소녀시대", "Girls' Generation",
    "프로미스나인", "fromis_9", "케플러", "Kep1er", "베이비몬스터", "BABYMONSTER",
    "아일릿", "ILLIT", "하츠투하츠", "Hearts2Hearts", "피프티피프티", "FIFTY FIFTY"
]

def clean_text(s):
    return re.sub(r"\s+", " ", s or "").strip()

def parse_date(soup):
    values = []
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        if key in ("article:published_time", "datepublished", "date", "pubdate",
                   "og:updated_time", "article:modified_time") and tag.get("content"):
            values.append(tag["content"])
    for tag in soup.find_all("time"):
        value = tag.get("datetime") or tag.get_text(" ", strip=True)
        if value:
            values.append(value)
    for value in values:
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except (ValueError, TypeError):
            continue
    return None

def discover_links(url, soup, domain):
    links = []
    for a in soup.find_all("a", href=True):
        link = urljoin(url, a["href"].split("#")[0])
        parsed = urlparse(link)
        if parsed.scheme in ("http", "https") and parsed.netloc == domain and link not in links:
            if not any(link.lower().endswith(ext) for ext in (".pdf", ".zip", ".mp4", ".jpg", ".png", ".gif", ".webp")):
                links.append(link)
    return links

def detect_names(text, custom_keywords):
    haystack = (text or "").lower()
    found = [name for name in KPOP_WOMEN_IDOLS if name.lower() in haystack]
    for keyword in custom_keywords:
        if keyword.lower() in haystack and keyword not in found:
            found.append(keyword)
    return list(dict.fromkeys(found))

def image_to_data_url(image_bytes, content_type):
    import base64
    return f"data:{content_type};base64," + base64.b64encode(image_bytes).decode("ascii")

def analyze_image_with_openai(image_bytes, content_type):
    """Vision API analyzes general visual context. It must not identify a real person's identity from their face."""
    if not OPENAI_API_KEY:
        return {
            "status": "not_configured",
            "category": None,
            "description": None,
            "kpop_relevance": None,
            "reason": "OPENAI_API_KEY가 설정되지 않아 AI 이미지 분석을 건너뛰었습니다."
        }
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        data_url = image_to_data_url(image_bytes, content_type)
        prompt = (
            "Analyze this image for general visual content only. Do not identify, name, or verify the identity "
            "of any person shown. Return concise JSON with keys: category (one of: performance, photoshoot, "
            "airport_or_public_appearance, group_photo, portrait, poster_or_graphic, other), "
            "description (short neutral visual description), kpop_relevance (0 to 1 estimate of how much "
            "the visible context resembles K-pop entertainment content). This is a relevance estimate, not identity verification."
        )
        response = client.chat.completions.create(
            model=OPENAI_VISION_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "low"}}
                ]
            }]
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        score = parsed.get("kpop_relevance")
        try:
            score = max(0.0, min(1.0, float(score)))
        except (TypeError, ValueError):
            score = None
        return {
            "status": "ok",
            "category": str(parsed.get("category") or "other")[:80],
            "description": str(parsed.get("description") or "")[:500],
            "kpop_relevance": score,
            "reason": None
        }
    except Exception as exc:
        return {
            "status": "error",
            "category": None,
            "description": None,
            "kpop_relevance": None,
            "reason": "AI 이미지 분석에 실패했습니다: " + str(exc)[:250]
        }

def download_image(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True)
    r.raise_for_status()
    content_type = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        return None, None
    data = r.raw.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return None, None
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return None, None

def run_ocr(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1800, 1800))
        try:
            return clean_text(pytesseract.image_to_string(img, lang="kor+eng")), "ok"
        except Exception:
            return clean_text(pytesseract.image_to_string(img, lang="eng")), "english_only"
    except Exception:
        return "", "unavailable"

def fetch_page(url, custom_keywords, enable_ocr, enable_vision):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    response.raise_for_status()
    if "text/html" not in response.headers.get("Content-Type", "").lower():
        return None
    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    description = ""
    for meta in soup.find_all("meta"):
        if (meta.get("name") or "").lower() == "description":
            description = clean_text(meta.get("content", ""))
            break
    published_date = parse_date(soup)

    raw_images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        raw_images.append({
            "url": urljoin(response.url, src),
            "alt": clean_text(img.get("alt", "")),
            "filename": urlparse(src).path.rsplit("/", 1)[-1]
        })
        if len(raw_images) >= MAX_IMAGES_PER_PAGE:
            break

    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    body_text = clean_text(main.get_text(" ", strip=True))[:12000]

    image_results = []
    for item in raw_images:
        image_data, content_type = download_image(item["url"])
        ocr_text, ocr_status = ("", "disabled")
        vision = {"status": "disabled", "category": None, "description": None, "kpop_relevance": None, "reason": None}
        if image_data:
            if enable_ocr:
                ocr_text, ocr_status = run_ocr(image_data)
            if enable_vision:
                vision = analyze_image_with_openai(image_data, content_type)
        image_results.append({
            **item,
            "ocr_text": ocr_text,
            "ocr_status": ocr_status,
            "vision": vision
        })

    text_searchable = " ".join([title, description, body_text])
    image_text_searchable = " ".join(
        item["alt"] + " " + item["filename"] + " " + item["ocr_text"]
        for item in image_results
    )
    detected_text_names = detect_names(text_searchable, custom_keywords)
    detected_image_text_names = detect_names(image_text_searchable, custom_keywords)
    vision_scores = [
        item["vision"]["kpop_relevance"] for item in image_results
        if item.get("vision", {}).get("kpop_relevance") is not None
    ]
    max_vision_score = max(vision_scores) if vision_scores else None
    detected_names = list(dict.fromkeys(detected_text_names + detected_image_text_names))

    # Explainable blended relevance: textual matches plus vision-model context score.
    text_score = min(len(detected_text_names) / 5.0, 1.0)
    image_text_score = min(len(detected_image_text_names) / 5.0, 1.0)
    vision_score = max_vision_score if max_vision_score is not None else 0.0
    blended = round(0.45 * text_score + 0.20 * image_text_score + 0.35 * vision_score, 3)
    has_any_signal = bool(detected_names) or (max_vision_score is not None and max_vision_score >= 0.35)
    return {
        "url": response.url,
        "title": title or response.url,
        "description": description,
        "snippet": description or body_text[:300],
        "date": published_date,
        "images": image_results,
        "detected_names": detected_names,
        "text_matches": detected_text_names,
        "image_text_matches": detected_image_text_names,
        "max_vision_relevance": max_vision_score,
        "text_relevance": round(text_score, 3),
        "image_text_relevance": round(image_text_score, 3),
        "relevance_score": blended,
        "vision_enabled": enable_vision,
        "ocr_enabled": enable_ocr,
        "has_signal": has_any_signal
    }

@app.get("/")
def index():
    return render_template("index.html", idols=KPOP_WOMEN_IDOLS, vision_configured=bool(OPENAI_API_KEY))

@app.post("/api/analyze")
def analyze():
    data = request.get_json(silent=True) or {}
    site_url = (data.get("url") or "").strip()
    raw_keywords = data.get("keywords") or ""
    sort_mode = data.get("sort") or "relevance"
    enable_ocr = bool(data.get("ocr", True))
    enable_vision = bool(data.get("vision", True))
    custom_keywords = [x.strip() for x in re.split(r"[,，\n]", raw_keywords) if x.strip()]

    if not site_url:
        return jsonify({"error": "분석할 사이트 주소를 입력해 주세요."}), 400
    if not urlparse(site_url).scheme:
        site_url = "https://" + site_url
    parsed = urlparse(site_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify({"error": "올바른 웹사이트 주소를 입력해 주세요."}), 400

    try:
        response = requests.get(site_url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        response.raise_for_status()
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            return jsonify({"error": "HTML 웹페이지 주소를 입력해 주세요."}), 400
        response.encoding = response.apparent_encoding or response.encoding
        root_soup = BeautifulSoup(response.text, "html.parser")
        domain = urlparse(response.url).netloc
        urls = list(dict.fromkeys([response.url] + discover_links(response.url, root_soup, domain)))[:MAX_PAGES]

        results, seen = [], set()
        for page_url in urls:
            try:
                page = fetch_page(page_url, custom_keywords, enable_ocr, enable_vision)
                if not page or page["url"] in seen:
                    continue
                seen.add(page["url"])
                if page["has_signal"]:
                    results.append(page)
            except Exception:
                continue

        if sort_mode == "latest":
            results.sort(key=lambda x: x.get("date") or "", reverse=True)
        else:
            results.sort(key=lambda x: (x.get("relevance_score", 0), x.get("date") or ""), reverse=True)

        return jsonify({
            "site": response.url,
            "count": len(results),
            "results": results,
            "ocr_enabled": enable_ocr,
            "vision_enabled": enable_vision,
            "vision_configured": bool(OPENAI_API_KEY),
            "notice": (
                "AI 이미지 분석은 사진의 유형과 시각적 맥락을 평가합니다. 얼굴을 이용해 특정 인물의 신원을 확인하지 않습니다. "
                "관련성 점수는 추정치이며 신원 확인이나 사실 판정이 아닙니다."
            )
        })
    except requests.RequestException as exc:
        return jsonify({"error": "사이트에 접속하지 못했습니다. 주소와 사이트의 자동 수집 정책을 확인해 주세요.", "detail": str(exc)}), 502

if __name__ == "__main__":
    app.run(debug=True, port=5000)
