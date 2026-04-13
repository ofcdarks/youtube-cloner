"""
Mockup Routes — Channel Mockup generation, ImageFX, and PDF report.
Extracted from dashboard.py for modularity.
"""

import json
import logging
import os
import re

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from auth import require_admin
from config import OUTPUT_DIR
from rate_limit import limiter

logger = logging.getLogger("ytcloner.routes.mockup")

router = APIRouter(tags=["mockup"])


# ─── Channel Mockup (Modelar Canal) ─────────────────────────────────

@router.post("/api/admin/generate-channel-mockup")
@limiter.limit("5/minute")
async def api_generate_channel_mockup(request: Request, user=Depends(require_admin)):
    """
    Generate a complete channel identity mockup for a project's niche.
    Persists as a file with category='mockup' so the student can see it.
    """
    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    override_language = (body.get("language") or "").strip()
    # Admin overrides when regenerating — any of these may be empty
    override_niche = (body.get("niche") or "").strip()
    custom_channel_name = (body.get("custom_channel_name") or "").strip()
    custom_tagline = (body.get("custom_tagline") or "").strip()
    custom_description_hint = (body.get("custom_description_hint") or "").strip()
    custom_niche_angle = (body.get("custom_niche_angle") or "").strip()
    extra_instructions = (body.get("extra_instructions") or "").strip()
    reset_images = bool(body.get("reset_images"))
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_project, save_file, get_files, get_ideas
    from services import get_project_sop
    from protocols.channel_mockup import generate_channel_mockup
    import asyncio
    import json as _json

    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    niche_name = override_niche or proj.get("niche_chosen") or proj.get("name", "")
    language = override_language or (proj.get("language") or "pt-BR").strip()
    # Map our internal lang code to country (best-effort)
    country_map = {
        "pt-BR": "BR", "es": "ES", "en": "US", "fr": "FR", "de": "DE",
        "it": "IT", "ja": "JP", "ko": "KR", "zh": "CN", "ru": "RU",
        "ar": "SA", "hi": "IN", "tr": "TR", "nl": "NL",
    }
    country = country_map.get(language, "US")
    sop_excerpt = (get_project_sop(project_id) or "")[:3000]

    # Pull the top 4 SOP-generated titles from the project to seed the mockup
    seed_titles: list[str] = []
    try:
        ideas = get_ideas(project_id) or []
        # Prefer scored ideas first, then fall back to creation order
        ideas_sorted = sorted(ideas, key=lambda i: -(i.get("score") or 0))
        for it in ideas_sorted[:4]:
            t = (it.get("title") or "").strip()
            if t:
                seed_titles.append(t)
    except Exception as e:
        logger.warning(f"generate-channel-mockup: failed to fetch seed titles: {e}")

    try:
        mockup = await asyncio.to_thread(
            generate_channel_mockup,
            niche_name,
            sop_excerpt,
            language,
            country,
            "faceless",
            seed_titles,
            custom_channel_name,
            custom_tagline,
            custom_description_hint,
            custom_niche_angle,
            extra_instructions,
        )
    except Exception as e:
        logger.exception(f"generate-channel-mockup error: {e}")
        return JSONResponse({"error": f"Falha ao gerar mockup: {str(e)[:200]}"}, status_code=500)

    # Persist as a file (overwrite previous mockup if any). By default we keep
    # previously generated images so they survive a "regenerate identity", but
    # when the admin explicitly asks to reset them (reset_images=true) we drop
    # them so the new identity gets a fresh set of logo/banner/thumbs.
    try:
        existing = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
        if existing:
            from database import get_db
            if not reset_images:
                try:
                    prev = _json.loads(existing[0].get("content", "") or "{}")
                    prev_images = prev.get("images") or {}
                    if prev_images:
                        mockup["images"] = prev_images
                except Exception:
                    pass
            with get_db() as conn:
                for f in existing:
                    conn.execute("DELETE FROM files WHERE id=?", (f["id"],))
        save_file(
            project_id,
            "mockup",
            f"Mockup do Canal - {niche_name}",
            f"channel_mockup_{project_id}.json",
            _json.dumps(mockup, ensure_ascii=False, indent=2),
            visible_to_students=True,
        )
    except Exception as e:
        logger.warning(f"generate-channel-mockup: failed to persist file: {e}")

    return JSONResponse({"ok": True, "mockup": mockup})


@router.get("/api/admin/get-channel-mockup")
async def api_get_channel_mockup(request: Request, user=Depends(require_admin), project_id: str = ""):
    """Return the saved mockup for a project, or null if none exists yet."""
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)
    from database import get_files
    import json as _json
    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return JSONResponse({"ok": True, "mockup": None})
    try:
        mockup = _json.loads(files[0].get("content", "") or "{}")
        return JSONResponse({"ok": True, "mockup": mockup})
    except Exception as e:
        return JSONResponse({"error": f"Mockup salvo invalido: {e}"}, status_code=500)


@router.get("/api/admin/mockup-report")
async def api_mockup_report(request: Request, user=Depends(require_admin), project_id: str = ""):
    """
    Render the saved channel mockup as a print-friendly HTML report.
    When opened in a new tab the page auto-triggers window.print() so the
    mentor can save it as PDF and forward to the student.
    """
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    import json as _json
    import html as _html
    from database import get_files, get_project

    proj = get_project(project_id)
    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return HTMLResponse("<h1>Mockup nao encontrado para este projeto.</h1>", status_code=404)
    try:
        m = _json.loads(files[0].get("content", "") or "{}")
    except Exception as e:
        return HTMLResponse(f"<h1>Mockup invalido: {_html.escape(str(e))}</h1>", status_code=500)

    def esc(s) -> str:
        return _html.escape(str(s or ""))

    images = m.get("images") or {}
    colors = m.get("colors") or {}
    primary = esc(colors.get("primary") or "#7c3aed")
    accent = esc(colors.get("accent") or "#fbbf24")

    channel_name = esc(m.get("channel_name") or (proj or {}).get("name") or "Canal")
    tagline = esc(m.get("tagline") or "")
    description = esc(m.get("description") or "")
    disclaimer = esc(m.get("disclaimer") or "")
    sub_est = esc(m.get("subscriber_estimate") or "")
    sub_12 = esc(m.get("subscriber_estimate_12m") or "")
    language = esc(m.get("language") or m.get("description_language") or "pt-BR")
    whats_better = esc(m.get("whats_better") or "")
    strategy_edge = esc(m.get("strategy_edge") or "")
    weaknesses = m.get("weaknesses_fixed") or []
    tags = m.get("tags") or []
    hashtags = m.get("hashtags") or []
    keywords = m.get("keywords") or []
    videos = m.get("videos") or []

    banner_pos = esc(m.get("banner_position") or "center")
    banner_html = (
        f'<img src="{esc(images.get("banner"))}" alt="Banner" style="object-position:{banner_pos}" />'
        if images.get("banner")
        else f'<div class="placeholder banner-ph">Banner não gerado</div>'
    )
    logo_html = (
        f'<img src="{esc(images.get("logo"))}" alt="Logo" />'
        if images.get("logo")
        else f'<div class="placeholder logo-ph">Logo</div>'
    )

    videos_html = ""
    for i, v in enumerate(videos[:4]):
        thumb_url = images.get(f"thumb{i}")
        thumb = (
            f'<img src="{esc(thumb_url)}" alt="Thumb {i + 1}" />'
            if thumb_url
            else '<div class="placeholder thumb-ph">Thumb não gerada</div>'
        )
        views = esc(v.get("views_estimate") or "")
        duration = esc(v.get("duration") or "")
        videos_html += f"""
        <div class="video-card">
            <div class="video-thumb">{thumb}<span class="duration-badge">{duration}</span></div>
            <div class="video-meta">
                <div class="video-num">VÍDEO {i + 1:02d}</div>
                <div class="video-title">{esc(v.get("title") or "")}</div>
                <div class="video-views">▶ {views} views previstos</div>
            </div>
        </div>"""

    weaknesses_html = "".join(f'<li><span class="check">✓</span> {esc(w)}</li>' for w in weaknesses[:6])
    tags_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in tags[:20])
    hashtags_html = "".join(f'<span class="hashtag">{esc(h)}</span>' for h in hashtags[:15])
    keywords_html = "".join(f'<span class="keyword">{esc(k)}</span>' for k in keywords[:15])

    # Pre-build conditional blocks (Python 3.11 forbids backslashes inside f-string expressions)
    disclaimer_block = f'<div class="disclaimer-card"><div class="disclaimer-icon">⚠</div><div class="disclaimer-text">{disclaimer}</div></div>' if disclaimer else ""
    description_block = f'<section class="block"><div class="block-eyebrow">01 · POSICIONAMENTO</div><h2 class="block-title">A promessa do canal</h2><p class="block-body">{description}</p></section>' if description else ""

    superior_inner = ""
    if whats_better:
        superior_inner += f'<p class="block-body">{whats_better}</p>'
    if weaknesses_html:
        superior_inner += f'<div class="weaknesses-title">Fraquezas do mercado que você corrige</div><ul class="weaknesses">{weaknesses_html}</ul>'
    if strategy_edge:
        superior_inner += f'<div class="strategy-callout"><div class="strategy-label">📈 ESTRATÉGIA DE CRESCIMENTO</div><div class="strategy-body">{strategy_edge}</div></div>'
    superior_block = (
        f'<section class="block"><div class="block-eyebrow">03 · DIFERENCIAL COMPETITIVO</div><h2 class="block-title">Por que este canal vai dominar</h2>{superior_inner}</section>'
        if (whats_better or weaknesses_html)
        else ""
    )

    tags_row = f'<div class="seo-row"><div class="seo-label">🏷️ Tags YouTube · {len(tags)}</div><div class="seo-chips">{tags_html}</div></div>' if tags_html else ""
    hashtags_row = f'<div class="seo-row"><div class="seo-label">#️⃣ Hashtags · {len(hashtags)}</div><div class="seo-chips">{hashtags_html}</div></div>' if hashtags_html else ""
    keywords_row = f'<div class="seo-row"><div class="seo-label">🔑 Keywords · {len(keywords)}</div><div class="seo-chips">{keywords_html}</div></div>' if keywords_html else ""
    seo_block = f'<section class="block"><div class="block-eyebrow">04 · SEO PACK</div><h2 class="block-title">Otimização para o algoritmo</h2><p class="block-body small">Conjunto pronto pra colar no YouTube Studio. Tudo no idioma do canal e calibrado pro nicho.</p>{tags_row}{hashtags_row}{keywords_row}</section>' if (tags_html or hashtags_html or keywords_html) else ""

    # Convert "#hex" → "r,g,b" for rgba() interpolation in CSS
    def _hex_to_rgb_str(hex_color: str, fallback: str = "251,191,36") -> str:
        h = (hex_color or "").lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            return fallback
        try:
            return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"
        except ValueError:
            return fallback

    accent_rgb = _hex_to_rgb_str(colors.get("accent") or "#fbbf24", "251,191,36")
    primary_rgb = _hex_to_rgb_str(colors.get("primary") or "#7c3aed", "124,58,237")

    handle = channel_name.lower().replace(" ", "")
    sub_6_display = sub_est or "—"
    sub_12_display = sub_12 or "—"
    rpm_avg_raw = m.get("rpm_estimate") or ""
    rpm_max_raw = m.get("rpm_max") or ""
    rpm_currency = esc(m.get("rpm_currency") or "USD")
    monthly_views_display = esc(m.get("monthly_views_estimate") or "—")
    adsense_display = esc(m.get("adsense_monthly_estimate") or "—")

    # ── Path to first $1,000 ─────────────────────────────────
    # Parse RPM strings like "$2.50", "USD 3.00", "3" → float
    import re as _re_pdf
    def _parse_rpm(s: str) -> float:
        if not s:
            return 0.0
        match = _re_pdf.search(r"(\d+(?:[.,]\d+)?)", str(s))
        if not match:
            return 0.0
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            return 0.0

    rpm_avg_num = _parse_rpm(rpm_avg_raw)
    # Fallback: if AI didn't return rpm_max, default to 2x the avg
    rpm_max_num = _parse_rpm(rpm_max_raw)
    if rpm_max_num == 0 and rpm_avg_num > 0:
        rpm_max_num = round(rpm_avg_num * 2, 2)

    rpm_avg_display = esc(rpm_avg_raw or (f"${rpm_avg_num:.2f}" if rpm_avg_num else "—"))
    rpm_max_display = esc(rpm_max_raw or (f"${rpm_max_num:.2f}" if rpm_max_num else "—"))

    creator_share = 0.55  # YouTube keeps 45%

    def _format_views(n: float) -> str:
        if n <= 0:
            return "—"
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
        if n >= 1_000:
            return f"{n / 1_000:.0f}K"
        return f"{int(n)}"

    if rpm_avg_num > 0:
        views_for_1k_avg = 1000 / (rpm_avg_num * creator_share) * 1000
        views_for_1k_avg_display = _format_views(views_for_1k_avg)
    else:
        views_for_1k_avg_display = "—"

    if rpm_max_num > 0:
        views_for_1k_max = 1000 / (rpm_max_num * creator_share) * 1000
        views_for_1k_max_display = _format_views(views_for_1k_max)
    else:
        views_for_1k_max_display = "—"

    from datetime import datetime as _dt
    today_br = _dt.now().strftime("%d/%m/%Y")

    project_label = esc((proj or {}).get("name") or m.get("channel_name") or "")
    lang_upper = language.upper()

    # Cover hero — uses banner image as background if available
    if images.get("banner"):
        hero_bg = f'background-image: linear-gradient(180deg, rgba(10,10,15,0.55) 0%, rgba(10,10,15,0.95) 100%), url("{esc(images.get("banner"))}"); background-size: cover; background-position: {banner_pos};'
    else:
        hero_bg = f'background: linear-gradient(135deg, {primary}, #0a0a0f);'

    seo_page = (
        f'<div class="page page-break"><div class="page-header"><div class="ph-brand"><div class="ph-brand-dot"></div>SEO Pack</div><div class="ph-channel">{channel_name} · LACASADARK</div></div>{seo_block}<div class="page-footer"><div>{channel_name} · LACASADARK · canaisdarks.com.br</div><div>05</div></div></div>'
        if seo_block
        else ""
    )

    # NOTE: The full HTML template is inlined here as it was in the original dashboard.py.
    # It generates a complete print-friendly PDF report for the channel mockup.
    html_doc = _build_mockup_report_html(
        hero_bg=hero_bg, accent=accent, primary=primary, accent_rgb=accent_rgb, primary_rgb=primary_rgb,
        channel_name=channel_name, tagline=tagline, lang_upper=lang_upper,
        sub_6_display=sub_6_display, sub_12_display=sub_12_display,
        rpm_avg_display=rpm_avg_display, rpm_max_display=rpm_max_display,
        rpm_currency=rpm_currency, monthly_views_display=monthly_views_display,
        adsense_display=adsense_display, views_for_1k_avg_display=views_for_1k_avg_display,
        views_for_1k_max_display=views_for_1k_max_display,
        project_label=project_label, today_br=today_br,
        banner_html=banner_html, banner_pos=banner_pos, logo_html=logo_html,
        handle=handle, videos_html=videos_html, videos=videos,
        disclaimer_block=disclaimer_block, description_block=description_block,
        superior_block=superior_block, seo_page=seo_page,
    )
    return HTMLResponse(html_doc)


def _build_mockup_report_html(*, hero_bg, accent, primary, accent_rgb, primary_rgb,
                               channel_name, tagline, lang_upper,
                               sub_6_display, sub_12_display,
                               rpm_avg_display, rpm_max_display,
                               rpm_currency, monthly_views_display,
                               adsense_display, views_for_1k_avg_display,
                               views_for_1k_max_display,
                               project_label, today_br,
                               banner_html, banner_pos, logo_html,
                               handle, videos_html, videos,
                               disclaimer_block, description_block,
                               superior_block, seo_page):
    """Build the full HTML document for the mockup report."""
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>LACASADARK · Identidade Estratégica — {channel_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif; color: #1a1a1a; background: #f5f5f7; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .doc {{ max-width: 880px; margin: 0 auto; background: #fff; box-shadow: 0 20px 80px rgba(0,0,0,0.08); }}
  .page {{ padding: 60px 64px 90px; min-height: 1100px; position: relative; }}
  .page-break {{ page-break-before: always; }}
  .cover {{ {hero_bg} background-color: #0a0a0f; color: #fff; padding: 80px 64px 50px; min-height: 1100px; display: flex; flex-direction: column; justify-content: space-between; position: relative; overflow: hidden; }}
  .cover-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .cover-brand {{ display: flex; align-items: center; gap: 10px; font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; opacity: 0.85; font-weight: 600; }}
  .cover-brand-dot {{ width: 8px; height: 8px; border-radius: 50%; background: {accent}; box-shadow: 0 0 14px {accent}; }}
  .cover-date {{ font-size: 11px; letter-spacing: 0.15em; text-transform: uppercase; opacity: 0.7; }}
  .cover-center {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
  .cover-eyebrow {{ font-size: 12px; letter-spacing: 0.4em; text-transform: uppercase; color: {accent}; font-weight: 700; margin-bottom: 18px; }}
  .cover-title {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 76px; line-height: 0.95; letter-spacing: -0.02em; font-weight: 600; margin: 0 0 18px; text-shadow: 0 4px 30px rgba(0,0,0,0.6); }}
  .cover-tagline {{ font-size: 18px; line-height: 1.5; font-weight: 300; max-width: 580px; opacity: 0.92; font-style: italic; }}
  .cover-divider {{ width: 60px; height: 3px; background: {accent}; margin: 28px 0; border-radius: 2px; }}
  .cover-meta {{ display: flex; gap: 36px; margin-top: 32px; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500; opacity: 0.85; }}
  .cover-meta span strong {{ display: block; color: {accent}; font-size: 14px; margin-bottom: 4px; font-weight: 700; letter-spacing: 0.05em; }}
  .cover-bottom {{ padding-top: 28px; border-top: 1px solid rgba(255,255,255,0.18); display: flex; justify-content: space-between; align-items: center; font-size: 10px; letter-spacing: 0.15em; text-transform: uppercase; opacity: 0.6; }}
  .page-header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 22px; margin-bottom: 38px; border-bottom: 1px solid #ececef; }}
  .ph-brand {{ display: flex; align-items: center; gap: 8px; font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: #888; font-weight: 600; }}
  .ph-brand-dot {{ width: 6px; height: 6px; border-radius: 50%; background: {primary}; }}
  .ph-channel {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 16px; color: #1a1a1a; font-weight: 600; }}
  .page-footer {{ position: absolute; bottom: 30px; left: 64px; right: 64px; display: flex; justify-content: space-between; font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase; color: #aaa; padding-top: 14px; border-top: 1px solid #ececef; }}
  .block {{ margin-bottom: 50px; }}
  .block-eyebrow {{ font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase; color: {primary}; font-weight: 700; margin-bottom: 12px; }}
  .block-title {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 38px; line-height: 1.05; letter-spacing: -0.01em; font-weight: 600; color: #0f0f12; margin: 0 0 22px; }}
  .block-body {{ font-size: 14px; line-height: 1.75; color: #2a2a30; margin: 0 0 14px; font-weight: 400; }}
  .block-body.small {{ font-size: 12px; color: #666; margin-bottom: 22px; }}
  .disclaimer-card {{ display: flex; gap: 14px; align-items: flex-start; background: linear-gradient(135deg, #fffbeb, #fef3c7); border: 1px solid #fcd34d; border-left: 4px solid {accent}; border-radius: 10px; padding: 16px 20px; margin-bottom: 32px; }}
  .disclaimer-icon {{ font-size: 22px; line-height: 1; color: #b45309; }}
  .disclaimer-text {{ font-size: 12px; line-height: 1.6; color: #78350f; font-weight: 500; }}
  .identity-card {{ border-radius: 14px; overflow: hidden; box-shadow: 0 8px 30px rgba(0,0,0,0.06); border: 1px solid #ececef; margin-bottom: 38px; }}
  .identity-banner {{ width: 100%; aspect-ratio: 5.4/1; max-height: 280px; min-height: 150px; overflow: hidden; background: #0f0f12; }}
  .identity-banner img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .identity-row {{ display: flex; align-items: center; gap: 22px; padding: 24px 28px; background: #fff; }}
  .identity-logo {{ width: 92px; height: 92px; border-radius: 50%; overflow: hidden; flex-shrink: 0; background: linear-gradient(135deg, {primary}, {accent}); display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 800; font-size: 36px; box-shadow: 0 6px 20px rgba(0,0,0,0.12); border: 3px solid #fff; }}
  .identity-logo img {{ width: 135%; height: 135%; object-fit: cover; }}
  .identity-name {{ flex: 1; min-width: 0; }}
  .identity-name h3 {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 30px; line-height: 1; font-weight: 700; margin: 0 0 4px; color: #0f0f12; letter-spacing: -0.01em; }}
  .identity-handle {{ font-size: 12px; color: #888; font-weight: 500; }}
  .identity-tag {{ font-size: 13px; color: #444; margin-top: 6px; font-style: italic; line-height: 1.5; }}
  .identity-cta {{ padding: 10px 22px; border-radius: 22px; background: #0f0f12; color: #fff; font-size: 12px; font-weight: 700; flex-shrink: 0; }}
  .identity-tabs {{ display: flex; gap: 0; padding: 0 28px; border-top: 1px solid #ececef; background: #fff; }}
  .identity-tab {{ padding: 14px 18px; font-size: 12px; font-weight: 500; color: #888; border-bottom: 2px solid transparent; }}
  .identity-tab.active {{ color: #0f0f12; font-weight: 700; border-bottom-color: #0f0f12; }}
  .identity-videos {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; padding: 18px 22px 24px; background: #fff; }}
  .identity-videos .video-card {{ border: none; box-shadow: none; background: transparent; border-radius: 8px; }}
  .identity-videos .video-thumb {{ border-radius: 8px; }}
  .identity-videos .video-meta {{ padding: 8px 2px 0; }}
  .identity-videos .video-num {{ font-size: 7px; margin-bottom: 3px; }}
  .identity-videos .video-title {{ font-size: 11px; line-height: 1.35; -webkit-line-clamp: 2; display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }}
  .identity-videos .video-views {{ font-size: 9px; }}
  .identity-videos .duration-badge {{ font-size: 8px; padding: 2px 5px; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 38px; }}
  .stats-grid-5 {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 24px; }}
  .stats-grid-5 .stat-card {{ padding: 18px 14px; }}
  .stats-grid-5 .stat-value {{ font-size: 26px; }}
  .stats-grid-5 .stat-label {{ font-size: 8px; }}
  .stats-grid-5 .stat-sub {{ font-size: 9px; }}
  .stat-card {{ border: 1px solid #ececef; border-radius: 12px; padding: 22px 20px; background: linear-gradient(180deg, #fff, #fafafb); position: relative; }}
  .stat-card::before {{ content: ''; position: absolute; top: 0; left: 0; width: 38px; height: 3px; background: {primary}; border-radius: 0 0 3px 0; }}
  .stat-label {{ font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: #888; font-weight: 700; margin-bottom: 10px; }}
  .stat-value {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 32px; line-height: 1; font-weight: 700; color: #0f0f12; }}
  .stat-sub {{ font-size: 10px; color: #aaa; margin-top: 4px; }}
  .stat-card.accent {{ background: linear-gradient(180deg, {primary}, #1a1a2e); border: none; }}
  .stat-card.accent::before {{ background: {accent}; }}
  .stat-card.accent .stat-label {{ color: rgba(255,255,255,0.65); }}
  .stat-card.accent .stat-value {{ color: #fff; }}
  .stat-card.accent .stat-sub {{ color: rgba(255,255,255,0.55); }}
  .videos-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .video-card {{ border-radius: 12px; overflow: hidden; background: #fff; border: 1px solid #ececef; box-shadow: 0 4px 16px rgba(0,0,0,0.04); page-break-inside: avoid; }}
  .video-thumb {{ width: 100%; aspect-ratio: 16/9; background: #0f0f12; position: relative; overflow: hidden; }}
  .video-thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .duration-badge {{ position: absolute; bottom: 8px; right: 8px; background: rgba(0,0,0,0.85); color: #fff; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; }}
  .video-meta {{ padding: 14px 16px 16px; }}
  .video-num {{ font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: {primary}; font-weight: 800; margin-bottom: 6px; }}
  .video-title {{ font-weight: 600; font-size: 13px; color: #0f0f12; line-height: 1.4; margin-bottom: 8px; }}
  .video-views {{ font-size: 11px; color: #999; font-weight: 500; }}
  .placeholder {{ width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #aaa; font-size: 11px; background: repeating-linear-gradient(45deg, #f5f5f7, #f5f5f7 8px, #ececef 8px, #ececef 16px); }}
  .weaknesses-title {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #c2410c; font-weight: 700; margin: 22px 0 12px; }}
  .weaknesses {{ list-style: none; padding: 0; margin: 0 0 22px; }}
  .weaknesses li {{ font-size: 13px; line-height: 1.6; color: #2a2a30; padding: 10px 0; border-bottom: 1px solid #f0f0f3; display: flex; gap: 10px; align-items: flex-start; }}
  .weaknesses li:last-child {{ border-bottom: none; }}
  .check {{ color: #16a34a; font-weight: 800; flex-shrink: 0; font-size: 14px; }}
  .strategy-callout {{ background: linear-gradient(135deg, #f0fdf4, #dcfce7); border: 1px solid #86efac; border-left: 4px solid #16a34a; border-radius: 10px; padding: 18px 22px; margin-top: 22px; }}
  .strategy-label {{ font-size: 9px; letter-spacing: 0.25em; text-transform: uppercase; color: #166534; font-weight: 800; margin-bottom: 8px; }}
  .strategy-body {{ font-size: 13px; line-height: 1.65; color: #14532d; font-weight: 500; font-style: italic; }}
  .seo-row {{ margin-bottom: 26px; }}
  .seo-label {{ font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase; color: #555; font-weight: 700; margin-bottom: 10px; }}
  .seo-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .tag, .hashtag, .keyword {{ display: inline-block; padding: 5px 12px; border-radius: 6px; font-size: 11px; font-weight: 500; }}
  .tag {{ background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }}
  .hashtag {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }}
  .keyword {{ background: #faf5ff; color: #7c3aed; border: 1px solid #ddd6fe; }}
  .path-1k {{ background: linear-gradient(135deg, #0f0f12, #1a1a2e); border-radius: 14px; padding: 26px 28px 24px; margin: 28px 0 24px; color: #fff; position: relative; overflow: hidden; }}
  .path-1k::before {{ content: ''; position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: {accent}; }}
  .path-1k-header {{ margin-bottom: 20px; }}
  .path-1k-eyebrow {{ font-size: 9px; letter-spacing: 0.3em; text-transform: uppercase; color: {accent}; font-weight: 800; margin-bottom: 8px; }}
  .path-1k-title {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 24px; line-height: 1.2; font-weight: 600; margin: 0; color: #fff; letter-spacing: -0.01em; }}
  .path-1k-grid {{ display: grid; grid-template-columns: 1.1fr 1fr 1fr; gap: 16px; align-items: stretch; }}
  .path-1k-card {{ background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 18px 18px; display: flex; flex-direction: column; justify-content: center; }}
  .path-1k-card.best {{ background: linear-gradient(135deg, rgba({accent_rgb},0.22), rgba(255,255,255,0.04)); border-color: {accent}; }}
  .path-1k-card-label {{ font-size: 9px; letter-spacing: 0.16em; text-transform: uppercase; color: rgba(255,255,255,0.65); font-weight: 700; margin-bottom: 10px; }}
  .path-1k-card.best .path-1k-card-label {{ color: {accent}; }}
  .path-1k-card-value {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 38px; line-height: 1; font-weight: 700; color: #fff; margin-bottom: 6px; }}
  .path-1k-card-sub {{ font-size: 10px; color: rgba(255,255,255,0.55); }}
  .path-1k-medal {{ background: linear-gradient(135deg, rgba({accent_rgb},0.18), rgba(0,0,0,0.4)); border: 2px solid {accent}; border-radius: 14px; padding: 18px 14px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; position: relative; box-shadow: inset 0 0 30px rgba({accent_rgb},0.15); }}
  .medal-ring {{ width: 130px; height: 130px; border-radius: 50%; background: radial-gradient(circle at 30% 30%, rgba({accent_rgb},0.95), rgba({accent_rgb},0.55) 60%, rgba({accent_rgb},0.3)); display: flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: 0 0 40px rgba({accent_rgb},0.4), inset 0 -8px 20px rgba(0,0,0,0.3), inset 0 4px 12px rgba(255,255,255,0.3); border: 3px solid rgba(255,255,255,0.4); }}
  .medal-amount {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 36px; font-weight: 700; color: #1a0f00; line-height: 1; text-shadow: 0 1px 2px rgba(255,255,255,0.4); }}
  .medal-label {{ font-size: 8px; letter-spacing: 0.18em; text-transform: uppercase; color: rgba(26,15,0,0.75); font-weight: 800; margin-top: 4px; }}
  .medal-badge {{ font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase; color: {accent}; font-weight: 800; padding: 5px 12px; border: 1px solid {accent}; border-radius: 999px; background: rgba(0,0,0,0.4); }}
  .reality-note {{ background: #fff8eb; border: 1px solid #fde68a; border-left: 3px solid #d97706; border-radius: 8px; padding: 12px 16px; font-size: 11px; line-height: 1.55; color: #78350f; margin-top: 8px; margin-bottom: 38px; }}
  .reality-note strong {{ color: #92400e; font-weight: 700; }}
  .reality-note em {{ font-style: italic; color: #92400e; }}
  .back-cover {{ background: #0f0f12; color: #fff; min-height: 800px; padding: 180px 64px 80px; text-align: center; }}
  .back-eyebrow {{ font-size: 11px; letter-spacing: 0.4em; text-transform: uppercase; color: {accent}; font-weight: 700; margin-bottom: 24px; }}
  .back-title {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 48px; font-weight: 600; margin: 0 0 22px; line-height: 1.05; letter-spacing: -0.01em; }}
  .back-text {{ font-size: 15px; line-height: 1.75; max-width: 520px; margin: 0 auto 40px; color: rgba(255,255,255,0.78); font-weight: 300; }}
  .back-line {{ width: 60px; height: 3px; background: {accent}; margin: 0 auto 40px; border-radius: 2px; }}
  .back-meta {{ font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase; color: rgba(255,255,255,0.5); }}
  .print-bar {{ position: fixed; top: 16px; right: 16px; background: #0f0f12; color: #fff; padding: 12px 18px; border-radius: 12px; font-size: 12px; z-index: 9999; box-shadow: 0 12px 40px rgba(0,0,0,0.4); display: flex; align-items: center; gap: 14px; }}
  .print-bar button {{ padding: 8px 16px; background: {accent}; color: #0f0f12; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 12px; }}
  @media print {{
    body {{ background: #fff; }}
    .print-bar {{ display: none; }}
    .doc {{ box-shadow: none; max-width: none; }}
    .page {{ padding: 50px 50px 80px; }}
    .cover {{ padding: 70px 50px 50px; }}
    .back-cover {{ padding: 160px 50px 70px; }}
    .page-footer {{ left: 50px; right: 50px; }}
    section {{ page-break-inside: avoid; }}
    .video-card {{ page-break-inside: avoid; }}
  }}
  @page {{ size: A4; margin: 0; }}
</style>
</head>
<body>
<div class="print-bar">
  💡 Use "Salvar como PDF" no diálogo de impressão
  <button onclick="window.print()">📄 Salvar PDF</button>
</div>

<div class="doc">

  <!-- COVER -->
  <div class="cover">
    <div class="cover-top">
      <div class="cover-brand"><div class="cover-brand-dot"></div>LACASADARK · Mentoria</div>
      <div class="cover-date">{today_br}</div>
    </div>
    <div class="cover-center">
      <div class="cover-eyebrow">Documento Confidencial · Identidade Estratégica</div>
      <h1 class="cover-title">{channel_name}</h1>
      <div class="cover-divider"></div>
      <div class="cover-tagline">{tagline}</div>
      <div class="cover-meta">
        <span><strong>{lang_upper}</strong>Idioma</span>
        <span><strong>{sub_6_display}</strong>Inscritos · 6m</span>
        <span><strong>{sub_12_display}</strong>Inscritos · 12m</span>
        <span><strong>{rpm_avg_display}</strong>RPM médio</span>
      </div>
    </div>
    <div class="cover-bottom">
      <div>Projeto · {project_label}</div>
      <div>LACASADARK · canaisdarks.com.br</div>
    </div>
  </div>

  <!-- PAGE 2 — IDENTIDADE -->
  <div class="page page-break">
    <div class="page-header">
      <div class="ph-brand"><div class="ph-brand-dot"></div>Identidade Visual</div>
      <div class="ph-channel">{channel_name} · LACASADARK</div>
    </div>

    {disclaimer_block}

    <div class="block">
      <div class="block-eyebrow">02 · IDENTIDADE VISUAL</div>
      <h2 class="block-title">Como o canal aparece no YouTube</h2>
      <p class="block-body small">Mockup completo do canal — banner, logo, header e os 4 vídeos iniciais. Pronto pra você reproduzir no canal real.</p>

      <div class="identity-card">
        <div class="identity-banner">{banner_html}</div>
        <div class="identity-row">
          <div class="identity-logo">{logo_html}</div>
          <div class="identity-name">
            <h3>{channel_name} ✓</h3>
            <div class="identity-handle">@{handle} · {len(videos)} vídeos · {sub_6_display} inscritos previstos</div>
            <div class="identity-tag">{tagline}</div>
          </div>
          <div class="identity-cta">Inscrever-se</div>
        </div>
        <div class="identity-tabs">
          <div class="identity-tab active">Início</div>
          <div class="identity-tab">Vídeos</div>
          <div class="identity-tab">Playlists</div>
          <div class="identity-tab">Posts</div>
        </div>
        <div class="identity-videos">{videos_html}</div>
      </div>
    </div>

    <div class="page-footer">
      <div>{channel_name} · LACASADARK · canaisdarks.com.br</div>
      <div>02</div>
    </div>
  </div>

  <!-- PAGE 3 — PROJEÇÃO FINANCEIRA + DESCRIÇÃO -->
  <div class="page page-break">
    <div class="page-header">
      <div class="ph-brand"><div class="ph-brand-dot"></div>Projeção &amp; Posicionamento</div>
      <div class="ph-channel">{channel_name} · LACASADARK</div>
    </div>

    <div class="block">
      <div class="block-eyebrow">03 · PROJEÇÃO ESTIMADA</div>
      <h2 class="block-title">Potencial financeiro do canal</h2>
      <p class="block-body small">Suposições baseadas em médias de mercado de canais bem executados no nicho. Não são promessas — são referências do que é possível com disciplina, consistência e qualidade de execução.</p>

      <div class="stats-grid-5">
        <div class="stat-card">
          <div class="stat-label">Inscritos · 6m</div>
          <div class="stat-value">{sub_6_display}</div>
          <div class="stat-sub">Estimativa</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Inscritos · 12m</div>
          <div class="stat-value">{sub_12_display}</div>
          <div class="stat-sub">Estimativa</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">RPM Médio</div>
          <div class="stat-value">{rpm_avg_display}</div>
          <div class="stat-sub">{rpm_currency} · típico</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">RPM Máximo</div>
          <div class="stat-value">{rpm_max_display}</div>
          <div class="stat-sub">{rpm_currency} · pico nicho</div>
        </div>
        <div class="stat-card accent">
          <div class="stat-label">AdSense/mês</div>
          <div class="stat-value">{adsense_display}</div>
          <div class="stat-sub">{monthly_views_display} views/mês</div>
        </div>
      </div>

      <!-- Path to first $1000 -->
      <div class="path-1k">
        <div class="path-1k-header">
          <div class="path-1k-eyebrow">PRIMEIRA GRANDE META</div>
          <h3 class="path-1k-title">Quanto o canal precisa entregar para o primeiro $1K?</h3>
        </div>
        <div class="path-1k-grid">
          <div class="path-1k-medal">
            <div class="medal-ring">
              <div class="medal-amount">$1.000</div>
              <div class="medal-label">PRIMEIRA META</div>
            </div>
            <div class="medal-badge">🏆 ALCANÇADO</div>
          </div>
          <div class="path-1k-card">
            <div class="path-1k-card-label">Cenário Médio · RPM {rpm_avg_display}</div>
            <div class="path-1k-card-value">{views_for_1k_avg_display}</div>
            <div class="path-1k-card-sub">views totais necessárias</div>
          </div>
          <div class="path-1k-card best">
            <div class="path-1k-card-label">Cenário Pico · RPM {rpm_max_display}</div>
            <div class="path-1k-card-value">{views_for_1k_max_display}</div>
            <div class="path-1k-card-sub">views totais necessárias</div>
          </div>
        </div>
      </div>

      <div class="reality-note">⚠ <strong>Tudo isto é uma suposição</strong> baseada em médias de canais bem executados no mesmo nicho. Os números reais dependem de <em>consistência de postagem, qualidade de hooks, retenção, CTR e otimização contínua</em>. Use como referência de potencial, não como garantia.</div>
    </div>

    {description_block}

    <div class="page-footer">
      <div>{channel_name} · LACASADARK · canaisdarks.com.br</div>
      <div>03</div>
    </div>
  </div>

  <!-- PAGE 4 — DIFERENCIAL -->
  <div class="page page-break">
    <div class="page-header">
      <div class="ph-brand"><div class="ph-brand-dot"></div>Diferencial Competitivo</div>
      <div class="ph-channel">{channel_name} · LACASADARK</div>
    </div>

    {superior_block}

    <div class="page-footer">
      <div>{channel_name} · LACASADARK · canaisdarks.com.br</div>
      <div>04</div>
    </div>
  </div>

  <!-- PAGE 4 — SEO -->
  {seo_page}

  <!-- BACK COVER -->
  <div class="back-cover page-break">
    <div class="back-eyebrow">Próximo passo</div>
    <h2 class="back-title">Agora é executar.</h2>
    <p class="back-text">Use este documento como blueprint. Cada elemento foi desenhado pra que seu canal nasça posicionado pra dominar o nicho desde o primeiro upload. Consistência + hooks fortes + qualidade = crescimento real.</p>
    <div class="back-line"></div>
    <div style="font-family: 'Cormorant Garamond', Georgia, serif; font-size: 32px; font-weight: 600; color: #fff; margin-bottom: 6px; letter-spacing: 0.04em;">LACASADARK</div>
    <div style="font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase; color: rgba(255,255,255,0.55); margin-bottom: 14px;">Mentoria de Canais Faceless</div>
    <div style="font-size: 13px; color: {accent}; font-weight: 600; letter-spacing: 0.05em; margin-bottom: 32px;">canaisdarks.com.br</div>
    <div class="back-meta">Documento gerado em {today_br}</div>
  </div>

</div>

<script>
  window.addEventListener('load', function() {{
    setTimeout(function() {{ window.print(); }}, 800);
  }});
</script>
</body>
</html>"""


@router.post("/api/admin/save-mockup-banner-position")
@limiter.limit("60/minute")
async def api_save_mockup_banner_position(request: Request, user=Depends(require_admin)):
    """
    Persist the user-chosen banner position (drag-to-reposition). The position
    is stored as a CSS background-position string ("50% 30%") in
    mockup['banner_position'].
    """
    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    position = (body.get("position") or "").strip()
    if not project_id or not position:
        return JSONResponse({"error": "project_id e position obrigatorios"}, status_code=400)
    # Sanity check — only digits, %, decimal dot and spaces
    import re as _re
    if not _re.match(r"^[\d\.\s%]+$", position) or len(position) > 30:
        return JSONResponse({"error": "position invalida"}, status_code=400)

    import json as _json
    from database import get_files, get_db

    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return JSONResponse({"error": "Mockup nao encontrado"}, status_code=404)
    try:
        mockup = _json.loads(files[0].get("content", "") or "{}")
    except Exception as e:
        return JSONResponse({"error": f"Mockup invalido: {e}"}, status_code=500)

    mockup["banner_position"] = position
    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE files SET content=? WHERE id=?",
                (_json.dumps(mockup, ensure_ascii=False, indent=2), files[0]["id"]),
            )
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)

    return JSONResponse({"ok": True})


@router.post("/api/admin/save-mockup-image")
@limiter.limit("60/minute")
async def api_save_mockup_image(request: Request, user=Depends(require_admin)):
    """
    Persist a generated image URL on the saved mockup file under
    mockup['images'][slot]. The slot is one of: logo, banner, thumb0..3.
    """
    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    slot = (body.get("slot") or "").strip()
    url = (body.get("url") or "").strip()
    if not project_id or not slot or not url:
        return JSONResponse({"error": "project_id, slot e url obrigatorios"}, status_code=400)

    import json as _json
    from database import get_files, get_db

    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return JSONResponse({"error": "Mockup nao encontrado"}, status_code=404)
    try:
        mockup = _json.loads(files[0].get("content", "") or "{}")
    except Exception as e:
        return JSONResponse({"error": f"Mockup invalido: {e}"}, status_code=500)

    images = mockup.get("images") or {}
    images[slot] = url
    mockup["images"] = images

    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE files SET content=? WHERE id=?",
                (_json.dumps(mockup, ensure_ascii=False, indent=2), files[0]["id"]),
            )
    except Exception as e:
        logger.warning(f"save-mockup-image failed: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)

    return JSONResponse({"ok": True})


@router.post("/api/admin/translate-mockup-description")
@limiter.limit("10/minute")
async def api_translate_mockup_description(request: Request, user=Depends(require_admin)):
    """
    Translate the saved mockup description into a target language and persist
    the change so the next render shows it. Returns the updated description.
    """
    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    target_language = (body.get("language") or "").strip()
    if not project_id or not target_language:
        return JSONResponse({"error": "project_id e language obrigatorios"}, status_code=400)

    import json as _json
    from database import get_files, get_db

    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return JSONResponse({"error": "Mockup nao encontrado"}, status_code=404)

    try:
        mockup = _json.loads(files[0].get("content", "") or "{}")
    except Exception as e:
        return JSONResponse({"error": f"Mockup salvo invalido: {e}"}, status_code=500)

    original_desc = (mockup.get("description") or "").strip()
    if not original_desc:
        return JSONResponse({"error": "Sem descricao para traduzir"}, status_code=400)

    from protocols.ai_client import chat
    import asyncio

    system = (
        "Voce e um tradutor profissional especializado em conteudo para YouTube. "
        "Traduza o texto preservando tom, estrutura e impacto emocional. "
        "Retorne APENAS a traducao, sem explicacoes, sem aspas, sem preambulo."
    )
    user_prompt = (
        f"Traduza a descricao de canal abaixo para o idioma: {target_language}.\n"
        f"Mantenha o mesmo comprimento aproximado e o mesmo estilo persuasivo.\n\n"
        f"TEXTO ORIGINAL:\n{original_desc}"
    )

    try:
        translated = await asyncio.to_thread(
            chat,
            prompt=user_prompt,
            system=system,
            max_tokens=1500,
            temperature=0.4,
            timeout=120,
        )
    except Exception as e:
        logger.exception(f"translate-mockup-description error: {e}")
        return JSONResponse({"error": f"Falha na traducao: {str(e)[:200]}"}, status_code=502)

    translated = (translated or "").strip()
    if not translated:
        return JSONResponse({"error": "Tradutor retornou vazio"}, status_code=502)

    new_mockup = {**mockup, "description": translated, "description_language": target_language}
    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE files SET content=? WHERE id=?",
                (_json.dumps(new_mockup, ensure_ascii=False, indent=2), files[0]["id"]),
            )
    except Exception as e:
        logger.warning(f"translate-mockup-description: failed to persist: {e}")

    return JSONResponse({"ok": True, "description": translated, "language": target_language})


@router.post("/api/admin/generate-mockup-image")
@limiter.limit("20/minute")
async def api_generate_mockup_image(request: Request, user=Depends(require_admin)):
    """
    Generate a single image via ImageFX for a mockup field (logo/banner/thumb).
    Returns a data:image/png;base64 URL the frontend can render directly.
    """
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    aspect = (body.get("aspect") or "LANDSCAPE").upper()
    if not prompt:
        return JSONResponse({"error": "prompt obrigatorio"}, status_code=400)

    import asyncio
    from protocols.imagefx_client import get_client, ImageFXError

    try:
        client = get_client()
    except ImageFXError as e:
        return JSONResponse({"error": str(e), "code": "NO_COOKIE"}, status_code=400)

    try:
        images = await asyncio.to_thread(client.generate, prompt, aspect, 1, 90)
    except ImageFXError as e:
        status = 401 if e.status in (401, 403) else (429 if e.status == 429 else 502)
        return JSONResponse({"error": str(e), "code": f"IMAGEFX_{e.status}"}, status_code=status)
    except Exception as e:
        logger.exception(f"generate-mockup-image error: {e}")
        return JSONResponse({"error": f"Erro inesperado: {str(e)[:200]}"}, status_code=500)

    if not images:
        return JSONResponse({"error": "Nenhuma imagem gerada"}, status_code=502)

    return JSONResponse({"ok": True, "url": images[0]["url"], "seed": images[0].get("seed")})


@router.post("/api/admin/imagefx-cookie")
@limiter.limit("5/minute")
async def api_imagefx_cookie_save(request: Request, user=Depends(require_admin)):
    """Save (Fernet-encrypted) ImageFX cookie. Pass empty string to clear."""
    body = await request.json()
    cookie = (body.get("cookie") or "").strip()
    from protocols.imagefx_client import set_imagefx_cookie
    try:
        set_imagefx_cookie(cookie)
        return JSONResponse({"ok": True, "cleared": not cookie})
    except Exception as e:
        logger.exception(f"imagefx-cookie save error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.get("/api/admin/imagefx-cookie/status")
async def api_imagefx_cookie_status(request: Request, user=Depends(require_admin)):
    """
    Diagnostic: returns whether a cookie is saved and tries to fetch a session
    to confirm it's still valid. Bypasses any cache.
    """
    from protocols.imagefx_client import get_imagefx_cookie, ImageFXClient, ImageFXError
    cookie = get_imagefx_cookie()
    if not cookie:
        return JSONResponse({
            "configured": False,
            "valid": False,
            "hint": "Cookie nao configurado. Cole o cookie do labs.google na pagina de Admin.",
        })
    masked = (cookie[:30] + "…") if len(cookie) > 30 else cookie
    try:
        client = ImageFXClient(cookie)
        # Trigger a session fetch but don't generate an image (cheap call)
        client._refresh_session_if_needed()
        return JSONResponse({
            "configured": True,
            "valid": True,
            "cookie_length": len(cookie),
            "cookie_masked": masked,
            "hint": "✅ Cookie valido — sessao ativa.",
        })
    except ImageFXError as e:
        return JSONResponse({
            "configured": True,
            "valid": False,
            "cookie_length": len(cookie),
            "cookie_masked": masked,
            "error": str(e),
            "hint": "❌ Cookie invalido ou expirado. Atualize cole um novo do labs.google.",
        })
